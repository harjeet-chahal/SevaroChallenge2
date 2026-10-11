"""Deterministic, explainable alert prioritisation.

Sort key (lexicographic, most significant first):

1. severity          critical < warning < info            — hard safety precedence
2. category_rank     0 stroke consult at risk
                     1 coverage gap now
                     2 other consult at risk
                     3 projected coverage gap
                     4 open notes near shift end
                     5 demand spike
                     6 physician signal conflict
3. repeat_requests   the hospital called again about this consult: more calls first (brief:
                     a repeat call is the same patient and "should move up the list")
4. urgency           higher first (overrun ratio, imminence, deficit size — per rule)
5. coverage_risk     hospital with a gap now (2) > projected gap (1) > none (0)
6. affected          more consults/hospitals touched first
7. alert_id          stable tie-break

Softer workload considerations (repeat calls, urgency, affected) can never lift an alert
above a higher severity or a more safety-critical category.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

from app.engines.alert_detection.detect import AlertDraft, DetectionContext
from app.schemas.alert import Alert, AlertList, AlertRank
from app.schemas.common import Severity

SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _coverage_risk(ctx: DetectionContext, hospital_id: str | None) -> int:
    hc = ctx.coverage_by_hospital.get(hospital_id or "")
    if hc is None or not hc.requirement_defined:
        return 0
    if hc.metrics.deficit_now:
        return 2
    return 1 if hc.metrics.first_shortfall_at is not None else 0


def rank_alerts(
    ctx: DetectionContext, drafts: Sequence[AlertDraft], data_version: int
) -> AlertList:
    repeats = {
        c.consult_id: sum(a.code == "repeat_request" for a in c.anomalies)
        for c in ctx.state.consultations
    }
    keyed = []
    for d in drafts:
        rank = AlertRank(
            severity_rank=SEVERITY_RANK[d.severity],
            category_rank=d.category_rank,
            repeat_requests=repeats.get(d.consult_id or "", 0),
            urgency=round(d.urgency, 6),
            coverage_risk=_coverage_risk(ctx, d.hospital_id),
            affected=d.affected,
        )
        key = (
            rank.severity_rank,
            rank.category_rank,
            -rank.repeat_requests,
            -rank.urgency,
            -rank.coverage_risk,
            -rank.affected,
            d.alert_id,
        )
        keyed.append((key, d, rank))
    keyed.sort(key=lambda item: item[0])

    coverage_text = {
        2: "hospital has a coverage gap now",
        1: "hospital has a projected coverage gap",
    }
    alerts: list[Alert] = []
    for position, (_, d, rank) in enumerate(keyed, start=1):
        reasons = [
            f"{d.severity.value} severity: {d.severity_reason}",
            f"category: {d.category_reason}",
        ]
        if rank.repeat_requests:
            reasons.append(
                f"the hospital has called again about this consult ({rank.repeat_requests} "
                "repeat call(s)); same patient, still waiting since the first request"
            )
        reasons.append(f"urgency: {d.urgency_reason}")
        if rank.coverage_risk:
            reasons.append(coverage_text[rank.coverage_risk])
        reasons.append(f"affects {d.affected} open consult(s)/item(s)")
        hospital = ctx.hospitals.get(d.hospital_id or "")
        physician = ctx.physicians.get(d.physician_id or "")
        alerts.append(
            Alert(
                alert_id=d.alert_id,
                rule_code=d.rule_code,
                rule_name=d.rule_name,
                rule_source=d.rule_source,
                rule_reference=d.rule_reference,
                category=d.category,
                severity=d.severity,
                severity_reason=d.severity_reason,
                priority=position,
                priority_reasons=reasons,
                rank=rank,
                title=d.title,
                summary=d.summary,
                recommended_action_type=d.action,
                recommended_action_reason=d.action_reason,
                hospital_id=d.hospital_id,
                hospital_name=hospital.name if hospital else None,
                hospital_timezone=hospital.timezone if hospital else None,
                consult_id=d.consult_id,
                physician_id=d.physician_id,
                physician_name=physician.display_name if physician else None,
                as_of=ctx.as_of,
                condition_since=d.condition_since,
                elapsed_seconds=d.elapsed_seconds,
                warning_after_seconds=d.warning_after_seconds,
                critical_after_seconds=d.critical_after_seconds,
                impact_at=d.impact_at,
                minutes_to_impact=round(d.minutes_to_impact, 4)
                if d.minutes_to_impact is not None
                else None,
                evidence=d.evidence,
                event_ids=sorted(set(d.event_ids)),
                assumptions=d.assumptions,
            )
        )
    by_severity: Mapping[str, int] = Counter(a.severity.value for a in alerts)
    by_rule: Mapping[str, int] = Counter(a.rule_code.value for a in alerts)
    return AlertList(
        as_of=ctx.as_of,
        data_version=data_version,
        total=len(alerts),
        open_total=len(alerts),
        counts_by_severity={s.value: by_severity.get(s.value, 0) for s in SEVERITY_RANK},
        counts_by_rule=dict(sorted(by_rule.items())),
        alerts=alerts,
        notes=sorted(set(ctx.notes)),
    )
