"""Scenario builder for Phase 4 optimizer tests (pure engines, no database)."""

from __future__ import annotations

from datetime import datetime, timedelta

from analysis_helpers import Scenario, utc

from app.engines.analysis import OperationalAnalysis
from app.engines.optimization import OptimizationConfig, run_dispatch, run_staffing
from app.schemas.physician import Physician, PhysicianSchedule, ShiftWindow

NOW = utc(2031, 6, 3, 15, 0)  # Tuesday 10:00 CDT


def m(minutes: float) -> datetime:
    return NOW + timedelta(minutes=minutes)


class OptScenario(Scenario):
    def doctor(
        self,
        pid: str,
        creds: list[str],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        role: str = "day",
    ) -> OptScenario:
        start, end = start or m(-240), end or m(240)
        self.physicians.append(
            Physician(
                id=pid,
                display_name=f"Dr {pid}",
                roster="on_shift",
                roster_role=role,
                credentialed_hospital_ids=creds,
                schedule=PhysicianSchedule(current_shift=ShiftWindow(start=start, end=end)),
            )
        )
        self.event("shift_started", start, physician_id=pid)
        return self

    def candidate(
        self,
        pid: str,
        creds: list[str],
        *,
        opt_in: bool | None = True,
        last_end: datetime | None = None,
        next_start: datetime | None = None,
        hours: float | None = 20.0,
        online: int | None = 0,
        role: str = "float",
        missing: tuple[str, ...] = (),
    ) -> OptScenario:
        """Off-shift roster physician. ``missing`` blanks fields (e.g. ("last_end",))."""
        self.physicians.append(
            Physician(
                id=pid,
                display_name=f"Dr {pid}",
                roster="off_shift",
                roster_role=role,
                credentialed_hospital_ids=creds,
                split_shift_opt_in=opt_in,
                schedule=PhysicianSchedule(
                    last_shift_ended_at=None
                    if "last_end" in missing
                    else (last_end or m(-12 * 60)),
                    next_shift_starts_at=None
                    if "next_start" in missing
                    else (next_start or m(3 * 24 * 60)),
                    hours_worked_trailing_7d=hours,
                    minutes_to_come_online=online,
                ),
            )
        )
        return self

    def consult(
        self,
        cid: str,
        hid: str,
        ctype: str = "Stroke",
        *,
        received: float = -6,
        triaged: float | None = -5,
    ) -> OptScenario:
        self.event(
            "consult_received", m(received), consult_id=cid, hospital_id=hid, consult_type=ctype
        )
        if triaged is not None:
            self.event("consult_triaged", m(triaged), consult_id=cid, hospital_id=hid)
        return self

    def history(self, pid: str, hid: str, n: int, *, last_call_end: float = -60) -> OptScenario:
        """n completed consults this shift; the last call ends at ``last_call_end`` minutes."""
        for i in range(n):
            end = last_call_end - (n - 1 - i) * 20
            cid = f"H-{pid}-{i}"
            self.consult(cid, hid, "General Neuro", received=end - 15, triaged=end - 14)
            self.event(
                "physician_assigned", m(end - 13), consult_id=cid, physician_id=pid, hospital_id=hid
            )
            self.event(
                "incoming_call_started",
                m(end - 12),
                consult_id=cid,
                physician_id=pid,
                hospital_id=hid,
            )
            self.event(
                "incoming_call_ended", m(end), consult_id=cid, physician_id=pid, hospital_id=hid
            )
            self.event(
                "note_started", m(end + 1), consult_id=cid, physician_id=pid, hospital_id=hid
            )
            self.event("note_signed", m(end + 2), consult_id=cid, physician_id=pid, hospital_id=hid)
        return self

    def open_note(self, pid: str, cid: str, hid: str, *, call_end: float = -30) -> OptScenario:
        self.consult(cid, hid, "General Neuro", received=call_end - 15, triaged=call_end - 14)
        self.event(
            "physician_assigned",
            m(call_end - 13),
            consult_id=cid,
            physician_id=pid,
            hospital_id=hid,
        )
        self.event(
            "incoming_call_started",
            m(call_end - 12),
            consult_id=cid,
            physician_id=pid,
            hospital_id=hid,
        )
        self.event(
            "incoming_call_ended", m(call_end), consult_id=cid, physician_id=pid, hospital_id=hid
        )
        return self


def analyze(s: OptScenario, at: datetime = NOW) -> OperationalAnalysis:
    return s.analyze(at)


def dispatch(s: OptScenario, cfg: OptimizationConfig | None = None, at: datetime = NOW):
    return run_dispatch(analyze(s, at), cfg or OptimizationConfig())


def staffing(s: OptScenario, cfg: OptimizationConfig | None = None, at: datetime = NOW):
    return run_staffing(analyze(s, at), cfg or OptimizationConfig())


def pairs(result) -> dict[str, str]:
    return {r.consult_id: r.physician_id for r in result.plan.recommendations}


def config(**sections) -> OptimizationConfig:
    """OptimizationConfig with partial section overrides, e.g. config(routing={...})."""
    base = OptimizationConfig().model_dump()
    for key, value in sections.items():
        base[key] = {**base[key], **value} if isinstance(value, dict) else value
    return OptimizationConfig.model_validate(base)
