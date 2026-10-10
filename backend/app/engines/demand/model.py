"""Demand-spike rule (pure).

Brief: "A demand spike (trailing 60-minute consults above the hospital's p90 baseline for
that hour) raises the requirement by one."

Exact method:
- Arrivals = distinct consults whose consult_received ``event_time`` falls in the
  half-open window (t - 60 min, t]. Consults come from the replayed state, so duplicate
  events can never count twice and only events visible at the simulation time are used.
- "That hour" = the hospital-local clock hour containing t (IANA zone, DST-aware), matched
  to ``baseline_hourly_volume.hour``.
- Spike when arrivals > p90 (strictly above). No baseline row => spike is unknown; nothing
  is substituted.
- For future t (forecasting) only arrivals already known at the simulation time are
  counted, so projected spikes are lower bounds that end when known arrivals age out.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engines.event_processing import normalize_label
from app.engines.timeline import is_weekend, local, local_hour_boundaries
from app.schemas.consultation import ConsultationState
from app.schemas.coverage import BaselineVolume
from app.schemas.demand import DemandEvaluation

WEEKDAY_LABELS = {"weekday", "weekdays", "mon_fri", "monday_friday"}
WEEKEND_LABELS = {"weekend", "weekends", "sat_sun", "saturday_sunday"}


@dataclass
class HospitalDemandModel:
    hospital_id: str
    timezone: str
    window: timedelta
    requirement_increase: int
    as_of: datetime
    arrivals: list[tuple[datetime, str]] = field(default_factory=list)
    """(received_at, consult_id), sorted. Only consults known at ``as_of``."""
    baselines: list[BaselineVolume] = field(default_factory=list)
    consults_without_received_time: int = 0

    @property
    def arrival_times(self) -> list[datetime]:
        return [a for a, _ in self.arrivals]

    def _baseline(self, moment_local: datetime) -> tuple[BaselineVolume | None, str, str | None]:
        rows = [b for b in self.baselines if b.hour_local == moment_local.hour]
        if not rows:
            return None, "missing", None
        types = {normalize_label(b.day_type) if b.day_type else None for b in rows}
        if len(types) == 1:
            row = rows[0]
            label = next(iter(types))
            weekend = is_weekend(moment_local)
            mismatch = (label in WEEKDAY_LABELS and weekend) or (
                label in WEEKEND_LABELS and not weekend
            )
            return row, "day_type_mismatch" if mismatch else "ok", row.day_type
        wanted = WEEKEND_LABELS if is_weekend(moment_local) else WEEKDAY_LABELS
        matching = [b for b in rows if b.day_type and normalize_label(b.day_type) in wanted]
        if len(matching) == 1:
            return matching[0], "ok", matching[0].day_type
        return None, "ambiguous_day_type", None

    def baseline_at(self, at: datetime) -> BaselineVolume | None:
        """The baseline row for the hospital-local hour containing ``at`` (None if unusable)."""
        return self._baseline(local(at, self.timezone))[0]

    def evaluate(self, at: datetime) -> DemandEvaluation:
        start = at - self.window
        in_window = [(a, cid) for a, cid in self.arrivals if start < a <= at]
        count = len(in_window)
        moment_local = local(at, self.timezone)
        row, status, day_type = self._baseline(moment_local)
        hour = moment_local.hour
        label = f"{hour:02d}:00–{(hour + 1) % 24:02d}:00 {moment_local.tzname()}"
        future = at > self.as_of
        if row is None:
            spike = None
            comparison = (
                f"{count} arrivals in ({start.isoformat()}, {at.isoformat()}]; no usable p90 "
                f"baseline for local hour {label} ({status}) — spike not evaluated"
            )
        else:
            spike = count > row.p90_consults
            comparison = (
                f"{count} arrivals in ({start.isoformat()}, {at.isoformat()}] "
                f"{'>' if spike else '<='} p90 {row.p90_consults:g} for local hour {label}"
            )
        if future:
            comparison += " (known arrivals only; future arrivals are not assumed)"
        return DemandEvaluation(
            hospital_id=self.hospital_id,
            at=at,
            window_start=start,
            window_end=at,
            arrivals=count,
            consult_ids=[cid for _, cid in in_window],
            local_hour=hour,
            local_hour_label=label,
            baseline_status=status,
            baseline_day_type=day_type,
            baseline_mean=row.mean_consults if row else None,
            baseline_p90=row.p90_consults if row else None,
            spike=spike,
            requirement_adjustment=(
                None if spike is None else (self.requirement_increase if spike else 0)
            ),
            excess_over_p90=(count - row.p90_consults) if row else None,
            known_arrivals_only=future,
            comparison=comparison,
        )

    def change_points(self, start: datetime, end: datetime) -> list[datetime]:
        """Instants in (start, end) where the spike evaluation can change: an arrival
        leaving the window, or the local hour (and so the baseline) changing."""
        exits = [a + self.window for a in self.arrival_times if start < a + self.window < end]
        return sorted(set(exits) | set(local_hour_boundaries(self.timezone, start, end)))

    def spike_end(self, horizon_end: datetime) -> datetime | None:
        """If spiking at as_of: first change point at which it stops (known arrivals only)."""
        if not self.evaluate(self.as_of).spike:
            return None
        for moment in self.change_points(self.as_of, horizon_end):
            if not self.evaluate(moment).spike:
                return moment
        return None


def build_demand_models(
    consults: Sequence[ConsultationState],
    hospitals: Iterable[tuple[str, str]],
    baselines: Sequence[BaselineVolume],
    as_of: datetime,
    *,
    window_minutes: int,
    requirement_increase: int,
) -> dict[str, HospitalDemandModel]:
    models: dict[str, HospitalDemandModel] = {}
    for hospital_id, tz in hospitals:
        models[hospital_id] = HospitalDemandModel(
            hospital_id=hospital_id,
            timezone=tz,
            window=timedelta(minutes=window_minutes),
            requirement_increase=requirement_increase,
            as_of=as_of,
            baselines=[b for b in baselines if b.hospital_id == hospital_id],
        )
    for consult in consults:
        model = models.get(consult.hospital_id or "")
        if model is None:
            continue
        if consult.received_at is None:
            model.consults_without_received_time += 1
        elif consult.received_at <= as_of:
            model.arrivals.append((consult.received_at, consult.consult_id))
    for model in models.values():
        model.arrivals.sort()
    return models


def arrivals_in_window(times: Sequence[datetime], at: datetime, window: timedelta) -> int:
    """Count of sorted ``times`` in (at - window, at]."""
    return bisect_right(times, at) - bisect_right(times, at - window)
