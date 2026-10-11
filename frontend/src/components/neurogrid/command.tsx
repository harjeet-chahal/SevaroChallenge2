"use client";

import {
  AlarmClock,
  ArrowRight,
  BrainCircuit,
  ChevronDown,
  Fingerprint,
  ShieldAlert,
  Siren,
  UserRoundSearch,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { Button } from "@/components/ui/button";
import { useLiveResource } from "@/hooks/use-live-resource";
import { formatTime } from "@/lib/format";
import {
  neurogridApi,
  type LastSafeMoment,
  type LastSafeMomentReport,
  type ProblemGroup,
} from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import {
  CAUSE_LABEL,
  ClassBadge,
  ConfidenceBadge,
  Gate,
  PHASE,
  Pill,
  fmtMin,
} from "./kit";

function simulatorHref(p: { hospital_id?: string | null }, alertId?: string | null) {
  const q = new URLSearchParams();
  if (p.hospital_id) q.set("hospital", p.hospital_id);
  if (alertId) q.set("alert", alertId);
  return `/simulator?${q.toString()}`;
}

/** The single most urgent problem plus the nearest last-safe-moment deadline. */
export function PriorityOne() {
  const problems = useLiveResource((s) => neurogridApi.problems(s));
  const lsm = useLiveResource((s) => neurogridApi.lastSafeMoment(s));
  const top = problems.data?.groups[0];
  const deadline = lsm.data?.items.find((i) => i.latest_initiation_at) ?? lsm.data?.items[0];
  if (!problems.data || !top) return null;
  return (
    <section
      aria-label="Priority one"
      className={cn(
        "grid gap-4 rounded-xl border p-4 lg:grid-cols-[1.4fr_1fr]",
        top.severity === "critical" ? "border-critical-border bg-critical-soft/60" : "border-warning-border bg-warning-soft/50",
      )}
    >
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone="critical" icon={Siren}>
            Priority one · tier {top.tier}
          </Pill>
          <SeverityBadge severity={top.severity} />
          {top.root_cause ? <Pill tone="primary" icon={BrainCircuit}>{CAUSE_LABEL[top.root_cause]}</Pill> : null}
        </div>
        <p className="text-lg font-semibold">{top.title}</p>
        <p className="text-sm text-muted-foreground">{top.explanation}</p>
        <p className="text-sm">
          <span className="font-medium">Recommended: </span>
          {top.recommended_action}
        </p>
        <div className="flex flex-wrap gap-2 pt-1">
          <Button asChild size="sm">
            <Link href={simulatorHref(top, top.member_alert_ids[0])}>
              Simulate rescue options <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
        </div>
      </div>
      {deadline ? <DeadlineCard item={deadline} compact /> : null}
    </section>
  );
}

export function DeadlineCard({ item, compact }: { item: LastSafeMoment; compact?: boolean }) {
  const phase = PHASE[item.phase];
  const best = item.candidates.find((c) => c.physician_id === item.best_physician_id);
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card/70 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm font-semibold">
          <AlarmClock className="size-4 text-primary" aria-hidden />
          Last safe moment · {item.hospital_name}
        </span>
        <Pill tone={phase.tone}>{phase.label}</Pill>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <p className="text-[0.7rem] text-muted-foreground uppercase">Shortfall</p>
          <p className="font-semibold tabular-nums">{formatTime(item.shortfall_at, item.timezone)}</p>
        </div>
        <div>
          <p className="text-[0.7rem] text-muted-foreground uppercase">Start rescue by</p>
          <p className="font-semibold tabular-nums">
            {item.latest_initiation_at ? formatTime(item.latest_initiation_at, item.timezone) : "—"}
          </p>
        </div>
        <div>
          <p className="text-[0.7rem] text-muted-foreground uppercase">Remaining</p>
          <p className={cn("font-semibold tabular-nums", (item.remaining_minutes ?? -1) < 10 && "text-critical")}>
            {item.remaining_minutes === null ? "—" : fmtMin(item.remaining_minutes)}
          </p>
        </div>
      </div>
      {best ? (
        <p className="text-xs text-muted-foreground">
          Best candidate {best.display_name}: lead {best.lead.conservative_total_minutes} min (approval{" "}
          {best.lead.approval_minutes} + reply ≤ {best.lead.response_minutes_conservative} + online{" "}
          {best.lead.online_minutes}); expected online{" "}
          {best.activation_expected_at ? formatTime(best.activation_expected_at, item.timezone) : "—"} if started now.
        </p>
      ) : (
        <p className="text-xs text-critical">{item.mitigation[0] ?? item.explanation}</p>
      )}
      {!compact ? (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
          {item.mitigation.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ) : null}
      <p className="text-[0.68rem] text-muted-foreground">
        Simulation clock · planning deadline, not a guarantee of safety · stops when the scenario is paused.
      </p>
      <Button asChild size="sm" variant="outline" className="self-start">
        <Link href={simulatorHref({ hospital_id: item.hospital_id })}>
          Open rescue proposal <ArrowRight className="size-4" aria-hidden />
        </Link>
      </Button>
    </div>
  );
}

export function LastSafeMomentStrip({ className }: { className?: string }) {
  const lsm = useLiveResource((s) => neurogridApi.lastSafeMoment(s));
  return (
    <SectionCard
      className={className}
      title="Last Safe Moment"
      icon={AlarmClock}
      description="Latest time to start each rescue so an eligible physician is online before the projected shortfall (planning window)."
    >
      <Gate resource={lsm} feature="the last-safe-moment engine">
        {(r: LastSafeMomentReport) =>
          r.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No projected shortfall in the next {r.planning_horizon_minutes} min. Nothing to schedule.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {r.items.map((i) => (
                <DeadlineCard key={i.shortfall_id} item={i} />
              ))}
            </div>
          )
        }
      </Gate>
    </SectionCard>
  );
}

function ProblemRow({ g }: { g: ProblemGroup }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border bg-card/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="mt-0.5 w-7 shrink-0 text-center text-sm font-bold text-muted-foreground tabular-nums">
          {g.priority}
        </span>
        <span className="min-w-0 flex-1 space-y-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge severity={g.severity} />
            <Pill tone="muted">tier {g.tier}</Pill>
            {g.root_cause ? <Pill tone="primary">{CAUSE_LABEL[g.root_cause]}</Pill> : null}
            {g.member_alert_ids.length > 1 ? (
              <Pill tone="info" icon={Fingerprint}>
                {g.member_alert_ids.length} linked alerts
              </Pill>
            ) : null}
          </span>
          <span className="block truncate text-sm font-semibold">{g.title}</span>
          <span className="block text-xs text-muted-foreground">{g.summary}</span>
        </span>
        <ChevronDown className={cn("mt-1 size-4 shrink-0 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <div className="space-y-2 border-t px-3 py-2.5 text-sm">
          <p>{g.explanation}</p>
          <p>
            <span className="font-medium">Action: </span>
            {g.recommended_action}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {g.member_alert_ids.map((a) => (
              <Pill key={a} tone={g.critical_alert_ids.includes(a) ? "critical" : "muted"}>
                {a}
              </Pill>
            ))}
          </div>
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer">Ranking factors (machine-readable)</summary>
            <pre className="mt-1 overflow-x-auto rounded bg-muted p-2">{JSON.stringify(g.factors, null, 2)}</pre>
            <p>Fingerprint {g.fingerprint} — stable while the underlying issue persists.</p>
          </details>
          {g.hospital_id ? (
            <Button asChild size="sm" variant="outline">
              <Link href={simulatorHref(g, g.member_alert_ids[0])}>
                Compare interventions <ArrowRight className="size-4" aria-hidden />
              </Link>
            </Button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function ProblemBoard({ className }: { className?: string }) {
  const problems = useLiveResource((s) => neurogridApi.problems(s));
  return (
    <SectionCard
      className={className}
      title="Ranked problems"
      icon={ShieldAlert}
      description="Alerts grouped by underlying problem (deterministic fingerprint). Lexicographic tiers first, then a transparent tie-breaker. Every critical alert stays listed."
    >
      <Gate resource={problems} feature="problem ranking">
        {(r) => (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              {r.groups.length} problems from {r.alerts_total} alerts.
            </p>
            <ol className="space-y-2">
              {r.groups.map((g) => (
                <ProblemRow key={g.fingerprint} g={g} />
              ))}
            </ol>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Tier policy</summary>
              <ul className="mt-1 list-disc pl-4">
                {r.tier_policy.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </details>
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}

export function AvailabilityBoard({ className }: { className?: string }) {
  const res = useLiveResource((s) => neurogridApi.availability(s));
  return (
    <SectionCard
      className={className}
      title="Availability intelligence"
      icon={UserRoundSearch}
      description="Inferred from system signals, not self-reported status. Auto-routable follows the brief's routing rules; confirmation flags stale or contradictory evidence."
    >
      <Gate resource={res} feature="availability classification">
        {(r) => (
          <ul className="divide-y">
            {r.physicians
              .filter((p) => p.on_shift)
              .map((p) => (
                <li key={p.physician_id} className="space-y-1 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="mr-1 text-sm font-semibold">{p.display_name}</span>
                    <ClassBadge cls={p.availability_class} />
                    <ConfidenceBadge c={p.confidence} />
                    {p.auto_routable ? <Pill tone="success">auto-routable</Pill> : <Pill tone="muted">not routable</Pill>}
                    {p.needs_confirmation ? <Pill tone="warning">confirm</Pill> : null}
                    {p.unfinished_note_consult_ids.length ? (
                      <Pill tone="info">{p.unfinished_note_consult_ids.length} open note(s)</Pill>
                    ) : null}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {p.decision_rule}: {p.rationale[0]}
                    {p.routing_exclusions.length ? ` · Excluded from routing: ${p.routing_exclusions.join("; ")}` : ""}
                  </p>
                </li>
              ))}
          </ul>
        )}
      </Gate>
    </SectionCard>
  );
}

