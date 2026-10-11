"use client";

import { ArrowRight, ChevronRight, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { Button } from "@/components/ui/button";
import { useLiveResource } from "@/hooks/use-live-resource";
import { formatHm, zoneAbbr } from "@/lib/format";
import {
  neurogridApi,
  type LastSafeMoment,
  type LastSafeMomentReport,
  type ProblemGroup,
} from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import { CAUSE_LABEL, CLASS_TONE, CLASS_LABEL, Gate, PHASE, Pill, fmtMin, type Tone } from "./kit";

function simulatorHref(p: { hospital_id?: string | null }, alertId?: string | null) {
  const q = new URLSearchParams();
  if (p.hospital_id) q.set("hospital", p.hospital_id);
  if (alertId) q.set("alert", alertId);
  return `/simulator?${q.toString()}`;
}

/**
 * Split a backend problem title such as "CON-2110: Assigned, physician not yet contacted —
 * 12 min 45 s" into subject, headline and measured duration — display only.
 */
function splitTitle(title: string): { subject: string | null; headline: string; measure: string | null } {
  const [main, ...rest] = title.split(" — ");
  const tail = rest.join(" — ");
  const measure = /^\d[\d\s]*(h|min|s)\b/.test(tail) ? tail : null;
  const head = measure ? main : title;
  const colon = head.indexOf(": ");
  if (colon > 0 && colon <= 24) return { subject: head.slice(0, colon), headline: head.slice(colon + 2), measure };
  return { subject: null, headline: head, measure };
}

/** The single most urgent problem plus the nearest last-safe-moment deadline. */
export function PriorityOne() {
  const problems = useLiveResource((s) => neurogridApi.problems(s));
  const lsm = useLiveResource((s) => neurogridApi.lastSafeMoment(s));
  const top = problems.data?.groups[0];
  const deadline = lsm.data?.items.find((i) => i.latest_initiation_at) ?? lsm.data?.items[0];
  if (!problems.data || !top) return null;
  const critical = top.severity === "critical";
  const { subject, headline, measure } = splitTitle(top.title);
  return (
    <section aria-label="Priority one" className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))] gap-4">
      <div
        className={cn(
          "relative flex flex-col gap-4 overflow-hidden rounded-2xl border bg-card p-6",
          critical ? "border-critical-border" : "border-warning-border",
        )}
      >
        <span aria-hidden className={cn("absolute inset-y-0 left-0 w-1", critical ? "bg-critical" : "bg-warning")} />
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-xs font-bold tracking-[0.08em] uppercase",
              critical ? "bg-critical text-critical-foreground" : "bg-warning text-warning-foreground",
            )}
          >
            <TriangleAlert className="size-3.5" aria-hidden />
            Priority one · tier {top.tier}
          </span>
          <SeverityBadge severity={top.severity} />
          {top.root_cause ? (
            <span className="rounded-full border border-border-strong px-2.5 py-0.5 text-xs font-medium text-foreground-2">
              Root cause · {CAUSE_LABEL[top.root_cause]}
            </span>
          ) : null}
        </div>
        <div className="flex flex-col gap-1.5">
          {subject ? <span className="font-mono text-[13px] text-muted-foreground">{subject}</span> : null}
          <div className="flex flex-wrap items-baseline gap-x-[18px] gap-y-1">
            <h2 className="text-2xl leading-tight font-semibold text-pretty">{headline}</h2>
            {measure ? (
              <span
                className={cn(
                  "font-mono text-[34px] leading-none font-semibold tabular-nums",
                  critical ? "text-critical" : "text-warning-ink",
                )}
              >
                {measure}
              </span>
            ) : null}
          </div>
        </div>
        <p className="max-w-[680px] text-body leading-relaxed text-foreground-2 text-pretty">{top.explanation}</p>
        <div className="flex flex-col gap-1 rounded-[10px] border border-primary/30 bg-primary/8 px-3.5 py-3">
          <span className="text-[11px] font-semibold tracking-[0.12em] text-primary-ink uppercase">Recommended</span>
          <span className="text-sm leading-normal">{top.recommended_action}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button asChild>
            <Link href={simulatorHref(top, top.member_alert_ids[0])}>
              Simulate rescue options <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
          <span className="text-caption text-muted-foreground">
            {top.member_alert_ids.length} linked alert{top.member_alert_ids.length === 1 ? "" : "s"} · fingerprint{" "}
            <span className="font-mono">{top.fingerprint.slice(0, 8)}…</span>
          </span>
        </div>
      </div>
      {deadline ? <DeadlineCard item={deadline} /> : null}
    </section>
  );
}

const SUB = "text-micro leading-tight tracking-[0.06em] text-muted-foreground uppercase";

/** Countdown to the latest moment a rescue can start, on the simulation clock. */
export function DeadlineCard({ item, compact }: { item: LastSafeMoment; compact?: boolean }) {
  const phase = PHASE[item.phase];
  const urgent = phase.tone === "critical";
  const noCandidate = item.phase === "no_candidate";
  const best = item.candidates.find((c) => c.physician_id === item.best_physician_id);
  const tz = item.timezone;
  const zone = zoneAbbr(item.shortfall_at, tz);
  const rem = item.remaining_minutes;
  const shortIn = Math.max(item.minutes_until_shortfall, 1);
  const frac = rem === null ? 0 : Math.min(1, Math.max(0, rem / shortIn));
  const remText = rem === null ? "—" : rem <= 0 ? "Missed" : fmtMin(rem);
  return (
    <div
      className={cn(
        "flex h-full min-w-0 flex-col gap-3 rounded-[14px] border p-[18px]",
        urgent ? "border-critical-border bg-critical/7 ring-[3px] ring-critical/8" : "bg-card",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <p className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          Last safe moment · <span className="text-foreground">{item.hospital_name}</span>
        </p>
        <PhasePill tone={phase.tone} label={phase.label} pulse={urgent} />
      </div>
      {noCandidate ? (
        <p className="text-sm leading-normal">
          No off-shift physician passes all eligibility rules for {item.hospital_name}. Shortfall at{" "}
          <span className="font-mono">
            {formatHm(item.shortfall_at, tz)} {zone}
          </span>{" "}
          (projected).
        </p>
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(96px,1fr))] gap-3">
            <Figure label="Shortfall at" value={formatHm(item.shortfall_at, tz)} sub={`${zone} · projected`} />
            <Figure
              label="Start rescue by"
              value={item.latest_initiation_at ? formatHm(item.latest_initiation_at, tz) : "—"}
              sub={zone}
              valueClassName="text-primary-ink"
            />
            <Figure
              label="Remaining"
              value={remText}
              sub="sim clock"
              valueClassName={rem !== null && rem < 10 ? "text-critical" : undefined}
            />
          </div>
          <div>
            <div
              role="img"
              aria-label={`Timeline: ${remText} until start-by, shortfall projected at ${formatHm(item.shortfall_at, tz)} ${zone}`}
              className="relative h-[30px]"
            >
              <div className="absolute inset-x-0 top-[11px] h-2 overflow-hidden rounded-full bg-border">
                <div
                  className={cn(
                    "absolute inset-y-0 left-0 rounded-full transition-[width] duration-600",
                    phase.tone === "critical" ? "bg-critical/85" : phase.tone === "warning" ? "bg-warning/85" : "bg-success/85",
                  )}
                  style={{ width: `${frac * 100}%` }}
                />
              </div>
              <span
                aria-hidden
                className="absolute top-0 h-[30px] w-0.5 bg-primary-ink transition-[left] duration-600"
                style={{ left: `calc(${frac * 100}% - 1px)` }}
              />
              <span aria-hidden className="absolute top-1 left-0 h-[22px] w-0.5 bg-foreground" />
              <span aria-hidden className="absolute top-1 right-0 h-[22px] w-0.5 bg-critical" />
            </div>
            <div className="-mt-1 flex justify-between text-micro tracking-[0.04em] text-muted-foreground uppercase">
              <span>Now</span>
              <span>Start by</span>
              <span>Short</span>
            </div>
          </div>
          {best ? (
            <p className="text-[13px] leading-relaxed text-foreground-2 text-pretty">
              Best candidate {best.display_name}: lead {best.lead.conservative_total_minutes} min (approval{" "}
              {best.lead.approval_minutes} + reply ≤ {best.lead.response_minutes_conservative} + online{" "}
              {best.lead.online_minutes}); expected online{" "}
              {best.activation_expected_at ? `${formatHm(best.activation_expected_at, tz)} ${zone}` : "—"} if started
              now.
            </p>
          ) : (
            <p className="text-[13px] text-critical-ink">{item.mitigation[0] ?? item.explanation}</p>
          )}
        </>
      )}
      {!compact && item.mitigation.length ? (
        <ul className="flex list-disc flex-col gap-0.5 pl-[18px] text-caption leading-snug text-foreground-2">
          {item.mitigation.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ) : null}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2.5 pt-1">
        <span className="text-[11px] text-muted-foreground">
          Simulation clock · planning deadline, not a guarantee of safety
        </span>
        <Button asChild size="sm" variant="secondary">
          <Link href={simulatorHref({ hospital_id: item.hospital_id })}>
            {noCandidate ? "Escalate to clinical lead" : "Open rescue proposal"} <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Button>
      </div>
    </div>
  );
}

function Figure({
  label,
  value,
  sub,
  valueClassName,
}: {
  label: string;
  value: string;
  sub: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-label whitespace-nowrap text-muted-foreground">{label}</span>
      <span className={cn("font-mono text-lg font-semibold whitespace-nowrap tabular-nums", valueClassName)}>{value}</span>
      <span className={SUB}>{sub}</span>
    </div>
  );
}

const DOT: Record<Tone, string> = {
  critical: "bg-critical",
  serious: "bg-serious",
  warning: "bg-warning",
  success: "bg-success",
  info: "bg-info",
  muted: "bg-faint-foreground",
  primary: "bg-primary",
};

export function PhasePill({ tone, label, pulse }: { tone: Tone; label: string; pulse?: boolean }) {
  return (
    <Pill tone={tone} className="gap-1.5 px-2.5 text-xs font-semibold">
      <span aria-hidden className={cn("size-[7px] rounded-full", DOT[tone], pulse && "animate-ng-pulse")} />
      {label}
    </Pill>
  );
}

export function LastSafeMomentStrip({ className, timeMachineLink = true }: { className?: string; timeMachineLink?: boolean }) {
  const lsm = useLiveResource((s) => neurogridApi.lastSafeMoment(s));
  return (
    <section aria-labelledby="lsm-heading" className={cn("flex flex-col gap-3", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="lsm-heading" className="text-lg font-semibold">
          Last safe moment{" "}
          <span className="text-sm font-normal text-muted-foreground">· hospitals with a projected shortfall</span>
        </h2>
        {timeMachineLink ? (
          <Link href="/time-machine" className="text-[13px] text-primary-ink hover:underline">
            Open Time Machine →
          </Link>
        ) : null}
      </div>
      <Gate resource={lsm} feature="the last-safe-moment engine">
        {(r: LastSafeMomentReport) =>
          r.items.length === 0 ? (
            <p className="rounded-[14px] border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
              No projected shortfall in the next {r.planning_horizon_minutes} min. Nothing to schedule.
            </p>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,340px),1fr))] gap-3">
              {r.items.map((i) => (
                <DeadlineCard key={i.shortfall_id} item={i} compact />
              ))}
            </div>
          )
        }
      </Gate>
    </section>
  );
}

function ProblemRow({ g }: { g: ProblemGroup }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-border-subtle last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="grid w-full grid-cols-[32px_minmax(0,1fr)_20px] items-start gap-3 px-[18px] py-3.5 text-left transition-colors hover:bg-hover"
      >
        <span className="font-mono text-lg font-semibold text-muted-foreground tabular-nums">{g.priority}</span>
        <span className="flex min-w-0 flex-col gap-[7px]">
          <span className="flex flex-wrap gap-1.5">
            <SeverityBadge severity={g.severity} />
            <span className="rounded-sm bg-selected px-2 py-0.5 text-label font-medium text-foreground-2">Tier {g.tier}</span>
            {g.root_cause ? (
              <span className="rounded-sm border border-border-strong px-2 py-0.5 text-label text-foreground-2">
                {CAUSE_LABEL[g.root_cause]}
              </span>
            ) : null}
            {g.member_alert_ids.length > 1 ? (
              <span className="px-2 py-0.5 text-label text-muted-foreground">{g.member_alert_ids.length} linked alerts</span>
            ) : null}
          </span>
          <span className="text-[14.5px] font-semibold">{g.title}</span>
          <span className="text-[13px] leading-snug text-muted-foreground">{g.summary}</span>
        </span>
        <ChevronRight
          className={cn("mt-1 size-5 text-muted-foreground transition-transform duration-200", open && "rotate-90")}
          aria-hidden
        />
      </button>
      {open ? (
        <div className="flex flex-col gap-2.5 pr-[18px] pb-4 pl-[62px] text-[13px] leading-relaxed">
          <p className="text-foreground-2">{g.explanation}</p>
          <p>
            <span className="font-semibold text-primary-ink">Action · </span>
            {g.recommended_action}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {g.member_alert_ids.map((a) => (
              <Pill
                key={a}
                tone={g.critical_alert_ids.includes(a) ? "critical" : "muted"}
                className="rounded-sm font-mono"
              >
                {a}
              </Pill>
            ))}
          </div>
          <pre className="overflow-x-auto rounded-lg bg-inset px-3 py-2.5 font-mono text-label text-foreground-2">
            {JSON.stringify(g.factors, null, 2)}
          </pre>
          <div className="flex flex-wrap items-center justify-between gap-2.5">
            <span className="font-mono text-label text-faint-foreground">
              fp {g.fingerprint} · stable while the issue persists
            </span>
            {g.hospital_id ? (
              <Button asChild size="sm" variant="secondary">
                <Link href={simulatorHref(g, g.member_alert_ids[0])}>
                  Compare interventions <ArrowRight className="size-4" aria-hidden />
                </Link>
              </Button>
            ) : null}
          </div>
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
      description="Alerts grouped by underlying problem (deterministic fingerprint), ordered by tier, then a transparent tie-breaker. Every critical alert stays listed."
      contentClassName="p-0"
    >
      <Gate resource={problems} feature="problem ranking">
        {(r) => (
          <>
            <ol>
              {r.groups.map((g) => (
                <ProblemRow key={g.fingerprint} g={g} />
              ))}
            </ol>
            <details className="border-t border-border-subtle px-[18px] py-3 text-caption text-muted-foreground">
              <summary className="cursor-pointer">
                {r.groups.length} problems from {r.alerts_total} alerts · tier policy
              </summary>
              <ul className="mt-1 list-disc pl-4">
                {r.tier_policy.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            </details>
          </>
        )}
      </Gate>
    </SectionCard>
  );
}

const EVIDENCE_CLASS = {
  CONFIRMED: "border-success-border text-success-ink",
  LIKELY: "border-info-border text-info-ink",
  UNCERTAIN: "border-warning-border text-warning-ink",
  STALE: "border-warning-border text-warning-ink",
} as const;

export function AvailabilityBoard({ className }: { className?: string }) {
  const res = useLiveResource((s) => neurogridApi.availability(s));
  return (
    <SectionCard
      className={className}
      title="Availability intelligence"
      description="On-shift physicians, inferred from system signals, with the rule that decided each class. Evidence labels are categories, not probabilities."
      contentClassName="p-0"
    >
      <Gate resource={res} feature="availability classification">
        {(r) => (
          <ul>
            {r.physicians
              .filter((p) => p.on_shift)
              .map((p) => (
                <li key={p.physician_id} className="flex flex-col gap-[7px] border-b border-border-subtle px-[18px] py-[13px] last:border-b-0">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{p.display_name}</span>
                    <Pill tone={CLASS_TONE[p.availability_class]}>{CLASS_LABEL[p.availability_class]}</Pill>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <span
                      title="Evidence label — not a calibrated probability"
                      className={cn(
                        "rounded-sm border px-[7px] py-px text-label capitalize",
                        EVIDENCE_CLASS[p.confidence],
                      )}
                    >
                      {p.confidence.toLowerCase()}
                    </span>
                    <span
                      className={cn(
                        "rounded-sm border border-border-strong px-[7px] py-px text-label",
                        p.auto_routable ? "text-primary-ink" : "text-muted-foreground",
                      )}
                    >
                      {p.auto_routable ? "✓ auto-routable" : "✕ not routable"}
                    </span>
                    {p.needs_confirmation ? (
                      <span className="rounded-sm border border-warning-border bg-warning-soft px-[7px] py-px text-label text-warning-ink">
                        ⚠ confirm
                      </span>
                    ) : null}
                    {p.unfinished_note_consult_ids.length ? (
                      <span className="px-[7px] py-px text-label text-muted-foreground">
                        {p.unfinished_note_consult_ids.length} open note{p.unfinished_note_consult_ids.length === 1 ? "" : "s"}
                      </span>
                    ) : null}
                  </div>
                  <span className="font-mono text-label text-muted-foreground">
                    {p.decision_rule}: {p.rationale[0]}
                    {p.routing_exclusions.length ? ` · excluded: ${p.routing_exclusions.join("; ")}` : ""}
                  </span>
                </li>
              ))}
          </ul>
        )}
      </Gate>
    </SectionCard>
  );
}
