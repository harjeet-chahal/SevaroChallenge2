"use client";

import { BadgeCheck, CircleCheck, RefreshCw, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { AuditTrail } from "@/components/workflow/audit-trail";
import { useWorkflow } from "@/components/workflow/workflow-provider";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { useLiveResource } from "@/hooks/use-live-resource";
import { describeError } from "@/lib/api/errors";
import { formatHm, zoneAbbr } from "@/lib/format";
import { neurogridApi, type ContractVerification } from "@/lib/api/neurogrid";
import type { Intervention } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { Pill, fmtPm, type Tone } from "./kit";

const ET = "America/New_York";

const VERDICT_TONE: Record<ContractVerification["verdict"], Tone> = {
  resolved: "success",
  partially_resolved: "warning",
  failed: "critical",
  pending: "info",
  not_applicable: "muted",
};

const STEPS = [
  "Proposed",
  "Awaiting approval",
  "Ready to dispatch",
  "Response pending",
  "Activation pending",
  "Active",
  "Verified",
] as const;

/**
 * Where a contract phase sits on the 7-step lifecycle. Side exits (rejected, expired,
 * cancelled, escalated, declined) end the stepper early with a terminal pill.
 */
function position(phase: string, verdict: ContractVerification["verdict"] | undefined) {
  switch (phase) {
    case "PROPOSED":
      return { at: 0 };
    case "AWAITING_APPROVAL":
      return { at: 1 };
    case "REVALIDATION_REQUIRED":
      return { at: 1, warn: true };
    case "READY_TO_DISPATCH":
      return { at: 2 };
    case "RESPONSE_PENDING":
      return { at: 3 };
    case "ACTIVATION_PENDING":
      return { at: 4 };
    case "ACTIVE":
    case "VERIFYING":
      return { at: 5 };
    case "RESOLVED":
      return { at: 6, done: true };
    case "PARTIALLY_RESOLVED":
      return { at: 6, warn: true };
    case "FAILED":
      return verdict === "failed" ? { at: 6, fail: true } : { at: 3, exit: "Declined" };
    case "REJECTED":
      return { at: 1, exit: "Rejected" };
    case "ESCALATED":
      return { at: 2, exit: "Escalated" };
    case "EXPIRED":
      return { at: 3, exit: "Expired" };
    case "CANCELLED":
      return { at: 1, exit: "Cancelled" };
    default:
      return { at: 0 };
  }
}

const VERIFIABLE = new Set(["ACTIVE", "VERIFYING", "RESOLVED", "PARTIALLY_RESOLVED", "FAILED"]);

function PhaseStepper({ phase, verdict }: { phase: string; verdict?: ContractVerification["verdict"] }) {
  const p = position(phase, verdict);
  const shown = p.exit ? STEPS.slice(0, p.at + 1) : STEPS;
  return (
    <ol aria-label={`Contract phase: ${phase.replaceAll("_", " ").toLowerCase()}`} className="flex flex-wrap items-end gap-1">
      {shown.map((name, i) => {
        const current = i === p.at;
        const reached = i <= p.at;
        return (
          <li key={name} aria-current={current ? "step" : undefined} className="flex min-w-[84px] flex-1 flex-col gap-1.5">
            <span
              aria-hidden
              className={cn(
                "h-[5px] rounded-full",
                !reached && "bg-border",
                reached && !current && "bg-primary",
                current && (p.fail ? "bg-critical" : p.warn ? "bg-warning" : p.done ? "bg-success" : "animate-ng-pulse bg-primary/60"),
              )}
            />
            <span
              className={cn(
                "text-micro tracking-[0.05em] uppercase",
                current ? "font-bold text-foreground" : reached ? "font-medium text-foreground-2" : "text-faint-foreground",
              )}
            >
              {i === 6 && current ? phase.replaceAll("_", " ").toLowerCase() : name}
            </span>
          </li>
        );
      })}
      {p.exit ? (
        <li className="flex flex-1 items-end pb-0.5">
          <Pill tone={p.exit === "Escalated" ? "warning" : "muted"}>{p.exit} · contract closed</Pill>
        </li>
      ) : null}
    </ol>
  );
}

function verdictText(v: ContractVerification): string {
  const pm = (n: number | null) => (n === null ? "—" : `${Math.round(n)}`);
  switch (v.verdict) {
    case "resolved":
      return `Resolved: target deficit ${pm(v.target_deficit_physician_minutes)} vs ${pm(v.baseline_deficit_physician_minutes)} without the rescue`;
    case "partially_resolved":
      return `Partially resolved: ${pm(v.target_deficit_physician_minutes)} vs ${pm(v.baseline_deficit_physician_minutes)} without the rescue`;
    case "failed":
      return "Failed: no improvement over the same interval without the rescue";
    case "pending":
      return "Pending · not yet online, nothing to verify";
    default:
      return "Not a coverage rescue";
  }
}

function ContractCard({ intervention, phase }: { intervention: Intervention; phase: string }) {
  const { versionKey } = useWorkflow();
  const verification = useKeyedResource(versionKey ? `${intervention.id}|${versionKey}` : null, (s) =>
    neurogridApi.verification(intervention.id, "coordinator", s),
  );
  const v = verification.data;
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function verify() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await neurogridApi.verify(intervention.id);
      setMsg(`Recorded in the audit log: ${r.verdict.replace("_", " ")} (${r.contract_phase.toLowerCase()}).`);
      verification.reload();
    } catch (e) {
      setMsg(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-col gap-4 rounded-2xl border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="font-mono text-xs text-muted-foreground">{intervention.id}</span>
          <span className="text-[17px] font-semibold">{intervention.title}</span>
        </div>
        {v ? (
          <Pill tone={VERDICT_TONE[v.verdict]} className="rounded-lg px-2.5 py-1 text-caption font-semibold whitespace-normal">
            {verdictText(v)}
          </Pill>
        ) : null}
      </div>
      <PhaseStepper phase={phase} verdict={v?.verdict} />
      {v ? (
        <div className="flex flex-col gap-2 text-[13px] text-foreground-2">
          <p>
            <span className="font-medium text-foreground">Success condition · </span>
            {v.success_condition}
          </p>
          {v.target_deficit_physician_minutes !== null ? (
            <p className="font-mono text-xs text-muted-foreground">
              with rescue {fmtPm(v.target_deficit_physician_minutes)} · without {fmtPm(v.baseline_deficit_physician_minutes)}
              {v.interval_start ? ` · interval from ${formatHm(v.interval_start, ET)} ${zoneAbbr(v.interval_start, ET)}` : ""}
            </p>
          ) : null}
          {v.findings.length ? (
            <ul className="list-disc space-y-0.5 pl-4 text-xs">
              {v.findings.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : null}
          {v.next_steps.length ? (
            <p className="rounded-lg border border-warning-border bg-warning-soft px-3 py-2 text-xs text-warning-ink">
              {v.next_steps.join(" ")}
            </p>
          ) : null}
        </div>
      ) : null}
      {msg || VERIFIABLE.has(phase) ? (
        <div className="flex flex-wrap items-center justify-between gap-2.5">
          {msg ? (
            <p role="status" className="text-[13px] text-primary-ink">
              {msg}
            </p>
          ) : (
            <span className="text-[13px] text-muted-foreground">
              Checked {v ? `${formatHm(v.checked_at, ET)} ${zoneAbbr(v.checked_at, ET)} · data v${v.data_version}` : "—"}
            </span>
          )}
          {VERIFIABLE.has(phase) ? (
            <Button size="sm" onClick={verify} disabled={busy}>
              {busy ? <RefreshCw className="size-4 animate-spin" aria-hidden /> : <BadgeCheck className="size-4" aria-hidden />}
              Verify &amp; record
            </Button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/** Every rescue contract with its lifecycle phase and recovery verification. */
export function ContractVerificationPanel({ className }: { className?: string }) {
  const { interventions } = useWorkflow();
  const phases = useLiveResource((s) => neurogridApi.contractPhases("coordinator", s));
  const items = interventions.data?.items ?? [];
  return (
    <section aria-label="Rescue contracts" className={cn("flex flex-col gap-3", className)}>
      {items.length === 0 ? (
        <p className="rounded-[14px] border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
          No rescue contract yet. Create one from the Rescue Simulator or the composer below.
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((i) => (
            <ContractCard key={i.id} intervention={i} phase={phases.data?.[i.id] ?? i.status.toUpperCase()} />
          ))}
        </ul>
      )}
    </section>
  );
}

/** Network-wide audit log: every consequential decision, who made it and on which data. */
export function ContractAudit({ className }: { className?: string }) {
  const { versionKey } = useWorkflow();
  return (
    <SectionCard
      className={className}
      title="Contract audit"
      description="Immutable and append-only: proposals, approvals with re-validation, offers, responses, expiries, activation and verification — with actor, role, simulation time and data version."
    >
      <AuditTrail role="coordinator" versionKey={versionKey} limit={200} />
    </SectionCard>
  );
}

/** Decision Freshness Lock, as the clinical lead sees it: which pending decisions were
 * proposed on older data and will be re-validated (and blocked if stale) on approval. */
export function FreshnessLockBanner({ className }: { className?: string }) {
  const { interventions } = useWorkflow();
  const { config } = useSystemStatus();
  const pending = (interventions.data?.items ?? []).filter((i) => i.status === "pending_approval" || i.status === "approved");
  if (!config || !pending.length) return null;
  const stale = pending.filter((i) => i.created_data_version !== config.data_version);
  const Icon = stale.length ? TriangleAlert : CircleCheck;
  return (
    <section
      aria-label="Decision freshness"
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3",
        stale.length ? "border-warning-border bg-warning-soft" : "border-success-border bg-success-soft",
        className,
      )}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", stale.length ? "text-warning-ink" : "text-success-ink")} aria-hidden />
      <div className="flex flex-col gap-0.5">
        <p className={cn("text-sm font-semibold", stale.length ? "text-warning-ink" : "text-success-ink")}>
          {stale.length
            ? "State changed since this plan was made — it will be re-validated on approval"
            : "Data unchanged since proposal"}
        </p>
        <p className="text-caption text-foreground-2">
          {stale.length ? (
            <>
              {stale.map((i) => `${i.id} (proposed on data v${i.created_data_version})`).join(", ")}: the operational
              state has changed since proposal (now v{config.data_version}). Approving re-checks eligibility, rest and
              weekly hours, offer limits, shift conflicts and whether the gap still exists; a stale or invalid plan is
              blocked and returned for review.
            </>
          ) : (
            <>Every pending decision was proposed on the current data version (v{config.data_version}).</>
          )}
        </p>
      </div>
    </section>
  );
}
