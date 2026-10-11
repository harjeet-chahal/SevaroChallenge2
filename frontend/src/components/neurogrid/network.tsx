"use client";

import "@xyflow/react/dist/style.css";

import { Background, Controls, MarkerType, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { Dna, GitFork, Network, ShieldHalf, Split, UsersRound } from "lucide-react";
import { useMemo, useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { useLiveResource } from "@/hooks/use-live-resource";
import { formatTime } from "@/lib/format";
import { neurogridApi, type FragilityReport, type GraphEdge, type GraphNode } from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import { CAUSE_LABEL, CLASS_LABEL, ClassBadge, Gate, KeyValue, Pill, fmtPm, type Tone } from "./kit";

const ET = "America/New_York";

const EDGE_STYLE: Record<GraphEdge["operational"], { stroke: string; dash?: string; width: number; label: string; opacity: number }> = {
  routable_now: { stroke: "var(--primary)", width: 2, label: "Counted · routable now", opacity: 1 },
  counted_busy: { stroke: "var(--viz-confirmed)", width: 1.5, label: "Counted · busy", opacity: 0.9 },
  counted_unverified: { stroke: "var(--viz-warning)", width: 1.5, dash: "5 4", label: "Counted · unverified", opacity: 0.9 },
  joins_later: { stroke: "var(--viz-uncertain)", width: 1.5, dash: "5 4", label: "Joins later", opacity: 0.85 },
  off_shift: { stroke: "var(--muted-foreground)", width: 1, dash: "2 4", label: "Credential only (off shift)", opacity: 0.35 },
  unavailable: { stroke: "var(--critical)", width: 1, dash: "2 4", label: "Unavailable", opacity: 0.5 },
  outside_scope: { stroke: "var(--muted-foreground)", width: 1, dash: "1 5", label: "Outside approved scope", opacity: 0.4 },
};

const RISK_TONE: Record<GraphNode["risk"], Tone> = { critical: "critical", warning: "warning", ok: "success", info: "muted" };
const RISK_RING: Record<GraphNode["risk"], string> = {
  critical: "border-critical-border bg-critical-soft",
  warning: "border-warning-border bg-warning-soft",
  ok: "border-success-border bg-success-soft",
  info: "border-border bg-muted",
};

function NodeLabel({ n }: { n: GraphNode }) {
  const a = n.attributes as Record<string, unknown>;
  return (
    <div className={cn("w-full rounded-md border px-2 py-1 text-left", RISK_RING[n.risk])}>
      <p className="truncate text-[11px] font-semibold text-foreground">{n.label}</p>
      <p className="truncate text-[10px] text-muted-foreground">
        {n.kind === "hospital"
          ? `${a.counted_now as number}/${(a.required_now as number | null) ?? "—"} now · ${n.status}${a.spike ? " · surge" : ""}`
          : `${CLASS_LABEL[n.status as keyof typeof CLASS_LABEL] ?? n.status}${a.shift_end ? ` · ends ${formatTime(String(a.shift_end), ET)}` : ""}`}
      </p>
    </div>
  );
}

function Graph({
  r,
  selected,
  onSelect,
}: {
  r: FragilityReport;
  selected: string | null;
  onSelect: (id: string | null) => void;
}) {
  const [hideOff, setHideOff] = useState(true);
  const [risk, setRisk] = useState<"all" | "risk">("all");
  const { nodes, edges } = useMemo(() => {
    const hospitals = r.nodes.filter((n) => n.kind === "hospital");
    const physicians = r.nodes
      .filter((n) => n.kind === "physician")
      .sort((a, b) => Number(a.attributes.criticality_rank) - Number(b.attributes.criticality_rank));
    const keep = (n: GraphNode) => risk === "all" || n.risk === "critical" || n.risk === "warning";
    const visibleEdges = r.edges.filter((e) => !(hideOff && e.operational === "off_shift"));
    const active = selected
      ? new Set(visibleEdges.filter((e) => `p:${e.physician_id}` === selected || `h:${e.hospital_id}` === selected).flatMap((e) => [`p:${e.physician_id}`, `h:${e.hospital_id}`]))
      : null;
    const toNode = (n: GraphNode, x: number, y: number): Node => ({
      id: n.id,
      position: { x, y },
      data: { label: <NodeLabel n={n} /> },
      sourcePosition: "left" as never,
      targetPosition: "right" as never,
      style: {
        width: 200,
        padding: 0,
        border: "none",
        background: "transparent",
        opacity: active && !active.has(n.id) ? 0.25 : keep(n) ? 1 : 0.3,
        outline: selected === n.id ? "2px solid var(--primary)" : undefined,
        borderRadius: 8,
      },
    });
    const ns: Node[] = [
      ...hospitals.map((n, i) => toNode(n, 0, i * 58)),
      ...physicians.map((n, i) => toNode(n, 420, i * 50)),
    ];
    const es: Edge[] = visibleEdges.map((e) => {
      const st = EDGE_STYLE[e.operational];
      const on = !active || (active.has(`p:${e.physician_id}`) && active.has(`h:${e.hospital_id}`) && (selected === `p:${e.physician_id}` || selected === `h:${e.hospital_id}`));
      return {
        id: e.id,
        source: `p:${e.physician_id}`,
        target: `h:${e.hospital_id}`,
        type: "default",
        animated: false,
        markerEnd: e.critical_dependency ? { type: MarkerType.ArrowClosed, color: "var(--critical)" } : undefined,
        style: {
          stroke: e.critical_dependency ? "var(--critical)" : st.stroke,
          strokeWidth: e.critical_dependency ? st.width + 1 : st.width,
          strokeDasharray: st.dash,
          opacity: on ? st.opacity : 0.06,
        },
      };
    });
    return { nodes: ns, edges: es };
  }, [r, selected, hideOff, risk]);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={hideOff} onChange={(e) => setHideOff(e.target.checked)} />
          Hide off-shift credential edges
        </label>
        <label className="flex items-center gap-1.5">
          Show
          <select value={risk} onChange={(e) => setRisk(e.target.value as "all" | "risk")} className="rounded border bg-card px-1.5 py-0.5">
            <option value="all">all nodes</option>
            <option value="risk">at-risk nodes</option>
          </select>
        </label>
        <select
          value={selected ?? ""}
          onChange={(e) => onSelect(e.target.value || null)}
          className="rounded border bg-card px-1.5 py-0.5"
          aria-label="Focus a hospital or physician"
        >
          <option value="">Focus: none</option>
          {r.nodes.map((n) => (
            <option key={n.id} value={n.id}>
              {n.kind === "hospital" ? "Hospital: " : "Physician: "}
              {n.label}
            </option>
          ))}
        </select>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Edge legend">
        {Object.entries(EDGE_STYLE).map(([k, s]) => (
          <li key={k} className="flex items-center gap-1.5">
            <svg width="20" height="6" aria-hidden>
              <line x1="0" y1="3" x2="20" y2="3" stroke={s.stroke} strokeWidth="2" strokeDasharray={s.dash} />
            </svg>
            {s.label}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <svg width="20" height="6" aria-hidden>
            <line x1="0" y1="3" x2="20" y2="3" stroke="var(--critical)" strokeWidth="3" />
          </svg>
          Critical dependency
        </li>
      </ul>
      <div className="h-[640px] w-full overflow-hidden rounded-lg border bg-background/60">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          colorMode="dark"
          fitView
          nodesDraggable
          nodesConnectable={false}
          onNodeClick={(_, n) => onSelect(n.id === selected ? null : n.id)}
          onPaneClick={() => onSelect(null)}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
        >
          <Background color="var(--viz-grid)" gap={24} />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <p className="text-xs text-muted-foreground">
        Hospitals left, physicians right (ordered by computed criticality). Edges are permanent credentials; style shows how each is usable right now.
      </p>
    </div>
  );
}

function Inspector({ r, selected }: { r: FragilityReport; selected: string | null }) {
  if (!selected) {
    return <p className="text-sm text-muted-foreground">Click a hospital or physician to inspect its evidence and simulate its removal.</p>;
  }
  const n = r.nodes.find((x) => x.id === selected);
  if (!n) return null;
  if (n.kind === "hospital") {
    const h = r.hospitals.find((x) => x.hospital_id === n.entity_id)!;
    return (
      <div className="space-y-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-semibold">{h.hospital_name}</p>
          <Pill tone={RISK_TONE[n.risk]}>{h.status}</Pill>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <KeyValue label="Counted now / required" value={`${h.counted_now} / ${h.required_now ?? "—"}`} />
          <KeyValue label="Routable now" value={h.routable_now} />
          <KeyValue label="Credentialed (any roster)" value={h.credentialed_total} />
          <KeyValue label="Min spare in horizon" value={h.min_spare_in_horizon ?? "—"} />
        </div>
        <p>{h.explanation}</p>
        {h.single_point_dependencies.length ? (
          <p className="text-xs">
            Single-point dependencies:{" "}
            {h.single_point_dependencies.map((p) => r.nodes.find((x) => x.entity_id === p)?.label ?? p).join(", ")}
          </p>
        ) : null}
      </div>
    );
  }
  const c = r.physicians.find((x) => x.physician_id === n.entity_id)!;
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-semibold">{c.display_name}</p>
        <ClassBadge cls={c.availability_class} />
        <Pill tone="muted">rank {c.rank}</Pill>
      </div>
      <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Simulated removal (computed)</h4>
      <p>{c.explanation}</p>
      <div className="grid grid-cols-2 gap-2">
        <KeyValue label="Added deficit" value={fmtPm(c.added_deficit_physician_minutes)} hint={`over ${r.horizon_minutes} min`} />
        <KeyValue label="Criticality score" value={c.criticality_score} hint="weighted computed quantities" />
      </div>
      {c.hospitals_affected.length ? (
        <ul className="space-y-1 text-xs">
          {c.hospitals_affected.map((i) => (
            <li key={i.hospital_id}>
              {i.hospital_name}: +{i.added_deficit_physician_minutes} phys-min
              {i.newly_uncovered ? " · newly uncovered" : ""}
              {i.first_shortfall_after ? ` · short from ${formatTime(i.first_shortfall_after, ET)}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">Score factors</summary>
        <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">{JSON.stringify(c.criticality_factors, null, 2)}</pre>
      </details>
    </div>
  );
}

export function NetworkIntelligence() {
  const res = useLiveResource((s) => neurogridApi.fragility(s));
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <div className="space-y-6">
      <SectionCard title="Network fragility scanner" icon={Network} description="Hospital ↔ physician credentialing graph with time-dependent operational state (NetworkX on the backend).">
        <Gate resource={res} feature="the network fragility scan">
          {(r) => (
            <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
              <Graph r={r} selected={selected} onSelect={setSelected} />
              <div className="space-y-4">
                <div className="rounded-lg border bg-muted/30 p-3">
                  <Inspector r={r} selected={selected} />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <KeyValue label="Credentialing edges" value={String(r.graph_metrics.credentialing_edges)} />
                  <KeyValue label="Graph density" value={String(r.graph_metrics.bipartite_density)} />
                  <KeyValue label="Single-point dependencies" value={String(r.graph_metrics.single_point_dependency_count)} hint="physicians" />
                  <KeyValue label="Baseline deficit" value={fmtPm(r.baseline_deficit_physician_minutes)} hint={`${r.horizon_minutes} min`} />
                </div>
              </div>
            </div>
          )}
        </Gate>
      </SectionCard>
      <Gate resource={res} feature="network resilience">
        {(r) => (
          <div className="grid gap-6 xl:grid-cols-2">
            <SectionCard title="Pool vs exclusive allocation" icon={Split} description="Per-hospital (pool) coverage lets one physician count everywhere they are credentialed. Exclusive allocation lets each fill one position (maximum bipartite matching).">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="text-left font-medium">Time</th>
                    <th className="text-right font-medium">Required</th>
                    <th className="text-right font-medium">Pool</th>
                    <th className="text-right font-medium">Exclusive</th>
                    <th className="text-left font-medium pl-3">Unmatched</th>
                  </tr>
                </thead>
                <tbody>
                  {r.allocation.map((a) => (
                    <tr key={a.at} className="border-t">
                      <td className="py-1">{a.label}</td>
                      <td className="text-right tabular-nums">{a.required_total}</td>
                      <td className="text-right tabular-nums">{a.pool_covered}</td>
                      <td className={cn("text-right tabular-nums", a.exclusive_shortfall > 0 && "text-warning")}>{a.exclusive_covered}</td>
                      <td className="pl-3 text-xs text-muted-foreground">{a.unmatched_hospital_ids.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-muted-foreground">
                The brief defines coverage per hospital (pool). The exclusive reading is shown so the difference is visible, not assumed away.
              </p>
            </SectionCard>
            <SectionCard title="Multi-failure scenarios" icon={GitFork} description="Computed on isolated copies; the baseline is unchanged.">
              <ul className="space-y-2 text-sm">
                {r.multi_failure.map((m) => (
                  <li key={m.scenario} className="rounded-lg border bg-card/60 p-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{m.label}</span>
                      {m.hospitals_newly_short.length ? <Pill tone="critical">{m.hospitals_newly_short.length} newly short</Pill> : <Pill tone="success">no new shortfall</Pill>}
                      <Pill tone="muted">+{m.added_deficit_physician_minutes} phys-min</Pill>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{m.explanation}</p>
                  </li>
                ))}
              </ul>
            </SectionCard>
            <SectionCard className="xl:col-span-2" title="Hospital resilience" icon={ShieldHalf}>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr>
                      <th className="text-left font-medium">Hospital</th>
                      <th className="text-left font-medium">Status</th>
                      <th className="text-right font-medium">Counted/req now</th>
                      <th className="text-right font-medium">Spare now</th>
                      <th className="text-right font-medium">Zero-spare min</th>
                      <th className="text-right font-medium">Deficit</th>
                      <th className="text-left font-medium pl-3">Single points</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.hospitals.map((h) => (
                      <tr key={h.hospital_id} className="border-t">
                        <td className="py-1">{h.hospital_name}</td>
                        <td><Pill tone={h.status === "short" ? "critical" : h.status === "fragile" ? "warning" : "success"}>{h.status}</Pill></td>
                        <td className="text-right tabular-nums">{h.counted_now}/{h.required_now ?? "—"}</td>
                        <td className="text-right tabular-nums">{h.spare_now ?? "—"}</td>
                        <td className="text-right tabular-nums">{h.fragile_minutes}</td>
                        <td className="text-right tabular-nums">{h.deficit_physician_minutes}</td>
                        <td className="pl-3 text-xs text-muted-foreground">{h.single_point_dependencies.join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </div>
        )}
      </Gate>
      <div className="grid gap-6 xl:grid-cols-2">
        <GenomePanel />
        <ScarcityPanel />
      </div>
      <GuardianPanel />
    </div>
  );
}

export function GenomePanel({ className }: { className?: string }) {
  const res = useLiveResource((s) => neurogridApi.genome(s));
  return (
    <SectionCard className={className} title="Coverage Genome" icon={Dna} description="Why resources cannot meet demand: weighted root causes measured from state at the problem instant.">
      <Gate resource={res} feature="root-cause diagnosis">
        {(r) => (
          <div className="space-y-3">
            {r.diagnoses.length === 0 ? <p className="text-sm text-muted-foreground">No shortfall or stranded consult to diagnose.</p> : null}
            {r.diagnoses.map((d) => (
              <div key={d.diagnosis_id} className="space-y-2 rounded-lg border bg-card/60 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={d.severity} />
                  <span className="font-semibold">{d.hospital_name}</span>
                  <Pill tone="muted">{d.problem.replaceAll("_", " ")}</Pill>
                  <Pill tone="primary">{CAUSE_LABEL[d.primary_cause]}</Pill>
                </div>
                <p className="text-sm">{d.explanation}</p>
                <div className="space-y-1" role="list" aria-label="Root-cause factor shares">
                  {d.factors.map((f) => (
                    <div key={f.cause} role="listitem" className="flex items-center gap-2 text-xs">
                      <span className="w-48 shrink-0 truncate">{CAUSE_LABEL[f.cause]}</span>
                      <span className="h-2 flex-1 rounded bg-muted">
                        <span className="block h-2 rounded bg-[var(--viz-confirmed)]" style={{ width: `${f.weight * 100}%` }} />
                      </span>
                      <span className="w-10 text-right tabular-nums">{Math.round(f.weight * 100)}%</span>
                    </div>
                  ))}
                </div>
                <details className="text-xs text-muted-foreground">
                  <summary className="cursor-pointer">Evidence &amp; counts</summary>
                  <ul className="mt-1 list-disc pl-4">
                    {d.factors.flatMap((f) => f.evidence).map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                  <p className="mt-1">Counts: {Object.entries(d.counts).map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(" · ")}</p>
                  <p>Excluded: {Object.entries(d.excluded_by_reason).map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(" · ") || "none"}</p>
                </details>
                <p className="text-xs"><span className="font-medium">Limiting constraint:</span> {d.limiting_constraint}. <span className="font-medium">Most useful:</span> {d.recommended_intervention}</p>
              </div>
            ))}
            {r.strategic.length ? (
              <details className="text-sm">
                <summary className="cursor-pointer font-medium">Strategic resilience suggestions ({r.strategic.length}) — planning only</summary>
                <ul className="mt-2 space-y-1.5 text-xs">
                  {r.strategic.map((s) => (
                    <li key={s.title}>
                      <span className="font-medium">{s.title}.</span> {s.detail}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}

export function ScarcityPanel({ className }: { className?: string }) {
  const res = useLiveResource((s) => neurogridApi.scarcity(s));
  return (
    <SectionCard className={className} title="Rescue scarcity index" icon={UsersRound} description="Every off-shift physician, every rule. How replaceable each eligible backup is, and what using them elsewhere would cost.">
      <Gate resource={res} feature="the scarcity index">
        {(r) => (
          <div className="space-y-3">
            {r.escalation_recommended ? (
              <p className="rounded-md border border-critical-border bg-critical-soft px-3 py-2 text-sm text-critical">
                No eligible off-shift backup for {r.uncovered_hospital_ids.join(", ")} — escalate.
              </p>
            ) : null}
            <ul className="space-y-2">
              {r.entries.map((e) => (
                <li key={e.physician_id} className="rounded-lg border bg-card/60 p-2.5 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{e.display_name}</span>
                    <Pill tone={e.eligible ? "success" : "muted"}>{e.eligible ? "eligible" : "not eligible"}</Pill>
                    <Pill tone={e.recommendation === "preserve" ? "warning" : e.recommendation === "allocate" ? "primary" : "muted"}>
                      {e.recommendation.replaceAll("_", " ")}
                    </Pill>
                    {e.eligible ? <Pill tone="muted">score {e.scarcity_score}</Pill> : null}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{e.explanation}</p>
                  {e.eligible ? (
                    <p className="text-xs">
                      {e.hospitals.map((h) => `${h.hospital_name}: ${h.sole_candidate ? "sole backup" : `${h.alternative_candidate_ids.length} alternative(s)`}, −${h.reduction_if_assigned} phys-min`).join(" · ")}
                      {e.minutes_to_come_online !== null ? ` · online in ${e.minutes_to_come_online} min` : ""}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Scarcity policy</summary>
              <ul className="mt-1 list-disc pl-4">
                {r.policy.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}

export function GuardianPanel({ className }: { className?: string }) {
  const res = useLiveResource((s) => neurogridApi.loadGuardian(s));
  return (
    <SectionCard className={className} title="Physician Load Guardian" icon={ShieldHalf} description="The split-shift trap: a joiner with zero consults would receive nearly every call. Protected vs unrestricted routing on modeled arrivals.">
      <Gate resource={res} feature="the load guardian">
        {(r) =>
          !r.available ? (
            <p className="text-sm text-muted-foreground">{r.conclusion}</p>
          ) : (
            <div className="space-y-3 text-sm">
              <Pill tone="warning">{r.label}</Pill>
              <p>{r.conclusion}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {(["unrestricted", "protected"] as const).map((k) => {
                  const o = (r[k] ?? {}) as Record<string, number>;
                  return (
                    <div key={k} className={cn("rounded-lg border p-3", k === "protected" ? "border-success-border bg-success-soft/40" : "border-warning-border bg-warning-soft/40")}>
                      <p className="font-semibold">{k === "protected" ? "Protected (proposed policy)" : "Unrestricted least-loaded"}</p>
                      <p className="text-xs">Routed to {r.display_name}: <b>{o.routed_to_joiner}</b> of {o.modeled_arrivals} · outside gap hospitals: <b>{o.routed_to_joiner_elsewhere}</b></p>
                      <p className="text-xs">Joiner final consults {o.joiner_final_consults} vs peer median {o.peer_median_consults ?? "—"}</p>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs">Scope: {r.scope_hospital_ids.join(", ")} · excluded: {r.excluded_hospital_ids.join(", ") || "none"} · seeded count {r.workload_limit}</p>
              <ul className="list-disc pl-4 text-xs text-muted-foreground">
                {r.release_conditions.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )
        }
      </Gate>
    </SectionCard>
  );
}
