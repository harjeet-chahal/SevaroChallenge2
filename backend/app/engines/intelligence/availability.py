"""NEUROGRID availability classes on top of the Phase 2 precedence decision (pure).

The Phase 2 engine decides availability with an ordered rule list (R1-R10, see
engines/physician_state/availability.py). This module does not re-decide anything: it maps
each decision onto the finer NEUROGRID classes and separates three questions the
single routing flag would blur:

  auto_routable          the brief's routing rules 1-2 (on shift, not busy, not ringing,
                         no hang-up < 2 min) - computed by the Phase 4 routing view;
  coordinator_reachable  a person could reasonably contact them now;
  needs_confirmation     the evidence is stale or contradictory.

Brief vs. NEUROGRID spec. The brief says "Agent offline: routing assumes the physician is
available, but this is unverified. Surface the risk." The supplied rule wins: such a
physician stays ``auto_routable`` (as Synapse would route), is classed ``UNCERTAIN`` with
``STALE`` evidence and ``needs_confirmation``. Holding routing until confirmation is a
*proposed* policy only (see docs/RULES.md).
"""

from __future__ import annotations

from collections import Counter

from app.engines.analysis import OperationalAnalysis
from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.routing.problem import physician_view
from app.schemas.consultation import ConsultStage
from app.schemas.intelligence import (
    AvailabilityClass as C,
)
from app.schemas.intelligence import (
    AvailabilityReport,
    PhysicianAvailabilityView,
)
from app.schemas.intelligence import (
    EvidenceConfidence as E,
)
from app.schemas.physician import PhysicianState

NOTE_STAGES = {ConsultStage.NOTE_PENDING, ConsultStage.DOCUMENTATION}

RULE_CLASS: dict[str, tuple[C, E, str]] = {
    "R1_SYNAPSE_CALL": (C.BUSY_CALL, E.CONFIRMED, "Active Synapse call (system signal)."),
    "R2_SYNAPSE_VIDEO": (C.BUSY_VIDEO, E.CONFIRMED, "Active Synapse video (system signal)."),
    "R3_OFF_SHIFT": (C.OFF_SHIFT, E.CONFIRMED, "Not on shift (roster / shift events)."),
    "R4_TEMPORARILY_UNAVAILABLE": (
        C.UNAVAILABLE,
        E.CONFIRMED,
        "Self-reported Temporarily Unavailable.",
    ),
    "R5_CAMERA_NO_SYNAPSE": (
        C.PROBABLY_BUSY_EXTERNAL,
        E.LIKELY,
        "Camera active with no Synapse video and not In Meeting: probably an external "
        "video platform (brief: treat as busy and flag).",
    ),
    "R6_CAMERA_IN_MEETING": (
        C.INTERRUPTIBLE_MEETING,
        E.LIKELY,
        "Camera active while In Meeting: internal meeting, interruptible (brief).",
    ),
    "R7_IN_MEETING": (
        C.INTERRUPTIBLE_MEETING,
        E.LIKELY,
        "Self-reported In Meeting, camera off: interruptible.",
    ),
    "R8_AGENT_OFFLINE": (
        C.UNCERTAIN,
        E.STALE,
        "Desktop agent offline: camera state unknown; routing assumes available but this "
        "is unverified (brief).",
    ),
    "R9_DOCUMENTATION": (
        C.AVAILABLE,
        E.CONFIRMED,
        "Writing a note: documentation is not a busy signal in the routing rules.",
    ),
    "R10_DEFAULT": (C.AVAILABLE, E.CONFIRMED, "No busy, meeting or unavailable signal."),
}

WEAKENING_FLAGS = {
    "agent_online_inferred": (E.LIKELY, "agent online only inferred from a later agent event"),
    "shift_assumed_from_roster": (E.LIKELY, "on shift only by roster (no shift_started event)"),
    "not_in_roster": (E.UNCERTAIN, "not in any roster file"),
}
CONTRADICTION_FLAGS = {"status_contradiction", "external_video_suspected", "phone_ringing"}

RULES = [
    "Classes map the Phase 2 precedence rule (R1-R10) that decided availability; the rule "
    "and every input signal are kept as evidence.",
    "auto_routable = the brief's routing rules 1-2 (on shift, not busy, not Temporarily "
    "Unavailable, phone not ringing for another call, last call ended >= 2 min ago). "
    "Credentialing is checked per hospital.",
    "UNCERTAIN (agent offline) stays routable because the brief says routing assumes "
    "available; it is surfaced with STALE evidence and needs confirmation.",
    "PROBABLY_BUSY_EXTERNAL is never routable (brief: treat as busy).",
    "INTERRUPTIBLE_MEETING is routable (brief: internal meetings are interruptible) and is "
    "shown separately from ordinary availability.",
    "Confidence labels are evidence categories, not calibrated probabilities.",
]


def classify(
    p: PhysicianState, analysis: OperationalAnalysis, cfg: OptimizationConfig
) -> PhysicianAvailabilityView:
    cls, conf, why = RULE_CLASS.get(
        p.decision_rule, (C.UNKNOWN, E.UNCERTAIN, f"Unrecognised decision rule {p.decision_rule}.")
    )
    if p.on_shift is None:
        cls, conf, why = C.UNKNOWN, E.UNCERTAIN, "Not in any roster and no shift events."
    rationale = [why]
    codes = [f.code for f in p.flags]
    for code in codes:
        if code in WEAKENING_FLAGS:
            weaker, note = WEAKENING_FLAGS[code]
            order = [E.CONFIRMED, E.LIKELY, E.UNCERTAIN, E.STALE]
            if order.index(weaker) > order.index(conf):
                conf = weaker
            rationale.append(f"Evidence weakened: {note}.")
    view = physician_view(p, analysis, cfg)
    exclusions = list(view.blocking_reasons)
    routable = bool(view.eligible) and cls not in (C.PROBABLY_BUSY_EXTERNAL, C.UNKNOWN)
    contradictions = sorted(set(codes) & CONTRADICTION_FLAGS)
    # Confirmation is needed when the *classification* may be wrong: stale or uncertain
    # evidence, or a busy state inferred from the camera alone. A manual status that
    # disagrees with a confirmed Synapse call/video does not make the call doubtful.
    needs_confirmation = conf in (E.UNCERTAIN, E.STALE) or "external_video_suspected" in codes
    if contradictions:
        rationale.append(
            "Contradictory or competing signals: "
            + ", ".join(c.replace("_", " ") for c in contradictions)
        )
    rationale.extend(p.explanation)
    consults = {c.consult_id: c for c in analysis.state.consultations}
    notes = sorted(
        cid for cid in p.open_consult_ids if cid in consults and consults[cid].stage in NOTE_STAGES
    )
    s = p.signals
    reachable = bool(p.on_shift) and cls not in (C.OFF_SHIFT, C.UNAVAILABLE, C.UNKNOWN)
    if cls is C.UNAVAILABLE and p.open_consult_ids:
        rationale.append(
            f"Inconsistency: unavailable while holding {len(p.open_consult_ids)} open consult(s)."
        )
    return PhysicianAvailabilityView(
        physician_id=p.physician_id,
        display_name=p.display_name,
        on_shift=p.on_shift,
        availability_class=cls,
        confidence=conf,
        decision_rule=p.decision_rule,
        auto_routable=routable,
        coordinator_reachable=reachable,
        needs_confirmation=needs_confirmation,
        routing_exclusions=exclusions,
        rationale=rationale,
        signal_times={
            "status_since": s.status_since,
            "agent_status_since": s.agent_status_since,
            "camera_since": s.camera_since,
            "last_call_ended_at": s.last_call_ended_at,
            "shift_started_at": p.shift_started_at,
        },
        evidence_event_ids=p.evidence_event_ids,
        flags=codes,
        open_consult_ids=p.open_consult_ids,
        unfinished_note_consult_ids=notes,
    )


def availability_report(
    analysis: OperationalAnalysis, cfg: OptimizationConfig
) -> AvailabilityReport:
    views = [
        classify(p, analysis, cfg)
        for p in sorted(analysis.state.physicians, key=lambda x: x.physician_id)
    ]
    return AvailabilityReport(
        as_of=analysis.state.as_of,
        data_version=analysis.state.data_version,
        physicians=views,
        counts_by_class=dict(sorted(Counter(v.availability_class.value for v in views).items())),
        rules=RULES,
    )


def class_map(analysis: OperationalAnalysis, cfg: OptimizationConfig) -> dict[str, C]:
    return {
        p.physician_id: classify(p, analysis, cfg).availability_class
        for p in analysis.state.physicians
    }
