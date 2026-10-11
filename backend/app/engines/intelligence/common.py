"""Shared, pure helpers over the Phase 3 coverage models.

A ``HospitalCoverageModel`` holds one contribution window per counted physician. Every
what-if in this package is a small, isolated change to those windows (drop a physician,
add a proposed shift, extend a shift) followed by the *same* exact piecewise evaluation
the dashboard uses, so before and after are always computed by one code path. Models are
dataclasses; ``dataclasses.replace`` gives an independent copy and the live analysis is
never mutated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.engines.analysis import OperationalAnalysis
from app.engines.coverage_prediction import (
    HospitalCoverageModel,
    Window,
    build_coverage_models,
)

Models = Mapping[str, HospitalCoverageModel]

STROKE_LABELS = ("stroke",)


def is_stroke(consult_type: str | None) -> bool:
    return bool(consult_type) and any(k in consult_type.lower() for k in STROKE_LABELS)


def planning_models(
    analysis: OperationalAnalysis, horizon_minutes: int
) -> dict[str, HospitalCoverageModel]:
    """Coverage models over ``horizon_minutes`` (reuses the cached dashboard models when the
    horizon matches)."""
    if horizon_minutes == analysis.coverage.horizon_minutes:
        return dict(analysis.coverage_models)
    return build_coverage_models(
        analysis.state,
        analysis.reference,
        analysis.demand_models,
        analysis.config.coverage,
        horizon_minutes,
    )


def drop_physicians(
    models: Models, physician_ids: Iterable[str]
) -> dict[str, HospitalCoverageModel]:
    gone = set(physician_ids)
    return {
        hid: replace(m, windows=[w for w in m.windows if w.physician_id not in gone])
        for hid, m in models.items()
    }


def end_windows_at(
    models: Models, physician_ids: Iterable[str], at: datetime
) -> dict[str, HospitalCoverageModel]:
    """The physicians stop counting at ``at`` (e.g. leave now) instead of their shift end."""
    ids = set(physician_ids)
    out: dict[str, HospitalCoverageModel] = {}
    for hid, m in models.items():
        windows: list[Window] = []
        for w in m.windows:
            if w.physician_id in ids:
                if w.start >= at:
                    continue
                w = replace(w, end=at if w.end is None or w.end > at else w.end)
            windows.append(w)
        out[hid] = replace(m, windows=windows)
    return out


def add_windows(
    models: Models, additions: Mapping[str, Iterable[Window]]
) -> dict[str, HospitalCoverageModel]:
    return {
        hid: replace(m, windows=[*m.windows, *additions.get(hid, ())]) if hid in additions else m
        for hid, m in models.items()
    }


@dataclass(frozen=True)
class Profile:
    """Exact summary of one hospital's coverage over the model horizon."""

    deficit_pm: float
    deficit_pm_confirmed_only: float
    shortfall_minutes: float
    fragile_minutes: float
    first_shortfall: datetime | None
    first_shortfall_end: datetime | None
    worst_deficit: int
    required_now: int | None
    counted_now: int
    min_spare: int | None
    requirement_defined: bool


def profile(model: HospitalCoverageModel) -> Profile:
    evals = model.evaluations()
    deficit = deficit_conf = short = fragile = 0.0
    first: datetime | None = None
    first_end: datetime | None = None
    worst = 0
    min_spare: int | None = None
    defined = False
    for a, b, e in evals:
        minutes = (b - a).total_seconds() / 60
        if e.required is None:
            continue
        defined = True
        d = e.deficit or 0
        spare = len(e.active) - e.required
        min_spare = spare if min_spare is None else min(min_spare, spare)
        deficit += d * minutes
        deficit_conf += (e.deficit_confirmed or 0) * minutes
        worst = max(worst, d)
        if d > 0:
            short += minutes
            if first is None:
                first = a
            if first_end is None or first_end == a:
                first_end = b
        elif e.required > 0 and spare == 0:
            fragile += minutes
    now = evals[0][2] if evals else None
    return Profile(
        deficit_pm=round(deficit, 4),
        deficit_pm_confirmed_only=round(deficit_conf, 4),
        shortfall_minutes=round(short, 4),
        fragile_minutes=round(fragile, 4),
        first_shortfall=first,
        first_shortfall_end=first_end,
        worst_deficit=worst,
        required_now=now.required if now else None,
        counted_now=len(now.active) if now else 0,
        min_spare=min_spare,
        requirement_defined=defined,
    )


def profiles(models: Models) -> dict[str, Profile]:
    return {hid: profile(m) for hid, m in models.items()}


def evaluation_at(model: HospitalCoverageModel, moment: datetime):
    """The constant piece (start, end, eval) containing ``moment`` (clamped to the horizon)."""
    evals = model.evaluations()
    if not evals:
        return None
    for piece in evals:
        if piece[0] <= moment < piece[1]:
            return piece
    return evals[-1] if moment >= evals[-1][1] else evals[0]


def deficit_between(model: HospitalCoverageModel, start: datetime, end: datetime) -> float:
    total = 0.0
    for a, b, e in model.evaluations():
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            total += (e.deficit or 0) * (hi - lo).total_seconds() / 60
    return round(total, 4)


def minutes(delta: timedelta) -> float:
    return round(delta.total_seconds() / 60, 2)


def single_point_physicians(models: Models) -> dict[str, list[str]]:
    """physician_id -> hospitals where dropping them alone adds deficit."""
    base = {hid: profile(m).deficit_pm for hid, m in models.items()}
    ids = sorted({w.physician_id for m in models.values() for w in m.windows})
    out: dict[str, list[str]] = {}
    for pid in ids:
        dropped = drop_physicians(models, [pid])
        hit = [hid for hid, m in dropped.items() if profile(m).deficit_pm > base[hid] + 1e-9]
        if hit:
            out[pid] = sorted(hit)
    return out
