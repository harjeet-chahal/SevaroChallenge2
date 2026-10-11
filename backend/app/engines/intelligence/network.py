"""Network Fragility Scanner (pure, NetworkX).

Graph. A bipartite graph with hospital and physician nodes. Edges are *permanent*
credentialing relationships. Operational usability (counted now, busy, off shift, outside
an approved scope...) is a separate, time-dependent edge attribute, so an unused
credential is never mistaken for coverage.

Single-point failure. For each physician who counts toward coverage somewhere in the
horizon, their contribution windows are removed from an isolated copy of the coverage
models and the exact deficit integral is recomputed. "Added deficit" is the difference in
physician-minutes; "newly uncovered" hospitals had no shortfall in the horizon before.

Pool vs exclusive allocation. Coverage is defined per hospital and non-exclusively (the
brief's minimum of available credentialed physicians, Phase 3). The allocation check also
reports the stricter reading where each physician fills at most one required position at
a time (maximum bipartite matching, Hopcroft-Karp), so the gap between the two readings is
visible instead of assumed away.

Criticality = Σ weight × computed quantity (weights in IntelligenceConfig.fragility).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import networkx as nx
from networkx.algorithms import bipartite

from app.engines.analysis import OperationalAnalysis
from app.engines.intelligence.common import (
    Models,
    Profile,
    drop_physicians,
    end_windows_at,
    evaluation_at,
    profiles,
)
from app.engines.intelligence.config import IntelligenceConfig
from app.engines.timeline import fmt_local
from app.schemas.intelligence import (
    AllocationCheck,
    AvailabilityClass,
    FragilityReport,
    GraphEdge,
    GraphNode,
    HospitalImpact,
    HospitalResilience,
    MultiFailureResult,
    PhysicianCriticality,
)

METHOD = [
    "Bipartite graph: hospitals × physicians, edges = credentialing (permanent).",
    "Edge 'operational' = how the credential is usable now (counted, busy, off shift, ...).",
    "Single-point failure: remove one physician's coverage windows from an isolated copy of "
    "the coverage models and recompute the exact deficit integral over the horizon.",
    "Exclusive allocation: maximum bipartite matching of physicians to required positions "
    "(Hopcroft-Karp) at now and at each coverage change point.",
    "Criticality score = weighted sum of added deficit (hours), newly uncovered hospitals, "
    "hospitals where the physician is the only counted one now, and relevant credentials.",
]

ASSUMPTIONS = [
    "Coverage is credentialed on-duty capacity (busy still counts); see the official "
    "scenario audit, section 2.",
    "Removal means the physician stops counting from now until the horizon end.",
    "Scores are relative rankings of computed quantities, not probabilities.",
]


def _impacts(
    names: Mapping[str, str], before: Mapping[str, Profile], after: Mapping[str, Profile]
) -> list[HospitalImpact]:
    out = []
    for hid in sorted(before):
        b, a = before[hid], after[hid]
        added = round(a.deficit_pm - b.deficit_pm, 4)
        if added <= 1e-9:
            continue
        out.append(
            HospitalImpact(
                hospital_id=hid,
                hospital_name=names.get(hid, hid),
                added_deficit_physician_minutes=added,
                first_shortfall_before=b.first_shortfall,
                first_shortfall_after=a.first_shortfall,
                newly_uncovered=b.first_shortfall is None and a.first_shortfall is not None,
            )
        )
    return out


def _allocation(models: Models, at: datetime, label: str) -> AllocationCheck:
    graph = nx.Graph()
    slots: list[tuple[str, int]] = []
    required_total = pool = 0
    for hid in sorted(models):
        piece = evaluation_at(models[hid], at)
        if piece is None or piece[2].required is None:
            continue
        e = piece[2]
        required_total += e.required
        pool += min(e.required, len(e.active))
        for i in range(e.required):
            slot = (hid, i)
            slots.append(slot)
            graph.add_node(("slot", hid, i), bipartite=0)
            for w in e.active:
                graph.add_node(("phys", w.physician_id), bipartite=1)
                graph.add_edge(("slot", hid, i), ("phys", w.physician_id))
    top = [n for n in graph.nodes if n[0] == "slot"]
    matching = bipartite.hopcroft_karp_matching(graph, top_nodes=top) if top else {}
    assignment: dict[str, list[str]] = {}
    unmatched: set[str] = set()
    for hid, i in slots:
        partner = matching.get(("slot", hid, i))
        if partner is None:
            unmatched.add(hid)
        else:
            assignment.setdefault(hid, []).append(partner[1])
    covered = sum(len(v) for v in assignment.values())
    return AllocationCheck(
        at=at,
        label=label,
        required_total=required_total,
        pool_covered=pool,
        exclusive_covered=covered,
        exclusive_shortfall=required_total - covered,
        unmatched_hospital_ids=sorted(unmatched),
        assignment={k: sorted(v) for k, v in sorted(assignment.items())},
    )


def _checkpoints(models: Models, as_of: datetime, limit: int = 10) -> list[datetime]:
    points: set[datetime] = {as_of}
    for m in models.values():
        for w in m.windows:
            for t in (w.start, w.end):
                if t is not None and as_of < t < m.horizon_end:
                    points.add(t)
    return sorted(points)[:limit]


def fragility_report(
    analysis: OperationalAnalysis,
    models: Models,
    classes: Mapping[str, AvailabilityClass],
    routable: Mapping[str, bool],
    cfg: IntelligenceConfig,
    *,
    horizon_minutes: int,
    candidates_by_hospital: Mapping[str, list[str]] | None = None,
) -> FragilityReport:
    state = analysis.state
    as_of = state.as_of
    names = {h.id: h.name for h in state.hospitals}
    zones = {h.id: h.timezone for h in state.hospitals}
    base = profiles(models)
    base_total = round(sum(p.deficit_pm for p in base.values()), 4)
    w = cfg.fragility

    counted_now: dict[str, list[str]] = {}
    for hid, m in models.items():
        piece = evaluation_at(m, as_of)
        counted_now[hid] = [x.physician_id for x in piece[2].active] if piece else []
    relevant_ids = sorted({x.physician_id for m in models.values() for x in m.windows})

    # ---- single-point failure, per physician -------------------------------------------
    crit: list[PhysicianCriticality] = []
    deps: dict[str, list[str]] = {hid: [] for hid in models}
    physicians = {p.physician_id: p for p in state.physicians}
    for p in sorted(state.physicians, key=lambda x: x.physician_id):
        pid = p.physician_id
        relevant = pid in relevant_ids
        impacts: list[HospitalImpact] = []
        if relevant:
            after = profiles(drop_physicians(models, [pid]))
            impacts = _impacts(names, base, after)
            for imp in impacts:
                deps[imp.hospital_id].append(pid)
        added = round(sum(i.added_deficit_physician_minutes for i in impacts), 4)
        newly = [i.hospital_id for i in impacts if i.newly_uncovered]
        sole = sorted(h for h, ids in counted_now.items() if ids == [pid])
        cred_relevant = (
            sum(
                1
                for h in p.credentialed_hospital_ids
                if any(x.physician_id == pid for x in models[h].windows)
            )
            if relevant
            else 0
        )
        factors = {
            "added_deficit_hours": round(added / 60, 4),
            "newly_uncovered_hospitals": float(len(newly)),
            "sole_coverage_hospitals": float(len(sole)),
            "credentialed_relevant_hospitals": float(cred_relevant),
        }
        score = round(
            w.added_deficit_hours * factors["added_deficit_hours"]
            + w.newly_uncovered_hospitals * factors["newly_uncovered_hospitals"]
            + w.sole_coverage_hospitals * factors["sole_coverage_hospitals"]
            + w.credentialed_relevant_hospitals * factors["credentialed_relevant_hospitals"],
            4,
        )
        end = p.scheduled_shift.end if p.scheduled_shift and p.on_shift else None
        if not relevant:
            text = (
                f"{p.display_name} does not count toward coverage anywhere in the next "
                f"{horizon_minutes} min; credentialing edges exist but are not in use."
            )
        elif impacts:
            parts = [
                f"{names.get(i.hospital_id, i.hospital_id)} +{i.added_deficit_physician_minutes:g} "
                "physician-min"
                + (
                    " (new shortfall from "
                    f"{fmt_local(i.first_shortfall_after, zones[i.hospital_id])})"
                    if i.newly_uncovered and i.first_shortfall_after
                    else ""
                )
                for i in impacts
            ]
            text = f"Losing {p.display_name} now would add deficit at " + "; ".join(parts) + "."
        else:
            text = (
                f"Losing {p.display_name} now would not create a shortfall in the horizon: every "
                "hospital they cover keeps enough other credentialed capacity."
            )
        crit.append(
            PhysicianCriticality(
                physician_id=pid,
                display_name=p.display_name,
                on_shift=p.on_shift,
                availability_class=classes.get(pid, AvailabilityClass.UNKNOWN),
                shift_end=end,
                credentialed_hospital_count=len(p.credentialed_hospital_ids),
                relevant=relevant,
                added_deficit_physician_minutes=added,
                hospitals_affected=impacts,
                newly_uncovered_hospital_ids=newly,
                sole_coverage_hospital_ids=sole,
                criticality_score=score,
                criticality_factors=factors,
                rank=0,
                explanation=text,
            )
        )
    crit.sort(key=lambda c: (-c.criticality_score, c.physician_id))
    for i, c in enumerate(crit, start=1):
        c.rank = i

    # ---- hospital resilience ---------------------------------------------------------------
    credentialed_total = {
        h.id: sum(1 for p in state.physicians if h.id in p.credentialed_hospital_ids)
        for h in state.hospitals
    }
    hospitals: list[HospitalResilience] = []
    for hid in sorted(models):
        pr = base[hid]
        routable_now = sum(1 for pid in counted_now[hid] if routable.get(pid))
        spare = None if pr.required_now is None else pr.counted_now - pr.required_now
        single = sorted(set(deps[hid]))
        if not pr.requirement_defined:
            status, text = "no_requirement", "No coverage requirement defined for this hospital."
        elif pr.deficit_pm > 0:
            status = "short"
            text = (
                f"Shortfall of {pr.deficit_pm:g} physician-minutes in the horizon"
                + (
                    f", first at {fmt_local(pr.first_shortfall, zones[hid])}"
                    if pr.first_shortfall
                    else ""
                )
                + "."
            )
        elif pr.fragile_minutes > 0 or single:
            status = "fragile"
            text = (
                f"Requirement met, but with zero spare for {pr.fragile_minutes:g} min"
                + (
                    "; losing "
                    + ", ".join(physicians[x].display_name for x in single if x in physicians)
                    + " "
                    "would create a shortfall"
                    if single
                    else ""
                )
                + "."
            )
        else:
            status = "resilient"
            text = (
                f"At least one spare credentialed physician throughout (min spare {pr.min_spare})."
            )
        hospitals.append(
            HospitalResilience(
                hospital_id=hid,
                hospital_name=names.get(hid, hid),
                timezone=zones.get(hid, "UTC"),
                credentialed_total=credentialed_total.get(hid, 0),
                required_now=pr.required_now,
                counted_now=pr.counted_now,
                routable_now=routable_now,
                spare_now=spare,
                min_spare_in_horizon=pr.min_spare,
                shortfall_minutes=pr.shortfall_minutes,
                fragile_minutes=pr.fragile_minutes,
                deficit_physician_minutes=pr.deficit_pm,
                single_point_dependencies=single,
                status=status,  # type: ignore[arg-type]
                explanation=text,
            )
        )

    # ---- exclusive allocation -------------------------------------------------------------
    label_zone = state.hospitals[0].timezone if state.hospitals else "UTC"
    allocation = [
        _allocation(models, t, "now" if t == as_of else f"change point {fmt_local(t, label_zone)}")
        for t in _checkpoints(models, as_of)
    ]

    # ---- multi-failure scenarios (computed, isolated copies) -------------------------------
    multi: list[MultiFailureResult] = []

    def scenario(key: str, label: str, removed: list[str], new_models: Models, why: str) -> None:
        after = profiles(new_models)
        impacts = _impacts(names, base, after)
        multi.append(
            MultiFailureResult(
                scenario=key,
                label=label,
                removed_physician_ids=removed,
                added_deficit_physician_minutes=round(
                    sum(i.added_deficit_physician_minutes for i in impacts), 4
                ),
                hospitals_newly_short=[i.hospital_id for i in impacts if i.newly_uncovered],
                hospitals_affected=impacts,
                explanation=why,
            )
        )

    horizon_end = next(iter(models.values())).horizon_end if models else as_of
    ending = sorted(
        (p.scheduled_shift.end, p.physician_id)
        for p in state.physicians
        if p.on_shift
        and p.scheduled_shift
        and as_of < p.scheduled_shift.end <= horizon_end
        and p.physician_id in relevant_ids
    )
    if len(ending) >= 2:
        pair = [ending[0][1], ending[1][1]]
        scenario(
            "two_shift_endings_now",
            "Two earliest shift endings happen now",
            pair,
            end_windows_at(models, pair, as_of),
            f"{', '.join(physicians[x].display_name for x in pair)} leave now instead of at their "
            "scheduled ends.",
        )
    spiking = [
        hid
        for hid, dm in analysis.demand_models.items()
        if dm.evaluate(as_of).spike and hid in models
    ]
    for hid in spiking[:2]:
        leaving = sorted(
            (p.scheduled_shift.end, p.physician_id)
            for p in state.physicians
            if p.on_shift
            and p.scheduled_shift
            and hid in p.credentialed_hospital_ids
            and p.physician_id in counted_now.get(hid, [])
        )
        if leaving:
            pid = leaving[0][1]
            scenario(
                f"shift_end_during_surge:{hid}",
                f"Shift ends now during the surge at {names.get(hid, hid)}",
                [pid],
                end_windows_at(models, [pid], as_of),
                f"{physicians[pid].display_name} (earliest shift end among those counted at "
                f"{names.get(hid, hid)}) leaves now while demand is above p90.",
            )
    shared = max(
        (c for c in crit if c.relevant and c.on_shift),
        key=lambda c: (c.credentialed_hospital_count, c.criticality_score, c.physician_id),
        default=None,
    )
    if shared is not None:
        scenario(
            "shared_physician_unavailable",
            "Most widely shared physician becomes unavailable",
            [shared.physician_id],
            drop_physicians(models, [shared.physician_id]),
            f"{shared.display_name} is credentialed at {shared.credentialed_hospital_count} "
            "hospitals; they stop counting now.",
        )
    thin = sorted(
        (len(ids), hid) for hid, ids in counted_now.items() if ids and base[hid].requirement_defined
    )
    if thin:
        n, hid = thin[0]
        scenario(
            f"final_qualified_lost:{hid}",
            f"{names.get(hid, hid)} loses every counted physician",
            counted_now[hid],
            drop_physicians(models, counted_now[hid]),
            f"{names.get(hid, hid)} has the fewest counted physicians now ({n}); all of them "
            "stop counting.",
        )
    if candidates_by_hospital:
        backups: dict[str, list[str]] = {}
        for hid, cands in candidates_by_hospital.items():
            for pid in cands:
                backups.setdefault(pid, []).append(hid)
        contested = sorted((pid, hs) for pid, hs in backups.items() if len(hs) >= 2)
        for pid, hs in contested[:1]:
            name = next((p.display_name for p in state.physicians if p.physician_id == pid), pid)
            multi.append(
                MultiFailureResult(
                    scenario=f"competing_for_backup:{pid}",
                    label=f"{len(hs)} hospitals compete for the same backup",
                    removed_physician_ids=[],
                    added_deficit_physician_minutes=0.0,
                    hospitals_newly_short=[],
                    hospitals_affected=[],
                    explanation=(
                        f"{name} is an eligible off-shift backup for "
                        f"{', '.join(names.get(h, h) for h in hs)}. One offer can be scoped to "
                        "several of them (counted at each, Phase 3 definition), but under "
                        "exclusive allocation they can fill only one position at a time; see the "
                        "Scarcity index for alternatives."
                    ),
                )
            )

    # ---- graph -----------------------------------------------------------------------------
    graph = nx.Graph()
    for h in state.hospitals:
        graph.add_node(("h", h.id), bipartite=0)
    for p in state.physicians:
        graph.add_node(("p", p.physician_id), bipartite=1)
        for hid in p.credentialed_hospital_ids:
            if ("h", hid) in graph:
                graph.add_edge(("p", p.physician_id), ("h", hid))
    articulation = sorted(n[1] for n in nx.articulation_points(graph) if n[0] == "p")
    components = nx.number_connected_components(graph)
    density = (
        bipartite.density(graph, [n for n in graph if n[0] == "h"])
        if graph.number_of_edges()
        else 0.0
    )

    crit_by_id = {c.physician_id: c for c in crit}
    contributor_status: dict[tuple[str, str], str] = {}
    for hid, m in models.items():
        for c in m.contributors:
            contributor_status[(c.physician_id, hid)] = c.status
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for h in hospitals:
        risk = (
            "critical"
            if h.status == "short" and (h.required_now or 0) > h.counted_now
            else ("warning" if h.status in ("short", "fragile") else "ok")
        )
        nodes.append(
            GraphNode(
                id=f"h:{h.hospital_id}",
                kind="hospital",
                entity_id=h.hospital_id,
                label=h.hospital_name,
                status=h.status,
                risk=risk,  # type: ignore[arg-type]
                attributes={
                    "timezone": h.timezone,
                    "required_now": h.required_now,
                    "counted_now": h.counted_now,
                    "routable_now": h.routable_now,
                    "spare_now": h.spare_now,
                    "credentialed_total": h.credentialed_total,
                    "deficit_physician_minutes": h.deficit_physician_minutes,
                    "fragile_minutes": h.fragile_minutes,
                    "spike": bool(
                        analysis.demand_models.get(h.hospital_id)
                        and analysis.demand_models[h.hospital_id].evaluate(as_of).spike
                    ),
                    "explanation": h.explanation,
                },
            )
        )
    for p in sorted(state.physicians, key=lambda x: x.physician_id):
        c = crit_by_id[p.physician_id]
        cls = classes.get(p.physician_id, AvailabilityClass.UNKNOWN)
        risk = (
            "critical"
            if c.newly_uncovered_hospital_ids
            else (
                "warning"
                if c.added_deficit_physician_minutes > 0
                else ("info" if not c.relevant else "ok")
            )
        )
        nodes.append(
            GraphNode(
                id=f"p:{p.physician_id}",
                kind="physician",
                entity_id=p.physician_id,
                label=p.display_name,
                status=cls.value,
                risk=risk,  # type: ignore[arg-type]
                attributes={
                    "roster": p.roster,
                    "roster_role": p.roster_role,
                    "on_shift": p.on_shift,
                    "shift_end": c.shift_end.isoformat() if c.shift_end else None,
                    "minutes_to_shift_end": p.minutes_to_shift_end,
                    "consults_this_shift": p.consults_this_shift,
                    "open_consults": len(p.open_consult_ids),
                    "criticality_score": c.criticality_score,
                    "criticality_rank": c.rank,
                    "articulation_point": p.physician_id in articulation,
                    "routable": bool(routable.get(p.physician_id)),
                    "explanation": c.explanation,
                    "temporary_shift": p.temporary_shift.phase if p.temporary_shift else None,
                },
            )
        )
        dep_hospitals = {i.hospital_id for i in c.hospitals_affected}
        for hid in sorted(p.credentialed_hospital_ids):
            if hid not in models:
                continue
            status = contributor_status.get((p.physician_id, hid))
            if p.on_shift is False and status is None:
                op = "off_shift"
            elif status == "excluded":
                scope = p.routing_scope_hospital_ids
                op = (
                    "outside_scope"
                    if scope is not None and hid not in scope
                    else ("unavailable" if cls is AvailabilityClass.UNAVAILABLE else "off_shift")
                )
            elif status in ("joins_later", "pending_activation", "proposed"):
                op = "joins_later"
            elif status == "counted":
                if routable.get(p.physician_id):
                    op = "routable_now"
                elif cls is AvailabilityClass.UNCERTAIN:
                    op = "counted_unverified"
                else:
                    op = "counted_busy"
            else:
                op = "off_shift"
            edges.append(
                GraphEdge(
                    id=f"e:{p.physician_id}:{hid}",
                    physician_id=p.physician_id,
                    hospital_id=hid,
                    operational=op,  # type: ignore[arg-type]
                    critical_dependency=hid in dep_hospitals,
                )
            )

    return FragilityReport(
        as_of=as_of,
        data_version=state.data_version,
        horizon_minutes=horizon_minutes,
        baseline_deficit_physician_minutes=base_total,
        nodes=nodes,
        edges=edges,
        physicians=crit,
        hospitals=hospitals,
        allocation=allocation,
        multi_failure=multi,
        graph_metrics={
            "hospitals": len(state.hospitals),
            "physicians": len(state.physicians),
            "credentialing_edges": graph.number_of_edges(),
            "bipartite_density": round(density, 4),
            "connected_components": components,
            "articulation_physicians": articulation,
            "hospital_degree": {
                h.id: graph.degree(("h", h.id)) for h in sorted(state.hospitals, key=lambda x: x.id)
            },
            "single_point_dependency_count": sum(
                1 for c in crit if c.added_deficit_physician_minutes > 0
            ),
        },
        score_weights=cfg.fragility.model_dump(),
        method=METHOD,
        assumptions=ASSUMPTIONS,
    )
