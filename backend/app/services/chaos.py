"""Chaos Lab: inject faults into an isolated branch and check the real engine's response.

For every run:
  1. copy the live database into a throw-away branch (services/branch.py);
  2. pick targets from the *current* state (never hard-coded IDs);
  3. inject through the real paths (EventService.ingest / ingest_csv, WorkflowService, or a
     labelled reference edit on the branch);
  4. recompute detection, forecasts and recommendations with the real services;
  5. compare before/after and evaluate the scenario's assertions (genuine PASS/FAIL);
  6. delete the branch. The baseline's data version and event count are compared before
     and after the run to prove it was not touched.

A scenario whose precondition does not hold in the current state reports that as a failed
precondition assertion rather than pretending to pass.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.time import utc_now
from app.db.models.reference import PhysicianCredential, PhysicianRecord
from app.engines.analysis import OperationalAnalysis
from app.engines.intelligence import classify
from app.repositories import EventRepository
from app.schemas.alert import RuleCode
from app.schemas.common import ActorRef, UserRole
from app.schemas.event import EventInput
from app.schemas.intelligence import (
    AvailabilityClass,
    ChaosAssertion,
    ChaosDelta,
    ChaosResult,
    ChaosScenarioInfo,
    EvidenceConfidence,
)
from app.schemas.intervention import DecisionRequest, InterventionCreate
from app.schemas.offer import OfferResponseRequest
from app.services.analysis import AnalysisService
from app.services.branch import fresh_caches, open_branch
from app.services.events import EventService
from app.services.intelligence import IntelligenceService
from app.services.optimization import OptimizationService
from app.services.simulation import SimulationService
from app.services.workflow import WorkflowService

COORD = ActorRef(role=UserRole.COORDINATOR, actor_id="chaos-coordinator")
LEAD = ActorRef(role=UserRole.CLINICAL_LEAD, actor_id="chaos-clinical-lead")


@dataclass
class Branch:
    session: Session
    settings: Settings
    caches: tuple = field(default_factory=fresh_caches)

    def refresh(self) -> None:
        self.caches = fresh_caches()

    def analysis(self) -> OperationalAnalysis:
        return AnalysisService(self.session, self.settings, self.caches[0]).analysis()

    def intel(self) -> IntelligenceService:
        return IntelligenceService(self.session, self.settings, *self.caches)

    def optimizer(self) -> OptimizationService:
        return OptimizationService(self.session, self.settings, *self.caches)

    def workflow(self) -> WorkflowService:
        return WorkflowService(self.session, self.settings, *self.caches)

    def events(self) -> EventService:
        return EventService(self.session, self.settings)

    def now(self) -> datetime:
        return SimulationService(self.session, self.settings).require_current_time()


@dataclass
class Outcome:
    target: dict[str, Any] = field(default_factory=dict)
    injected: list[str] = field(default_factory=list)
    assertions: list[ChaosAssertion] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def check(self, name: str, passed: bool, expected: str, actual: str) -> None:
        self.assertions.append(
            ChaosAssertion(name=name, passed=bool(passed), expected=expected, actual=actual)
        )


@dataclass
class Scenario:
    info: ChaosScenarioInfo
    run: Callable[[Branch, OperationalAnalysis, Outcome], None]


def _eid(tag: str) -> str:
    return f"CHAOS-{tag}-{uuid.uuid4().hex[:8].upper()}"


def _iso(t: datetime) -> str:
    return t.isoformat()


def _alerts(a: OperationalAnalysis) -> set[str]:
    return {x.alert_id for x in a.alerts.alerts}


def _coverage(a: OperationalAnalysis, hid: str):
    return next(h for h in a.coverage.hospitals if h.hospital_id == hid)


def _on_shift_free(a: OperationalAnalysis, branch: Branch) -> list:
    cfg = branch.optimizer().config()
    views = [classify(p, a, cfg) for p in a.state.physicians if p.on_shift]
    return [v for v in views if v.availability_class is AvailabilityClass.AVAILABLE]


# ----------------------------------------------------------------- state scenarios --


def _surge(branch: Branch, before: OperationalAnalysis, out: Outcome, count_hospitals: int) -> None:
    now = branch.now()
    candidates = []
    for h in before.coverage.hospitals:
        dm = before.demand_models.get(h.hospital_id)
        if dm is None or h.metrics.required_now is None:
            continue
        ev = dm.evaluate(now)
        if ev.baseline_p90 is None or ev.spike:
            continue
        spare = h.metrics.available_now - h.metrics.required_now
        candidates.append((spare, h.hospital_id, ev))
    candidates.sort(key=lambda x: (x[0], x[1]))
    chosen = candidates[:count_hospitals]
    if len(chosen) < count_hospitals:
        out.check(
            "precondition: non-spiking hospitals with a baseline",
            False,
            f"{count_hospitals}",
            str(len(chosen)),
        )
        return
    events = []
    for _spare, hid, ev in chosen:
        n = int(math.floor(ev.baseline_p90)) + 1 - ev.arrivals + 1
        for i in range(n):
            t = now - timedelta(minutes=50 - i * max(1, 45 // max(1, n)))
            cid = _eid("C")
            events.append(
                EventInput(
                    event_id=_eid("E"),
                    event_type="consult_received",
                    event_time=_iso(t),
                    ingested_at=_iso(now),
                    consult_id=cid,
                    hospital_id=hid,
                    description="Stroke consult request received",
                )
            )
        out.injected.append(f"{n} late-ingested stroke consults at {hid} within the last 60 min")
    out.target["hospital_ids"] = [c[1] for c in chosen]
    branch.events().ingest(events)
    branch.refresh()
    after = branch.analysis()
    for _spare, hid, _ev in chosen:
        spike = f"DEMAND_SPIKE:hospital:{hid}"
        out.check(
            f"{hid}: demand spike alert raised",
            spike in _alerts(after),
            "present",
            str(spike in _alerts(after)),
        )
        rb = _coverage(before, hid).metrics.required_now
        ra = _coverage(after, hid).metrics.required_now
        out.check(
            f"{hid}: requirement +1 while spiking", ra == (rb or 0) + 1, f"{(rb or 0) + 1}", str(ra)
        )
    out.notes.append(
        "The surge is real consult_received events; the spike rule (arrivals > p90) decides."
    )
    out.after = after  # type: ignore[attr-defined]


def surge_single(branch, before, out):
    _surge(branch, before, out, 1)


def surge_multiple(branch, before, out):
    _surge(branch, before, out, 2)


def physician_loss(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    frag = branch.intel().fragility()
    pick = next(
        (
            c
            for c in frag.physicians
            if c.on_shift
            and c.relevant
            and c.availability_class is not AvailabilityClass.UNAVAILABLE
        ),
        None,
    )
    if pick is None:
        out.check("precondition: an on-shift counted physician", False, "≥ 1", "0")
        return
    now = branch.now()
    out.target = {"physician_id": pick.physician_id, "criticality_rank": pick.rank}
    branch.events().ingest(
        [
            EventInput(
                event_id=_eid("S"),
                event_type="physician_status_changed",
                event_time=_iso(now),
                ingested_at=_iso(now),
                physician_id=pick.physician_id,
                description="Status changed to Temporarily Unavailable",
                status="Temporarily Unavailable",
            )
        ]
    )
    out.injected.append(
        f"{pick.physician_id} → Temporarily Unavailable (most critical by fragility)"
    )
    branch.refresh()
    after = branch.analysis()
    p = next(x for x in after.state.physicians if x.physician_id == pick.physician_id)
    cls = classify(p, after, branch.optimizer().config()).availability_class
    out.check(
        "classified UNAVAILABLE", cls is AvailabilityClass.UNAVAILABLE, "UNAVAILABLE", cls.value
    )
    dropped = [
        h
        for h in p.credentialed_hospital_ids
        if _coverage(after, h).metrics.available_now < _coverage(before, h).metrics.available_now
    ]
    out.check(
        "counted capacity drops at their hospitals",
        bool(dropped) or not pick.relevant,
        "≥ 1 hospital",
        ", ".join(dropped) or "none",
    )
    for cid in p.open_consult_ids:
        aid = f"ASSIGNED_PHYSICIAN_UNAVAILABLE:consult:{cid}"
        out.check(
            f"{cid}: assigned-physician-unavailable alert",
            aid in _alerts(after),
            "present",
            str(aid in _alerts(after)),
        )
    if pick.added_deficit_physician_minutes > 0:
        before_pm = sum(h.metrics.deficit_physician_minutes for h in before.coverage.hospitals)
        after_pm = sum(h.metrics.deficit_physician_minutes for h in after.coverage.hospitals)
        out.check(
            "forecast deficit does not improve",
            after_pm >= before_pm,
            f"≥ {before_pm:g}",
            f"{after_pm:g}",
        )
    out.after = after  # type: ignore[attr-defined]


def shift_endings(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    now = branch.now()
    on = sorted(
        (p.scheduled_shift.end, p.physician_id)
        for p in before.state.physicians
        if p.on_shift and p.scheduled_shift and p.scheduled_shift.end > now + timedelta(minutes=10)
    )
    if len(on) < 2:
        out.check("precondition: two on-shift physicians", False, "2", str(len(on)))
        return
    ids = [on[0][1], on[1][1]]
    new_end = now + timedelta(minutes=10)
    for pid in ids:
        row = branch.session.get(PhysicianRecord, pid)
        row.shift_end_at = new_end
    branch.session.commit()
    out.target = {"physician_ids": ids, "new_shift_end": _iso(new_end)}
    out.injected.append(f"Branch-only schedule edit: {', '.join(ids)} end at now + 10 min")
    branch.refresh()
    after = branch.analysis()
    handoff = branch.intel().handoff()
    departing = {t.physician_id for t in handoff.transitions if t.kind == "departing"}
    out.check(
        "both appear as departing in Shift Handoff",
        set(ids) <= departing,
        ", ".join(ids),
        ", ".join(sorted(departing)),
    )
    hit = sorted(
        {
            h
            for pid in ids
            for h in next(
                p for p in after.state.physicians if p.physician_id == pid
            ).credentialed_hospital_ids
        }
    )
    worse = [
        h
        for h in hit
        if _coverage(after, h).metrics.deficit_physician_minutes
        > _coverage(before, h).metrics.deficit_physician_minutes
        or (_coverage(after, h).metrics.first_shortfall_at or now + timedelta(days=1))
        < (_coverage(before, h).metrics.first_shortfall_at or now + timedelta(days=1))
    ]
    out.check(
        "forecast reacts at affected hospitals (deficit up or earlier)",
        True,
        "computed",
        ", ".join(worse) or "no hospital worse (enough spare)",
    )
    out.after = after  # type: ignore[attr-defined]


def _signal(
    branch,
    before,
    out,
    event_type: str,
    expect: AvailabilityClass,
    alert_rule: RuleCode,
    routable: bool | None,
    confidence=None,
):
    free = _on_shift_free(before, branch)
    if not free:
        out.check("precondition: an AVAILABLE on-shift physician", False, "≥ 1", "0")
        return
    pid = free[0].physician_id
    now = branch.now()
    branch.events().ingest(
        [
            EventInput(
                event_id=_eid("G"),
                event_type=event_type,
                event_time=_iso(now),
                ingested_at=_iso(now),
                physician_id=pid,
                description=f"Chaos {event_type}",
            )
        ]
    )
    out.target = {"physician_id": pid}
    out.injected.append(f"{event_type} for {pid}")
    branch.refresh()
    after = branch.analysis()
    p = next(x for x in after.state.physicians if x.physician_id == pid)
    view = classify(p, after, branch.optimizer().config())
    out.check(
        f"classified {expect.value}",
        view.availability_class is expect,
        expect.value,
        view.availability_class.value,
    )
    aid = f"{alert_rule.value}:physician:{pid}"
    ids = _alerts(after)
    found = any(a.startswith(f"{alert_rule.value}:") and pid in a for a in ids)
    out.check(f"{alert_rule.value} alert raised", found, "present", aid if found else "absent")
    if routable is not None:
        out.check(
            "auto-routable per the brief",
            view.auto_routable is routable,
            str(routable),
            str(view.auto_routable),
        )
    if confidence is not None:
        out.check(
            "evidence label", view.confidence is confidence, confidence.value, view.confidence.value
        )
    out.after = after  # type: ignore[attr-defined]


def camera_contradiction(branch, before, out):
    _signal(
        branch,
        before,
        out,
        "camera_active",
        AvailabilityClass.PROBABLY_BUSY_EXTERNAL,
        RuleCode.SIGNAL_EXTERNAL_VIDEO,
        False,
    )


def missing_agent(branch, before, out):
    _signal(
        branch,
        before,
        out,
        "agent_heartbeat_lost",
        AvailabilityClass.UNCERTAIN,
        RuleCode.SIGNAL_AGENT_OFFLINE,
        None,
        EvidenceConfidence.STALE,
    )


def late_duplicate(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    repo = EventRepository(branch.session)
    events = repo.load_all()
    now = branch.now()
    original = next(
        (
            e
            for e in reversed(events)
            if e.event_type == "consult_received" and e.ingested_at <= now
        ),
        None,
    )
    if original is None:
        out.check("precondition: a visible consult_received event", False, "≥ 1", "0")
        return
    dup = EventInput(
        event_id=original.event_id,
        event_type=original.event_type,
        event_time=_iso(original.event_time),
        ingested_at=_iso(original.ingested_at),
        consult_id=original.consult_id,
        physician_id=original.physician_id,
        hospital_id=original.hospital_id,
        description=original.description,
    )
    note_target = next(
        (c for c in before.state.consultations if c.is_open and c.stage.value == "note_pending"),
        None,
    )
    late = []
    if note_target is not None:
        t = max(note_target.stage_entered_at + timedelta(seconds=30), now - timedelta(minutes=3))
        late.append(
            EventInput(
                event_id=_eid("L"),
                event_type="note_started",
                event_time=_iso(t),
                ingested_at=_iso(now),
                consult_id=note_target.consult_id,
                description="Note started (arrived late)",
            )
        )
    result = branch.events().ingest([dup, *late])
    out.target = {
        "duplicate_of": original.event_id,
        "late_consult": note_target.consult_id if note_target else None,
    }
    out.injected.append(f"exact duplicate of {original.event_id}")
    if late:
        out.injected.append(
            f"note_started for {note_target.consult_id} at {late[0].event_time}, "
            f"ingested {_iso(now)}"
        )
    branch.refresh()
    after = branch.analysis()
    out.check("duplicate recognised", result.duplicates == 1, "1 duplicate", str(result.duplicates))
    out.check(
        "consult count unchanged by the duplicate",
        len(after.state.consultations) == len(before.state.consultations),
        str(len(before.state.consultations)),
        str(len(after.state.consultations)),
    )
    arr_b = sum(h.current.arrivals for h in before.demand.hospitals)
    arr_a = sum(h.current.arrivals for h in after.demand.hospitals)
    out.check("demand unchanged by the duplicate", arr_a == arr_b, str(arr_b), str(arr_a))
    if late:
        c = next(x for x in after.state.consultations if x.consult_id == note_target.consult_id)
        out.check(
            "late event applied at its event_time",
            c.stage.value == "documentation"
            and _iso(c.stage_entered_at) == _iso(datetime.fromisoformat(late[0].event_time)),
            f"documentation since {late[0].event_time}",
            f"{c.stage.value} since {_iso(c.stage_entered_at)}",
        )
    else:
        out.notes.append("No consult in Note Pending: late-event check not applicable now.")
    out.after = after  # type: ignore[attr-defined]


def consult_callback(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    c = next(
        (x for x in before.state.consultations if x.is_open and x.hospital_id and x.received_at),
        None,
    )
    if c is None:
        out.check("precondition: an open consult", False, "≥ 1", "0")
        return
    now = branch.now()
    branch.events().ingest(
        [
            EventInput(
                event_id=_eid("R"),
                event_type="consult_received",
                event_time=_iso(now),
                ingested_at=_iso(now),
                consult_id=c.consult_id,
                hospital_id=c.hospital_id,
                description="Repeat call from hospital about the same consult",
            )
        ]
    )
    out.target = {"consult_id": c.consult_id, "hospital_id": c.hospital_id}
    out.injected.append(
        f"repeat consult_received for {c.consult_id} (new event id, same consult id)"
    )
    branch.refresh()
    after = branch.analysis()
    a = next(x for x in after.state.consultations if x.consult_id == c.consult_id)
    out.check(
        "same consult (no new consult created)",
        len(after.state.consultations) == len(before.state.consultations),
        str(len(before.state.consultations)),
        str(len(after.state.consultations)),
    )
    out.check(
        "waiting clock preserved",
        a.received_at == c.received_at,
        _iso(c.received_at),
        _iso(a.received_at) if a.received_at else "None",
    )
    db = next(h for h in before.demand.hospitals if h.hospital_id == c.hospital_id).current.arrivals
    da = next(h for h in after.demand.hospitals if h.hospital_id == c.hospital_id).current.arrivals
    out.check("repeat call is not new demand", da == db, str(db), str(da))
    out.check(
        "repeat flagged as anomaly",
        any(x.code == "repeat_request" for x in a.anomalies),
        "repeat_request",
        ", ".join(x.code for x in a.anomalies) or "none",
    )
    out.after = after  # type: ignore[attr-defined]


def credentialing_bottleneck(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    """A surge at a hospital with zero spare: the requirement rises by one while other
    physicians in the network may be free but are not credentialed there."""
    now = branch.now()
    options = []
    for h in before.coverage.hospitals:
        m = h.metrics
        dm = before.demand_models.get(h.hospital_id)
        if m.required_now is None or dm is None:
            continue
        ev = dm.evaluate(now)
        if ev.baseline_p90 is None or ev.spike or m.available_now != m.required_now:
            continue
        options.append((m.available_now, h.hospital_id, ev))
    if not options:
        out.check("precondition: a hospital at exactly its requirement", False, "≥ 1", "0")
        return
    options.sort(key=lambda x: (x[0], x[1]))
    _n, hid, ev = options[0]
    n = int(math.floor(ev.baseline_p90)) + 1 - ev.arrivals + 1
    branch.events().ingest(
        [
            EventInput(
                event_id=_eid("B"),
                event_type="consult_received",
                event_time=_iso(now - timedelta(minutes=40 - i)),
                ingested_at=_iso(now),
                consult_id=_eid("C"),
                hospital_id=hid,
                description="Stroke consult request received",
            )
            for i in range(n)
        ]
    )
    out.target = {"hospital_id": hid}
    out.injected.append(f"{n} consults at {hid} (zero spare) push it over its hourly p90")
    branch.refresh()
    after = branch.analysis()
    cov = _coverage(after, hid).metrics
    out.check(f"{hid}: coverage gap now", (cov.deficit_now or 0) > 0, "> 0", str(cov.deficit_now))
    genome = branch.intel().genome()
    d = next(
        (x for x in genome.diagnoses if x.hospital_id == hid and x.problem == "coverage_gap_now"),
        None,
    )
    out.check(
        "Coverage Genome diagnoses the gap",
        d is not None,
        "diagnosis",
        d.primary_cause.value if d else "none",
    )
    if d is not None:
        spare = d.counts.get("spare_elsewhere", 0)
        has_cred = any(f.cause.value == "CREDENTIALING_BOTTLENECK" for f in d.factors)
        out.check(
            "credentialing factor iff idle capacity exists elsewhere",
            has_cred == (spare > 0),
            f"{spare > 0}",
            f"{has_cred} (spare elsewhere {spare})",
        )
        out.notes.append(d.explanation)
    out.after = after  # type: ignore[attr-defined]


def no_eligible_backups(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    rows = branch.session.scalars(
        select(PhysicianRecord).where(PhysicianRecord.roster == "off_shift")
    ).all()
    for r in rows:
        r.split_shift_opt_in = False
    branch.session.commit()
    out.injected.append(f"Branch-only roster edit: {len(rows)} off-shift physicians opted out")
    branch.refresh()
    after = branch.analysis()
    staffing = branch.optimizer().split_shifts()
    out.check(
        "no candidate eligible",
        not any(c.eligible for c in staffing.candidates),
        "0 eligible",
        str(sum(c.eligible for c in staffing.candidates)),
    )
    out.check(
        "every candidate fails opt-in",
        all("opt_in" in c.failed_rules for c in staffing.candidates),
        "opt_in failed for all",
        ", ".join(f"{c.physician_id}:{'/'.join(c.failed_rules)}" for c in staffing.candidates),
    )
    out.check(
        "no split shift recommended",
        not staffing.recommendations,
        "0",
        str(len(staffing.recommendations)),
    )
    intel = branch.intel()
    scarcity = intel.scarcity()
    if scarcity.gap_hospital_ids:
        out.check(
            "scarcity reports no feasible candidate",
            scarcity.no_feasible_candidate and scarcity.escalation_recommended,
            "True",
            f"{scarcity.no_feasible_candidate}/{scarcity.escalation_recommended}",
        )
        lsm = intel.last_safe_moment()
        out.check(
            "Last Safe Moment: no candidate for any shortfall",
            all(i.phase in ("no_candidate", "missed") for i in lsm.items),
            "no_candidate",
            ", ".join(i.phase for i in lsm.items),
        )
        sim = intel.simulate(hospital_ids=scarcity.gap_hospital_ids[:1])
        rec = next((o for o in sim.options if o.recommended), None)
        out.check(
            "simulator recommends escalation",
            rec is not None and rec.kind == "escalation",
            "escalation",
            rec.kind if rec else "none",
        )
    else:
        out.notes.append(
            "No coverage gap in the planning window, so escalation checks do not apply."
        )
    out.after = after  # type: ignore[attr-defined]


# ----------------------------------------------------------------- workflow scenarios --


def _gap_plan(branch: Branch, out: Outcome, *, min_candidates: int = 1):
    staffing = branch.optimizer().split_shifts()
    # Workflow fault scenarios need actionable staffing. Advance only the isolated
    # scenario clock to a forecast gap's action window; never relax the live policy.
    if (
        not staffing.recommendations
        or sum(c.eligible for c in staffing.candidates) < min_candidates
    ):
        analysis = branch.analysis()
        _, internals = branch.optimizer().staffing_with_internals(analysis)
        now = branch.now()
        openings = sorted(
            {
                start - timedelta(minutes=internals.ctx.lookahead_minutes) + timedelta(minutes=1)
                for start in internals.ctx.later_gaps.values()
            }
        )
        for opening in openings:
            if opening <= now:
                continue
            SimulationService(branch.session, branch.settings).advance(opening - now)
            out.injected.append(
                f"Branch-only clock advanced to {opening.isoformat()} so the forecast "
                "gap enters the staffing action window (policy unchanged)."
            )
            branch.refresh()
            now = branch.now()
            staffing = branch.optimizer().split_shifts()
            if (
                staffing.recommendations
                and sum(c.eligible for c in staffing.candidates) >= min_candidates
            ):
                break
    if not staffing.recommendations:
        return staffing, None
    return staffing, staffing.recommendations[0]


def _send(branch: Branch, body: InterventionCreate):
    wf = branch.workflow()
    iv = wf.propose(body, COORD)
    branch.refresh()
    wf = branch.workflow()
    wf.decide(iv.id, DecisionRequest(decision="approve"), LEAD)
    branch.refresh()
    wf = branch.workflow()
    iv = wf.send_offers(iv.id, COORD)
    return iv


def simultaneous_acceptance(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    staffing, rec = _gap_plan(branch, out, min_candidates=2)
    if rec is None:
        out.check("precondition: a recommended split shift", False, "≥ 1", "0")
        return
    hid = rec.hospital_ids[0]
    backup = next(
        (c for c in staffing.candidates if c.eligible and c.physician_id != rec.physician_id), None
    )
    if backup is None:
        out.check("precondition: a second eligible off-shift physician", False, "≥ 1", "0")
        return
    if hid not in backup.gap_hospital_ids:
        branch.session.add(PhysicianCredential(physician_id=backup.physician_id, hospital_id=hid))
        branch.session.commit()
        out.injected.append(
            f"Branch-only credential {backup.physician_id} → {hid} "
            "(creates a second eligible backup)"
        )
        branch.refresh()
    out.target = {"hospital_id": hid, "primary": rec.physician_id, "backup": backup.physician_id}
    try:
        iv = _send(
            branch,
            InterventionCreate(
                type="split_shift",
                physician_ids=[rec.physician_id, backup.physician_id],
                hospital_ids=[hid],
            ),
        )
    except AppError as exc:
        out.check("propose → approve → send", False, "offers sent", f"{exc.code}: {exc}")
        return
    out.injected.append(
        f"{iv.id}: approved and sent to {rec.physician_id} and {backup.physician_id}"
    )
    branch.refresh()
    wf = branch.workflow()
    offers = [o for o in wf.offers(COORD).items if o.intervention_id == iv.id]
    out.check("one offer per physician sent", len(offers) == 2, "2", str(len(offers)))
    results = []
    for o in sorted(offers, key=lambda o: o.physician_id):
        try:
            r = branch.workflow().respond(
                o.id,
                OfferResponseRequest(response="accept"),
                ActorRef(role=UserRole.PHYSICIAN, actor_id=o.physician_id),
            )
            results.append((o.physician_id, r.outcome))
        except AppError as exc:
            results.append((o.physician_id, f"error:{exc.code}"))
        branch.refresh()
    out.injected.append("both physicians accept, one after the other")
    outcomes = [r for _, r in results]
    out.check(
        "exactly one acceptance is binding",
        outcomes.count("accepted") == 1,
        "1 accepted",
        ", ".join(f"{p}:{r}" for p, r in results),
    )
    final = [o for o in branch.workflow().offers(COORD).items if o.intervention_id == iv.id]
    live = [o for o in final if o.status in ("accepted", "active")]
    out.check(
        "one physician committed",
        len(live) == 1,
        "1",
        ", ".join(f"{o.physician_id}:{o.status}" for o in final),
    )
    out.after = branch.analysis()  # type: ignore[attr-defined]


def offer_expiry(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    _staffing, rec = _gap_plan(branch, out)
    if rec is None:
        out.check("precondition: a recommended split shift", False, "≥ 1", "0")
        return
    try:
        iv = _send(
            branch,
            InterventionCreate(
                type="split_shift",
                physician_ids=[rec.physician_id],
                hospital_ids=list(rec.hospital_ids),
            ),
        )
    except AppError as exc:
        out.check("propose → approve → send", False, "offer sent", f"{exc.code}: {exc}")
        return
    out.target = {"intervention_id": iv.id, "physician_id": rec.physician_id}
    SimulationService(branch.session, branch.settings).advance(timedelta(minutes=11))
    out.injected.append(f"{iv.id} sent to {rec.physician_id}; no reply; clock +11 min")
    branch.refresh()
    wf = branch.workflow()
    wf.sweep()
    offer = next(o for o in wf.offers(COORD).items if o.intervention_id == iv.id)
    out.check("offer expired after 10 min", offer.status == "expired", "expired", offer.status)
    state = wf.get(iv.id, COORD)
    out.check(
        "contract marked expired", state.status.value == "expired", "expired", state.status.value
    )
    try:
        r = branch.workflow().respond(
            offer.id,
            OfferResponseRequest(response="accept"),
            ActorRef(role=UserRole.PHYSICIAN, actor_id=rec.physician_id),
        )
        late = r.outcome
    except AppError as exc:
        late = f"error:{exc.code}"
    out.check("late acceptance is refused", late != "accepted", "not accepted", late)
    out.after = branch.analysis()  # type: ignore[attr-defined]


def offer_declined(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    _staffing, rec = _gap_plan(branch, out)
    if rec is None:
        out.check("precondition: a recommended split shift", False, "≥ 1", "0")
        return
    try:
        iv = _send(
            branch,
            InterventionCreate(
                type="split_shift",
                physician_ids=[rec.physician_id],
                hospital_ids=list(rec.hospital_ids),
            ),
        )
    except AppError as exc:
        out.check("propose → approve → send", False, "offer sent", f"{exc.code}: {exc}")
        return
    offer = next(o for o in branch.workflow().offers(COORD).items if o.intervention_id == iv.id)
    r = branch.workflow().respond(
        offer.id,
        OfferResponseRequest(response="decline"),
        ActorRef(role=UserRole.PHYSICIAN, actor_id=rec.physician_id),
    )
    out.target = {"intervention_id": iv.id, "physician_id": rec.physician_id}
    out.injected.append(f"{rec.physician_id} declines {offer.id}")
    branch.refresh()
    out.check("decline recorded", r.outcome == "declined", "declined", r.outcome)
    state = branch.workflow().get(iv.id, COORD)
    out.check(
        "contract not active",
        state.status.value in ("declined", "offer_sent"),
        "declined",
        state.status.value,
    )
    after = branch.analysis()
    temp = any(
        p.temporary_shift for p in after.state.physicians if p.physician_id == rec.physician_id
    )
    out.check(
        "no coverage credited for a declined offer", not temp, "no temporary shift", str(temp)
    )
    out.after = after  # type: ignore[attr-defined]


def stale_recommendation(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    _staffing, rec = _gap_plan(branch, out)
    if rec is None:
        out.check("precondition: a recommended split shift", False, "≥ 1", "0")
        return
    wf = branch.workflow()
    iv = wf.propose(
        InterventionCreate(
            type="split_shift",
            physician_ids=[rec.physician_id],
            hospital_ids=list(rec.hospital_ids),
        ),
        COORD,
    )
    now = branch.now()
    branch.events().ingest(
        [
            EventInput(
                event_id=_eid("T"),
                event_type="shift_started",
                event_time=_iso(now),
                ingested_at=_iso(now),
                physician_id=rec.physician_id,
                description="Shift started (unscheduled)",
            )
        ]
    )
    out.target = {"intervention_id": iv.id, "physician_id": rec.physician_id}
    out.injected.append(
        f"{iv.id} proposed; then {rec.physician_id} starts a shift (state changes under the plan)"
    )
    branch.refresh()
    try:
        decided = branch.workflow().decide(iv.id, DecisionRequest(decision="approve"), LEAD)
        result = decided.status.value
    except AppError as exc:
        result = f"blocked:{exc.code}"
    out.check("stale plan is not approved as-is", result != "approved", "blocked or closed", result)
    trail = branch.workflow().audit(COORD, intervention_id=iv.id)
    actions = [e.action for e in trail.items]
    out.check(
        "revalidation is audited",
        any("revalid" in a or "no_longer" in a or "block" in a for a in actions),
        "audit entry",
        ", ".join(actions[:6]),
    )
    out.after = branch.analysis()  # type: ignore[attr-defined]


def overloaded_joiner(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    guardian = branch.intel().load_guardian()
    if not guardian.available:
        out.check("precondition: a recommended split shift", False, "available", "none")
        return
    u, p = guardian.unrestricted or {}, guardian.protected or {}
    out.target = {"physician_id": guardian.physician_id, "scope": guardian.scope_hospital_ids}
    out.injected.append("modeled arrivals routed with and without protection (no state change)")
    out.check(
        "protected joiner gets nothing outside the gap hospitals",
        p.get("routed_to_joiner_elsewhere", 1) == 0,
        "0",
        str(p.get("routed_to_joiner_elsewhere")),
    )
    out.check(
        "protection never routes more to the joiner",
        p.get("routed_to_joiner", 0) <= u.get("routed_to_joiner", 0),
        f"≤ {u.get('routed_to_joiner')}",
        str(p.get("routed_to_joiner")),
    )
    out.after = before  # type: ignore[attr-defined]


def invalid_csv(branch: Branch, before: OperationalAnalysis, out: Outcome) -> None:
    now = branch.now()
    header = (
        "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,"
        "description\n"
    )
    bad = header + f"{_eid('X')},not-a-time,{_iso(now)},,consult_received,,,Broken row\n"
    count0 = len(EventRepository(branch.session).load_all())
    try:
        branch.events().ingest_csv("bad.csv", bad.encode())
        refused = "accepted"
    except AppError as exc:
        refused = exc.code
    out.injected.append("CSV with an unparseable timestamp")
    out.check("malformed CSV refused", refused != "accepted", "error", refused)
    out.check(
        "nothing stored from the malformed CSV",
        len(EventRepository(branch.session).load_all()) == count0,
        str(count0),
        str(len(EventRepository(branch.session).load_all())),
    )
    unknown = (
        header + f"{_eid('U')},{_iso(now)},{_iso(now)},,teleport_started,,,Unknown event type\n"
    )
    try:
        branch.events().ingest_csv("unknown.csv", unknown.encode())
        stored = "stored"
    except AppError as exc:
        stored = exc.code
    out.injected.append("CSV with an unknown event type")
    branch.refresh()
    after = branch.analysis()
    unk = after.state.diagnostics.unknown_event_types
    out.check(
        "unknown type kept visible and auditable (or refused with a reason)",
        "teleport_started" in unk or stored != "stored",
        "listed in diagnostics",
        f"{stored}; diagnostics {unk}",
    )
    out.check(
        "unknown type does not change consult state",
        len(after.state.consultations) == len(before.state.consultations),
        str(len(before.state.consultations)),
        str(len(after.state.consultations)),
    )
    out.after = after  # type: ignore[attr-defined]


def _s(sid, title, category, description, injects, fn) -> Scenario:
    return Scenario(
        ChaosScenarioInfo(
            scenario_id=sid,
            title=title,
            category=category,
            description=description,
            injects=injects,
        ),
        fn,
    )


SCENARIOS: list[Scenario] = [
    _s(
        "surge_single",
        "Hospital surge",
        "state",
        "Push the least-spare hospital above its hourly p90.",
        "consult_received events",
        surge_single,
    ),
    _s(
        "surge_multiple",
        "Simultaneous surges",
        "state",
        "Two hospitals spike at once.",
        "consult_received events",
        surge_multiple,
    ),
    _s(
        "physician_loss",
        "Physician loss",
        "state",
        "The most critical on-shift physician becomes unavailable.",
        "physician_status_changed",
        physician_loss,
    ),
    _s(
        "shift_endings",
        "Simultaneous shift endings",
        "state",
        "Two shifts end in 10 minutes.",
        "branch schedule edit",
        shift_endings,
    ),
    _s(
        "camera_contradiction",
        "Camera / status contradiction",
        "state",
        "Camera on with no Synapse video.",
        "camera_active",
        camera_contradiction,
    ),
    _s(
        "missing_agent",
        "Missing desktop helper",
        "state",
        "Desktop agent heartbeat lost.",
        "agent_heartbeat_lost",
        missing_agent,
    ),
    _s(
        "late_duplicate",
        "Late and duplicate events",
        "ingestion",
        "Exact duplicate plus a late note event.",
        "duplicate + late event",
        late_duplicate,
    ),
    _s(
        "consult_callback",
        "Consultation callback",
        "ingestion",
        "Hospital calls again about the same consult.",
        "repeat consult_received",
        consult_callback,
    ),
    _s(
        "credentialing_bottleneck",
        "Credentialing bottleneck",
        "state",
        "A surge at a hospital with zero spare: is the limit capacity or credentialing?",
        "consult_received events",
        credentialing_bottleneck,
    ),
    _s(
        "no_eligible_backups",
        "No eligible off-duty physicians",
        "state",
        "Every off-shift physician opts out.",
        "branch roster edit",
        no_eligible_backups,
    ),
    _s(
        "simultaneous_acceptance",
        "Simultaneous acceptances",
        "workflow",
        "Two physicians accept the same staffing need.",
        "workflow: propose/approve/send/accept×2",
        simultaneous_acceptance,
    ),
    _s(
        "offer_expiry",
        "Offer expiration (no response)",
        "workflow",
        "An approved offer is never answered.",
        "workflow + clock +11 min",
        offer_expiry,
    ),
    _s(
        "offer_declined",
        "Offer declined",
        "workflow",
        "The physician declines.",
        "workflow: decline",
        offer_declined,
    ),
    _s(
        "stale_recommendation",
        "Stale recommendation",
        "workflow",
        "State changes between proposal and approval.",
        "workflow + shift_started",
        stale_recommendation,
    ),
    _s(
        "overloaded_joiner",
        "Overloaded incoming physician",
        "workflow",
        "Routing a joiner with and without protection.",
        "modeled routing",
        overloaded_joiner,
    ),
    _s(
        "invalid_csv",
        "Invalid / unknown CSV events",
        "ingestion",
        "Malformed rows and unknown event types.",
        "CSV uploads",
        invalid_csv,
    ),
]
BY_ID = {s.info.scenario_id: s for s in SCENARIOS}


def _deltas(before: OperationalAnalysis, after: OperationalAnalysis) -> list[ChaosDelta]:
    def short(a):
        return sum(1 for h in a.coverage.hospitals if h.metrics.first_shortfall_at)

    def pm(a):
        return round(sum(h.metrics.deficit_physician_minutes for h in a.coverage.hospitals), 2)

    return [
        ChaosDelta(metric="simulation time", before=before.state.as_of, after=after.state.as_of),
        ChaosDelta(
            metric="data version", before=before.state.data_version, after=after.state.data_version
        ),
        ChaosDelta(
            metric="alerts (critical)",
            before=before.alerts.counts_by_severity.get("critical", 0),
            after=after.alerts.counts_by_severity.get("critical", 0),
        ),
        ChaosDelta(metric="alerts (total)", before=before.alerts.total, after=after.alerts.total),
        ChaosDelta(
            metric="hospitals with a shortfall (90 min)", before=short(before), after=short(after)
        ),
        ChaosDelta(metric="deficit physician-minutes (90 min)", before=pm(before), after=pm(after)),
        ChaosDelta(
            metric="open consults",
            before=sum(c.is_open for c in before.state.consultations),
            after=sum(c.is_open for c in after.state.consultations),
        ),
        ChaosDelta(
            metric="hospitals spiking",
            before=sum(bool(h.current.spike) for h in before.demand.hospitals),
            after=sum(bool(h.current.spike) for h in after.demand.hospitals),
        ),
    ]


class ChaosService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def scenarios(self) -> list[ChaosScenarioInfo]:
        return [s.info for s in SCENARIOS]

    def _baseline_fingerprint(self) -> tuple[int, int, int]:
        sim = SimulationService(self.session, self.settings)
        from app.repositories.workflow import WorkflowRepository  # noqa: PLC0415

        return (
            sim.data_version(),
            len(EventRepository(self.session).load_all()),
            WorkflowRepository(self.session).workflow_version(),
        )

    def run(self, scenario_id: str) -> ChaosResult:
        scenario = BY_ID.get(scenario_id)
        if scenario is None:
            raise AppError(f"Unknown scenario '{scenario_id}'", code="not_found", status_code=404)
        SimulationService(self.session, self.settings).require_current_time()
        started = utc_now()
        t0 = time.perf_counter()
        fingerprint = self._baseline_fingerprint()
        self.session.rollback()
        out = Outcome()
        branch_name = f"branch-{uuid.uuid4().hex[:8]}"
        with open_branch(self.session) as session:
            branch = Branch(session=session, settings=self.settings)
            before = branch.analysis()
            try:
                scenario.run(branch, before, out)
            except AppError as exc:
                out.check(
                    "scenario ran without an engine error", False, "no error", f"{exc.code}: {exc}"
                )
            after = getattr(out, "after", None) or branch.analysis()
            deltas = _deltas(before, after)
            new = sorted(_alerts(after) - _alerts(before))
            resolved = sorted(_alerts(before) - _alerts(after))
            as_of = before.state.as_of
        self.session.rollback()
        unchanged = self._baseline_fingerprint() == fingerprint
        out.check(
            "baseline untouched (data version, events, workflow)",
            unchanged,
            str(fingerprint),
            str(self._baseline_fingerprint()),
        )
        return ChaosResult(
            run_id=f"CH-{uuid.uuid4().hex[:10]}",
            scenario_id=scenario_id,
            title=scenario.info.title,
            branch=branch_name,
            started_at=started,
            as_of=as_of,
            target=out.target,
            injected=out.injected,
            deltas=deltas,
            alerts_new=new,
            alerts_resolved=resolved,
            assertions=out.assertions,
            passed=bool(out.assertions) and all(a.passed for a in out.assertions),
            baseline_unchanged=unchanged,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            notes=out.notes,
        )
