"""Coverage Time Machine (pure): frames over the horizon, shift lanes, demand bands.

Deterministic layer. Frames sample the exact piecewise coverage models every ``step``
minutes *and* at every exact change point (shift start/end, requirement block, spike
end), so a 19:07 shift end is never rounded to 19:05. Only the ``now`` frame is observed;
every other frame is projected.

Stochastic layer (labelled sensitivity, not a forecast of real patients). Arrivals per
hospital are drawn from a Poisson process whose hourly rate is the hospital's baseline
*mean* for the local hour (× ``rate_multiplier``), with a fixed NumPy seed. For each
sample time the trailing-60-minute arrivals = known arrivals still inside the window +
simulated future arrivals. Reported: p10/p50/p90 across runs, and the share of runs in
which the trailing hour exceeds the hospital's p90 baseline (the brief's spike rule). The
p90 baseline is used only as the spike threshold, never as a distribution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

import numpy as np

from app.engines.analysis import OperationalAnalysis
from app.engines.intelligence.common import Models, evaluation_at
from app.engines.intelligence.config import StochasticPolicy
from app.schemas.intelligence import (
    AvailabilityClass,
    DemandBand,
    ShiftLane,
    ShiftLaneSegment,
    TimeMachineFrame,
    TimeMachineHospital,
    TimeMachineReport,
)


def _frame_times(
    models: Models, as_of: datetime, horizon: int, step: int
) -> list[tuple[datetime, str]]:
    end = as_of + timedelta(minutes=horizon)
    times: dict[datetime, str] = {}
    t = as_of
    while t < end:
        times[t] = "step"
        t += timedelta(minutes=step)
    for m in models.values():
        for a, _b, _e in m.evaluations():
            if as_of < a < end:
                times.setdefault(a, "boundary")
    times[as_of] = "now"
    times[end] = "horizon_end"
    return sorted(times.items())


def _labels(analysis: OperationalAnalysis, models: Models, a: datetime, b: datetime) -> list[str]:
    out = []
    for hid, m in models.items():
        for w in m.windows:
            if w.start is not None and a < w.start <= b and w.start > analysis.state.as_of:
                out.append(f"+{w.name} ({hid})")
            if w.end is not None and a < w.end <= b:
                out.append(f"−{w.name} ({hid})")
    return sorted(set(out))


def stochastic_demand(
    analysis: OperationalAnalysis, horizon: int, policy: StochasticPolicy
) -> tuple[list[DemandBand], dict]:
    as_of = analysis.state.as_of
    rng = np.random.default_rng(policy.seed)
    step = policy.step_minutes
    n_steps = max(1, horizon // step)
    bands: list[DemandBand] = []
    window = timedelta(minutes=60)
    for hid in sorted(analysis.demand_models):
        dm = analysis.demand_models[hid]
        rates = []
        for k in range(n_steps):
            t0 = as_of + timedelta(minutes=k * step)
            row = dm.baseline_at(t0)
            rate = (row.mean_consults if row else 0.0) * policy.rate_multiplier * step / 60
            rates.append(rate)
        draws = rng.poisson(lam=np.array(rates), size=(policy.runs, n_steps))
        for k in range(1, n_steps + 1):
            t = as_of + timedelta(minutes=k * step)
            known = sum(1 for a in dm.arrival_times if t - window < a <= as_of)
            first = max(0, k - 60 // step)
            future = draws[:, first:k].sum(axis=1) + known
            row = dm.baseline_at(t)
            threshold = row.p90_consults if row else None
            share = float((future > threshold).mean()) if threshold is not None else 0.0
            bands.append(
                DemandBand(
                    hospital_id=hid,
                    at=t,
                    expected_arrivals=round(float(rates[k - 1]), 4),
                    p10_trailing_hour=float(np.percentile(future, 10)),
                    p50_trailing_hour=float(np.percentile(future, 50)),
                    p90_trailing_hour=float(np.percentile(future, 90)),
                    p90_threshold=threshold,
                    share_runs_above_threshold=round(share, 4),
                )
            )
    meta = {
        "model": "Poisson arrivals at the baseline hourly mean (local hour) × rate_multiplier",
        "runs": policy.runs,
        "seed": policy.seed,
        "step_minutes": step,
        "rate_multiplier": policy.rate_multiplier,
        "label": "Sensitivity under a stated assumption — not a calibrated probability",
    }
    return bands, meta


def time_machine_report(
    analysis: OperationalAnalysis,
    models: Models,
    classes: Mapping[str, AvailabilityClass],
    *,
    horizon_minutes: int,
    step_minutes: int,
    stochastic: StochasticPolicy,
    freshness: dict,
    pending_shifts: Sequence[dict] = (),
) -> TimeMachineReport:
    state = analysis.state
    as_of = state.as_of
    frames: list[TimeMachineFrame] = []
    times = _frame_times(models, as_of, horizon_minutes, step_minutes)
    prev = as_of
    for t, kind in times:
        hs: list[TimeMachineHospital] = []
        net_req = net_def = short = 0
        for hid in sorted(models):
            m = models[hid]
            piece = evaluation_at(
                m, t if t < m.horizon_end else m.horizon_end - timedelta(seconds=1)
            )
            if piece is None:
                continue
            e = piece[2]
            spike = None
            dm = analysis.demand_models.get(hid)
            if dm is not None:
                spike = dm.evaluate(t).spike
            hs.append(
                TimeMachineHospital(
                    hospital_id=hid,
                    required=e.required,
                    confirmed=len(e.confirmed),
                    uncertain=len(e.active) - len(e.confirmed),
                    deficit=e.deficit,
                    spike=spike,
                )
            )
            net_req += e.required or 0
            net_def += e.deficit or 0
            short += 1 if (e.deficit or 0) > 0 else 0
        frames.append(
            TimeMachineFrame(
                at=t,
                offset_minutes=round((t - as_of).total_seconds() / 60, 2),
                kind=kind,  # type: ignore[arg-type]
                observed=kind == "now",
                network_required=net_req,
                network_deficit=net_def,
                hospitals_short=short,
                hospitals=hs,
                labels=_labels(analysis, models, prev, t) if t > as_of else [],
            )
        )
        prev = t

    end = as_of + timedelta(minutes=horizon_minutes)
    lanes: list[ShiftLane] = []
    windows_by_p: dict[str, list] = {}
    for m in models.values():
        for w in m.windows:
            windows_by_p.setdefault(w.physician_id, []).append(w)
    for p in sorted(state.physicians, key=lambda x: x.physician_id):
        segs: list[ShiftLaneSegment] = []
        if p.temporary_shift is not None:
            t = p.temporary_shift
            segs.append(
                ShiftLaneSegment(
                    start=t.expected_online_at
                    if t.phase == "preparing"
                    else (t.activated_at or t.start_at),
                    end=t.end_at,
                    kind="rescue_pending" if t.phase == "preparing" else "rescue_active",
                    label=f"Rescue shift {t.intervention_id} ({t.phase})",
                )
            )
        elif p.on_shift and p.scheduled_shift is not None:
            segs.append(
                ShiftLaneSegment(
                    start=p.scheduled_shift.start,
                    end=p.scheduled_shift.end,
                    kind="scheduled",
                    label="Scheduled shift",
                )
            )
        else:
            seen = set()
            for w in sorted(windows_by_p.get(p.physician_id, []), key=lambda w: w.start):
                key = (w.start, w.end)
                if key in seen:
                    continue
                seen.add(key)
                segs.append(
                    ShiftLaneSegment(
                        start=w.start,
                        end=w.end,
                        kind="assumed" if w.certainty == "uncertain" else "scheduled",
                        label="Joins (end unknown)" if w.end is None else "Joins",
                    )
                )
            if not segs and p.next_shift_starts_at and p.next_shift_starts_at <= end:
                segs.append(
                    ShiftLaneSegment(
                        start=p.next_shift_starts_at, end=None, kind="assumed", label="Next shift"
                    )
                )
        lanes.append(
            ShiftLane(
                physician_id=p.physician_id,
                display_name=p.display_name,
                availability_class=classes.get(p.physician_id, AvailabilityClass.UNKNOWN),
                credentialed_hospital_ids=sorted(p.credentialed_hospital_ids),
                segments=segs,
            )
        )
    demand, meta = stochastic_demand(analysis, horizon_minutes, stochastic)
    return TimeMachineReport(
        as_of=as_of,
        data_version=state.data_version,
        horizon_minutes=horizon_minutes,
        step_minutes=step_minutes,
        frames=frames,
        lanes=lanes,
        demand=demand,
        stochastic=meta,
        freshness=freshness,
        hospitals=[
            {"hospital_id": h.id, "name": h.name, "timezone": h.timezone}
            for h in sorted(state.hospitals, key=lambda h: h.id)
        ],
        notes=[
            "Only the 'now' frame is observed state; all later frames are projections from "
            "schedules, credentials, current signals and known arrivals.",
            "Capacity = credentialed on-duty physicians (busy still counts). Uncertain = shift "
            "end unknown, agent offline, or an accepted rescue shift not yet active.",
            "Pool coverage: a physician counts at every hospital they are credentialed at "
            "(per-hospital requirement, brief). See Network → exclusive allocation for the "
            "stricter reading.",
        ],
    )
