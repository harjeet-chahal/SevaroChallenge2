"use client";

import { Check, ClipboardCheck, FileSearch, History, Loader2, Send, X } from "lucide-react";
import { useState } from "react";

import { DataEmptyState } from "@/components/shared/data-empty-state";
import { EmptyState } from "@/components/shared/empty-state";
import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { TagBadge } from "@/components/shared/status-badges";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AuditTrail } from "@/components/workflow/audit-trail";
import { Feedback } from "@/components/workflow/feedback";
import { InterventionDetailView, OfferRows } from "@/components/workflow/intervention-detail";
import { InterventionStatusBadge, InterventionTypeBadge } from "@/components/workflow/status";
import { sentOffersFeedback, useAction } from "@/components/workflow/use-action";
import { useWorkflow } from "@/components/workflow/workflow-provider";
import { workflowApi } from "@/lib/api/endpoints";
import type { Intervention } from "@/lib/api/types";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

function usePending(): Intervention[] {
  const { interventions } = useWorkflow();
  return (interventions.data?.items ?? []).filter((i) => i.status === "pending_approval");
}

function Waiting({ feature }: { feature: string }) {
  const { config } = useSystemStatus();
  const { interventions } = useWorkflow();
  if (!config?.dataset_loaded) {
    return (
      <DataEmptyState
        feature={feature}
        whenNoDataset="Nothing to review. Proposals appear here once coordinators submit them."
      />
    );
  }
  if (interventions.error) return <p className="text-sm text-critical-ink">{interventions.error}</p>;
  return <p className="text-sm text-muted-foreground">Loading…</p>;
}

export function PendingApprovals({ className }: { className?: string }) {
  const { interventions, selectedId, select } = useWorkflow();
  const pending = usePending();
  return (
    <SectionCard
      className={className}
      title="Pending approvals"
      icon={ClipboardCheck}
      info="Interventions proposed by coordinators, waiting for your decision. No physician is contacted before you approve."
      action={pending.length ? <TagBadge tone="warning">{pending.length} waiting</TagBadge> : null}
    >
      {!interventions.data ? (
        <Waiting feature="intervention workflow" />
      ) : pending.length === 0 ? (
        <EmptyState
          compact
          icon={ClipboardCheck}
          title="Nothing waiting"
          description="New proposals appear here automatically."
        />
      ) : (
        <ul className="space-y-2" aria-label="Pending approvals">
          {pending.map((i) => (
            <li key={i.id}>
              <button
                type="button"
                onClick={() => select(i.id)}
                aria-current={selectedId === i.id}
                className={cn(
                  "w-full space-y-1 rounded-lg border p-3 text-left text-sm outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50",
                  selectedId === i.id && "border-primary bg-primary/5",
                )}
              >
                <span className="flex flex-wrap items-center gap-1.5">
                  {i.problem.severity ? <SeverityBadge severity={i.problem.severity} /> : null}
                  <InterventionTypeBadge type={i.type} />
                  <span className="font-mono text-xs text-muted-foreground">{i.id}</span>
                </span>
                <span className="block font-semibold text-foreground">{i.title}</span>
                <span className="block text-xs text-muted-foreground">
                  {i.problem.title} · proposed {formatTime(i.proposed_at, i.problem.hospital_timezone)}{" "}
                  by {i.proposed_by.actor_id}
                </span>
                <span className="block text-xs">{i.recommendation.summary}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function DecisionPanel({ i }: { i: Intervention }) {
  const [note, setNote] = useState("");
  const { pending, feedback, run } = useAction();
  // Keep this intervention in view after deciding, so the outcome and next step stay visible.
  const { select } = useWorkflow();
  const canDecide = i.allowed_actions.includes("approve");
  const canSend = i.allowed_actions.includes("send_offers");
  return (
    <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
      {canDecide ? (
        <>
          <label htmlFor="decision-note" className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
            Note (optional; recorded in the audit trail)
          </label>
          <Textarea
            id="decision-note"
            value={note}
            maxLength={2000}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. why you reject, or conditions for approval"
          />
          <p className="text-xs text-muted-foreground">
            Approving re-checks eligibility, offer limits and the remaining coverage need against
            the current data first. It does not contact anyone; offers are sent as a separate step.
          </p>
        </>
      ) : null}
      <Feedback feedback={feedback} />
      <div className="flex flex-wrap justify-end gap-2">
        {canDecide ? (
          <>
            <Button
              variant="outline"
              disabled={pending !== null}
              onClick={() =>
                run("reject", async () => {
                  select(i.id);
                  await workflowApi.decide(i.id, "reject", note, i.version);
                  setNote("");
                  return `${i.id} rejected${note ? " with your note" : ""}.`;
                })
              }
            >
              {pending === "reject" ? <Loader2 className="animate-spin" aria-hidden /> : <X aria-hidden />}
              Reject
            </Button>
            <Button
              disabled={pending !== null}
              onClick={() =>
                run("approve", async () => {
                  select(i.id);
                  const approved = await workflowApi.decide(i.id, "approve", note, i.version);
                  setNote("");
                  return approved.type === "split_shift"
                    ? `${i.id} approved after revalidation. Send the offer when ready (simulated).`
                    : `${i.id} approved (escalation authorized).`;
                })
              }
            >
              {pending === "approve" ? <Loader2 className="animate-spin" aria-hidden /> : <Check aria-hidden />}
              Approve
            </Button>
          </>
        ) : null}
        {canSend ? (
          <Button
            disabled={pending !== null}
            onClick={() =>
              run("send", async () => {
                const sent = await workflowApi.sendOffers(i.id, "clinical_lead");
                return sentOffersFeedback(sent, "(simulated; nothing leaves the system).");
              })
            }
          >
            {pending === "send" ? <Loader2 className="animate-spin" aria-hidden /> : <Send aria-hidden />}
            Send approved offer (simulated)
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function InterventionDetail({ className }: { className?: string }) {
  const { interventions, selectedId } = useWorkflow();
  const pending = usePending();
  const items = interventions.data?.items ?? [];
  const selected = items.find((i) => i.id === selectedId) ?? pending[0] ?? null;
  return (
    <SectionCard
      className={className}
      title="Intervention detail"
      icon={FileSearch}
      info="The source problem, urgency, proposed action, candidate physicians and the rule each passed or failed, risks, alternatives and projected impact."
    >
      {!interventions.data ? (
        <Waiting feature="intervention workflow" />
      ) : !selected ? (
        <EmptyState
          icon={FileSearch}
          title="No proposal selected"
          description="Select a pending approval to review it before deciding."
        />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-sm">{selected.id}</span>
            <InterventionTypeBadge type={selected.type} />
            <InterventionStatusBadge status={selected.status} />
          </div>
          {/* Keyed: a note, result or spinner never carries over to another intervention. */}
          <DecisionPanel key={selected.id} i={selected} />
          {selected.offers.length ? (
            <OfferRows offers={selected.offers} tz={selected.problem.hospital_timezone} />
          ) : null}
          <InterventionDetailView intervention={selected} />
        </div>
      )}
    </SectionCard>
  );
}

export function ApprovalHistory({ className }: { className?: string }) {
  const { interventions, select, versionKey, role } = useWorkflow();
  const decided = (interventions.data?.items ?? []).filter(
    (i) => i.status !== "pending_approval" && i.type !== "reassign_consult",
  );
  return (
    <SectionCard
      className={className}
      title="Approval history"
      icon={History}
      info="Past decisions with who decided and when, and what happened to each offer."
    >
      {!interventions.data ? (
        <Waiting feature="audit log" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {decided.length ? (
            <ul className="space-y-2">
              {decided.map((i) => (
                <li key={i.id} className="space-y-1 rounded-lg border p-3 text-sm">
                  <button
                    type="button"
                    onClick={() => select(i.id)}
                    className="flex flex-wrap items-center gap-1.5 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  >
                    <span className="font-mono text-xs">{i.id}</span>
                    <InterventionStatusBadge status={i.status} />
                    <span className="font-medium">{i.title}</span>
                  </button>
                  {i.approval ? (
                    <p className="text-xs text-muted-foreground">
                      {i.approval.decision === "approve" ? "Approved" : "Rejected"} by{" "}
                      {i.approval.decided_by.actor_id} at{" "}
                      {formatTime(i.approval.decided_at, i.problem.hospital_timezone)}
                      {i.approval.note ? ` — “${i.approval.note}”` : ""}
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">{i.status_reason ?? "No decision recorded."}</p>
                  )}
                  {i.offers.length ? (
                    <p className="text-xs">
                      Offers:{" "}
                      {i.offers.map((o) => `${o.display_name} — ${o.status}`).join("; ")}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No decisions recorded yet.</p>
          )}
          <AuditTrail role={role} versionKey={versionKey} limit={40} />
        </div>
      )}
    </SectionCard>
  );
}
