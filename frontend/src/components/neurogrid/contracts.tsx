"use client";

import { BadgeCheck, ClipboardCheck, History, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { AuditTrail } from "@/components/workflow/audit-trail";
import { useWorkflow } from "@/components/workflow/workflow-provider";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { useLiveResource } from "@/hooks/use-live-resource";
import { describeError } from "@/lib/api/errors";
import { formatTime } from "@/lib/format";
import { neurogridApi, type ContractVerification } from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import { ContractPhaseBadge, Gate, KeyValue, Pill, fmtPm } from "./kit";

const ET = "America/New_York";

const VERDICT_TONE = {
  resolved: "success",
  partially_resolved: "warning",
  failed: "critical",
  pending: "info",
  not_applicable: "muted",
} as const;

function VerificationView({ v }: { v: ContractVerification }) {
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <ContractPhaseBadge phase={v.contract_phase} />
        <Pill tone={VERDICT_TONE[v.verdict]}>verdict: {v.verdict.replace("_", " ")}</Pill>
        <span className="text-xs text-muted-foreground">
          checked {formatTime(v.checked_at, ET)} · data v{v.data_version}
        </span>
      </div>
      <p>
        <span className="font-medium">Success condition: </span>
        {v.success_condition}
      </p>
      {v.target_deficit_physician_minutes !== null ? (
        <div className="grid grid-cols-2 gap-2">
          <KeyValue label="Target deficit with rescue" value={fmtPm(v.target_deficit_physician_minutes)} hint="recomputed now" />
          <KeyValue label="Same interval without it" value={fmtPm(v.baseline_deficit_physician_minutes)} hint="rescue physician removed" />
        </div>
      ) : null}
      <ul className="list-disc space-y-0.5 pl-4 text-xs">
        {v.findings.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
      {v.next_steps.length ? (
        <div className="rounded-md border border-warning-border bg-warning-soft px-3 py-2 text-xs text-warning">
          {v.next_steps.join(" ")}
        </div>
      ) : null}
    </div>
  );
}

/** NEUROGRID contract phase + recovery verification for the selected intervention. */
export function ContractVerificationPanel({ className }: { className?: string }) {
  const { selectedId, interventions, versionKey } = useWorkflow();
  const phases = useLiveResource((s) => neurogridApi.contractPhases("coordinator", s));
  const id = selectedId ?? interventions.data?.items[0]?.id ?? null;
  const verification = useKeyedResource(id && versionKey ? `${id}|${versionKey}` : null, (s) =>
    neurogridApi.verification(id!, "coordinator", s),
  );
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function verify() {
    if (!id) return;
    setBusy(true);
    setMsg(null);
    try {
      const v = await neurogridApi.verify(id);
      setMsg(`Recorded in the audit log: ${v.verdict.replace("_", " ")} (${v.contract_phase.toLowerCase()}).`);
      verification.reload();
    } catch (e) {
      setMsg(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      className={className}
      title="Contract phase & recovery verification"
      icon={ClipboardCheck}
      description="Acceptance is not activation, and activation is not recovery. Verification recomputes coverage at the target hospitals over the rescue interval from current state."
      action={
        <Button size="sm" onClick={verify} disabled={!id || busy}>
          {busy ? <RefreshCw className="size-4 animate-spin" aria-hidden /> : <BadgeCheck className="size-4" aria-hidden />}
          Verify &amp; record
        </Button>
      }
    >
      <div className="space-y-4">
        {phases.data && interventions.data ? (
          <ul className="flex flex-wrap gap-2" aria-label="Contract phases">
            {interventions.data.items.map((i) => (
              <li key={i.id} className={cn("flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs", i.id === id && "border-primary")}>
                <span className="font-medium">{i.id}</span>
                <ContractPhaseBadge phase={phases.data?.[i.id] ?? i.status.toUpperCase()} />
              </li>
            ))}
          </ul>
        ) : null}
        {msg ? <p role="status" className="text-sm text-primary">{msg}</p> : null}
        {!id ? (
          <p className="text-sm text-muted-foreground">No rescue contract yet. Create one from the Rescue Simulator or the composer below.</p>
        ) : (
          <Gate resource={verification} feature="contract verification">
            {(v) => <VerificationView v={v} />}
          </Gate>
        )}
      </div>
    </SectionCard>
  );
}

/** Network-wide audit log: every consequential decision, who made it and on which data. */
export function ContractAudit({ className }: { className?: string }) {
  const { versionKey } = useWorkflow();
  return (
    <SectionCard
      className={className}
      title="Audit log"
      icon={History}
      description="Append-only: proposals, approvals with re-validation, offers, responses, expiries, activation and verification, each with actor, role, simulation time and data version."
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
  return (
    <section
      aria-label="Decision freshness"
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        stale.length ? "border-warning-border bg-warning-soft text-warning" : "border-success-border bg-success-soft text-success",
        className,
      )}
    >
      <p className="flex items-center gap-2 font-semibold">
        <ShieldCheck className="size-4" aria-hidden />
        Decision freshness lock
      </p>
      {stale.length ? (
        <p className="mt-1">
          {stale.map((i) => `${i.id} (proposed on data v${i.created_data_version})`).join(", ")}: the operational state has
          changed since proposal (now v{config.data_version}). Approving re-checks eligibility, rest and weekly hours, offer
          limits, shift conflicts and whether the gap still exists; a stale or invalid plan is blocked and returned for review.
        </p>
      ) : (
        <p className="mt-1">Every pending decision was proposed on the current data version (v{config.data_version}).</p>
      )}
    </section>
  );
}
