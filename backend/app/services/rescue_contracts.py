"""Rescue Contracts: the NEUROGRID view of Phase 5 interventions, plus recovery verification.

A Rescue Contract *is* a Phase 5 intervention (same table, same validated state machine in
engines/interventions/machine.py). This service adds two things the workflow did not
expose:

  contract phase  the spec's contract states, derived from the intervention status, its
                  offers and data freshness (mapping in ``contract_phase``);
  verification    after a rescue shift is active, coverage at the target hospitals is
                  recomputed over the rescue interval from *current* state and compared
                  with the same models without the rescue physician. A recovery is never
                  claimed from a pending offer or an accepted-but-not-online physician.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.engines.intelligence import load_intelligence_config, planning_models
from app.engines.intelligence.common import deficit_between, drop_physicians, profiles
from app.repositories.workflow import WorkflowRepository
from app.schemas.common import ActorRef, UserRole
from app.schemas.intelligence import ContractVerification
from app.schemas.intervention import InterventionStatus as S
from app.schemas.intervention import InterventionType as T
from app.schemas.offer import OfferStatus as O
from app.services.analysis import AnalysisCache, AnalysisService
from app.services.workflow import WorkflowService
from app.services.workflow_records import write_audit

PHASES = {
    S.PROPOSED: "PROPOSED",
    S.PENDING_APPROVAL: "AWAITING_APPROVAL",
    S.REJECTED: "REJECTED",
    S.APPROVED: "READY_TO_DISPATCH",
    S.OFFER_SENT: "RESPONSE_PENDING",
    S.ACCEPTED: "ACTIVATION_PENDING",
    S.ACTIVATED: "ACTIVE",
    S.DECLINED: "FAILED",
    S.EXPIRED: "EXPIRED",
    S.CANCELLED: "CANCELLED",
    S.NO_LONGER_REQUIRED: "CANCELLED",
    S.COMPLETED: "RESOLVED",
}


def contract_phase(kind: T, status: S, *, stale: bool, verdict: str | None = None) -> str:
    if status in (S.PENDING_APPROVAL, S.APPROVED) and stale:
        return "REVALIDATION_REQUIRED"
    if kind is T.ESCALATION and status is S.APPROVED:
        return "ESCALATED"
    if status in (S.ACTIVATED, S.COMPLETED) and verdict:
        return {
            "resolved": "RESOLVED",
            "partially_resolved": "PARTIALLY_RESOLVED",
            "failed": "FAILED",
            "pending": "VERIFYING",
        }.get(verdict, PHASES[status])
    return PHASES.get(status, status.value.upper())


class RescueContractService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        analysis_cache: AnalysisCache,
        optimization_cache: AnalysisCache,
    ) -> None:
        self.session = session
        self.settings = settings
        self.repo = WorkflowRepository(session)
        self.workflow = WorkflowService(session, settings, analysis_cache, optimization_cache)
        self.analyses = AnalysisService(session, settings, analysis_cache)

    def verify(
        self, intervention_id: str, actor: ActorRef, *, record: bool
    ) -> ContractVerification:
        self.workflow._require_staff(actor)  # noqa: SLF001 - same role rule as the workflow
        self.workflow.sweep()
        rec = self.workflow._record(intervention_id)  # noqa: SLF001
        analysis = self.analyses.analysis()
        now = analysis.state.as_of
        version = analysis.state.data_version
        kind, status = T(rec.type), S(rec.status)
        stale = rec.created_data_version != version
        targets = list(rec.hospital_ids or [])
        names = {h.id: h.name for h in analysis.state.hospitals}
        findings: list[str] = []
        steps: list[str] = []
        verdict = "pending"
        start = end = None
        target_def = base_def = None
        new_critical: list[str] = []
        condition = (
            f"{', '.join(names.get(h, h) for h in targets) or 'Target'} has at least its "
            "required credentialed coverage over the rescue interval, without a new critical "
            "deficit elsewhere."
        )
        if kind is T.SPLIT_SHIFT:
            offers = self.repo.offers_for(rec.id)
            live = [o for o in offers if O(o.status) in (O.ACTIVE, O.COMPLETED)]
            accepted = [o for o in offers if O(o.status) is O.ACCEPTED]
            if live:
                offer = live[0]
                start = offer.activated_at or offer.start_at
                end = offer.end_at
                cfg = load_intelligence_config(self.settings.resolved_intelligence_policy_file)
                models = planning_models(analysis, cfg.planning_horizon_minutes)
                lo = max(start, now)
                hi = min(end, next(iter(models.values())).horizon_end) if models else end
                without = drop_physicians(models, [offer.physician_id])
                target_def = round(
                    sum(deficit_between(models[h], lo, hi) for h in targets if h in models), 4
                )
                base_def = round(
                    sum(deficit_between(without[h], lo, hi) for h in targets if h in without), 4
                )
                pa, pb = profiles(models), profiles(without)
                new_critical = sorted(
                    h
                    for h in models
                    if h not in targets
                    and pa[h].first_shortfall is not None
                    and pa[h].first_shortfall <= now
                    and pa[h].deficit_pm > pb[h].deficit_pm
                )
                state_word = "active" if O(offer.status) is O.ACTIVE else "completed"
                findings.append(
                    f"{offer.display_name} is {state_word}"
                    f" (online since {start.isoformat()}); interval checked {lo.isoformat()} – "
                    f"{hi.isoformat()} against data version {version}."
                )
                findings.append(
                    f"Target deficit with the rescue: {target_def:g} physician-min; without it: "
                    f"{base_def:g} physician-min."
                )
                if hi < end:
                    findings.append(
                        "The rescue runs past the planning horizon; the remainder is re-checked "
                        "as time advances."
                    )
                if new_critical:
                    verdict = "failed"
                    findings.append(
                        "New critical deficit attributable to the plan at "
                        + ", ".join(names.get(h, h) for h in new_critical)
                    )
                elif target_def == 0:
                    verdict = "resolved"
                elif target_def < (base_def or 0):
                    verdict = "partially_resolved"
                else:
                    verdict = "failed"
                if verdict != "resolved":
                    steps += [
                        "Run the Rescue Simulator for the residual shortfall.",
                        "A materially different plan needs a new clinical-lead approval.",
                    ]
            elif accepted:
                findings.append(
                    f"{accepted[0].display_name} accepted; expected online "
                    f"{accepted[0].expected_online_at.isoformat()}. Not verified until online "
                    "(acceptance is not activation)."
                )
            elif status in (S.DECLINED, S.EXPIRED):
                verdict = "failed"
                findings.append(f"The offer was {status.value}; the shortfall is not covered.")
                steps += [
                    "Re-run the Rescue Simulator and Last Safe Moment for the next candidate.",
                    "Escalate if no eligible candidate remains.",
                ]
            elif status in (S.CANCELLED, S.NO_LONGER_REQUIRED, S.REJECTED):
                verdict = "not_applicable"
                findings.append(f"Contract is {status.value}: {rec.status_reason or 'no reason'}.")
            else:
                findings.append(f"Contract is {status.value}: nothing to verify yet.")
        elif kind is T.REASSIGN_CONSULT:
            target = (rec.reassignment or {}).get("target_physician_id")
            consult = next(
                (c for c in analysis.state.consultations if c.consult_id == rec.consult_id), None
            )
            if status is S.COMPLETED and consult is not None:
                ok = consult.assigned_physician_id == target
                verdict = "resolved" if ok else "failed"
                findings.append(
                    f"{rec.consult_id} is assigned to {consult.assigned_physician_id or 'nobody'} "
                    f"(target {target})."
                )
            else:
                findings.append(f"Reassignment is {status.value}.")
            condition = f"Consult {rec.consult_id} is assigned to the approved physician."
        else:
            verdict = "not_applicable"
            alive = rec.alert_id and any(a.alert_id == rec.alert_id for a in analysis.alerts.alerts)
            findings.append(
                "Escalation: verification is the clinical lead's judgement. The escalated "
                f"alert is {'still active' if alive else 'no longer active'}."
            )
            condition = "The escalated problem is acknowledged and acted on by the clinical lead."
        if stale and status in (S.PENDING_APPROVAL, S.APPROVED):
            findings.append(
                f"Proposed at data version {rec.created_data_version}; now {version}. The plan is "
                "re-validated (eligibility, offer limits, remaining need) before approval and "
                "before dispatch."
            )
        result = ContractVerification(
            intervention_id=rec.id,
            contract_phase=contract_phase(kind, status, stale=stale, verdict=verdict),
            verdict=verdict,  # type: ignore[arg-type]
            checked_at=now,
            data_version=version,
            success_condition=condition,
            target_hospital_ids=targets,
            interval_start=start,
            interval_end=end,
            target_deficit_physician_minutes=target_def,
            baseline_deficit_physician_minutes=base_def,
            new_critical_elsewhere=new_critical,
            findings=findings,
            next_steps=steps,
        )
        if record:
            with self.workflow._write():  # noqa: SLF001 - short, transactional audit write
                write_audit(
                    self.session,
                    at=now,
                    actor=actor,
                    action="contract_verified",
                    summary=f"Verification: {verdict} ({result.contract_phase})",
                    entity_type="intervention",
                    entity_id=rec.id,
                    intervention_id=rec.id,
                    details=result.model_dump(mode="json"),
                )
        return result

    def phases(self, actor: ActorRef) -> dict[str, str]:
        if actor.role is UserRole.PHYSICIAN:
            return {}
        analysis = self.analyses.analysis()
        out = {}
        state = self.workflow.sim.system.get_simulation_state()
        for rec in self.repo.list_interventions(
            import_id=state.active_import_id if state else None
        ):
            out[rec.id] = contract_phase(
                T(rec.type),
                S(rec.status),
                stale=rec.created_data_version != analysis.state.data_version,
            )
        return out
