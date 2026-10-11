"use client";

import {
  Ban,
  CheckCheck,
  ListChecks,
  Loader2,
  Play,
  Power,
  Send,
  Undo2,
} from "lucide-react";

import { Disclosure } from "@/components/optimization/shared";
import { EmptyState } from "@/components/shared/empty-state";
import { SectionCard } from "@/components/shared/section-card";
import { TagBadge } from "@/components/shared/status-badges";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { offersApi, workflowApi } from "@/lib/api/endpoints";
import type { Intervention, InterventionAction, ShiftOffer } from "@/lib/api/types";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { AuditTrail } from "./audit-trail";
import { Feedback } from "./feedback";
import { ImpactView } from "./impact-view";
import { InterventionDetailView, OfferRows } from "./intervention-detail";
import { InterventionStatusBadge, InterventionTypeBadge } from "./status";
import { useAction } from "./use-action";
import { useWorkflow } from "./workflow-provider";

const NEXT_STEP: Partial<Record<Intervention["status"], string>> = {
  proposed: "Coordinator applies the reassignment.",
  pending_approval: "Waiting for the clinical lead.",
  approved: "Approved — send the offer(s) (simulated).",
  offer_sent: "Waiting for the physician's reply (expires 10 min after sending).",
  accepted: "Physician preparing to come online — not active capacity yet.",
  activated: "Physician online and routable within the approved scope.",
};

function InterventionActions({ i }: { i: Intervention }) {
  const { role } = useWorkflow();
  const { pending, feedback, run } = useAction();
  const allowed = new Set<InterventionAction>(i.allowed_actions);
  const spin = (key: string, Icon: React.ComponentType<{ className?: string }>) =>
    pending === key ? <Loader2 className="animate-spin" aria-hidden /> : <Icon aria-hidden />;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {allowed.has("send_offers") ? (
          <Button
            size="sm"
            disabled={pending !== null}
            onClick={() =>
              run("send", async () => {
                const sent = await workflowApi.sendOffers(i.id, role);
                const live = sent.offers.filter((o) => o.status === "sent");
                return `Sent ${live.length} offer(s) (simulated delivery; nothing leaves the system). They expire 10 simulated minutes after sending.`;
              })
            }
          >
            {spin("send", Send)}
            Send approved offer{i.offer_plan.length > 1 ? "s" : ""} (simulated)
          </Button>
        ) : null}
        {allowed.has("apply") ? (
          <Button
            size="sm"
            disabled={pending !== null}
            onClick={() =>
              run("apply", async () => {
                await workflowApi.apply(i.id);
                return "Reassignment re-checked and applied (recorded as a workflow event).";
              })
            }
          >
            {spin("apply", Play)}
            Apply reassignment
          </Button>
        ) : null}
        {allowed.has("resolve") ? (
          <Button
            size="sm"
            variant="outline"
            disabled={pending !== null}
            onClick={() =>
              run("resolve", async () => {
                await workflowApi.resolve(i.id, role, "Resolved by the coordinator");
                return "Escalation marked resolved.";
              })
            }
          >
            {spin("resolve", CheckCheck)}
            Mark resolved
          </Button>
        ) : null}
        {allowed.has("cancel") ? (
          <Button
            size="sm"
            variant="outline"
            disabled={pending !== null}
            onClick={() =>
              run("cancel", async () => {
                await workflowApi.cancel(i.id, role, `cancelled by the ${role.replace("_", " ")}`);
                return `${i.id} cancelled. Open offers were withdrawn and accepted shifts ended.`;
              })
            }
          >
            {spin("cancel", Ban)}
            Cancel
          </Button>
        ) : null}
      </div>
      <Feedback feedback={feedback} />
    </div>
  );
}

function OfferActions({ offer }: { offer: ShiftOffer }) {
  const { role } = useWorkflow();
  const { pending, feedback, run } = useAction();
  const allowed = new Set(offer.allowed_actions);
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex flex-wrap gap-2">
        {allowed.has("activate") && role === "coordinator" ? (
          <Button
            size="xs"
            variant="outline"
            disabled={pending !== null}
            onClick={() =>
              run("activate", async () => {
                const o = await offersApi.activate(offer.id, "coordinator");
                return `${o.display_name} marked online (simulated).`;
              })
            }
          >
            <Power aria-hidden />
            Simulate going online now
          </Button>
        ) : null}
        {allowed.has("withdraw") ? (
          <Button
            size="xs"
            variant="outline"
            disabled={pending !== null}
            onClick={() =>
              run("withdraw", async () => {
                await offersApi.withdraw(offer.id, role, null);
                return `Offer ${offer.id} withdrawn.`;
              })
            }
          >
            <Undo2 aria-hidden />
            Withdraw offer
          </Button>
        ) : null}
      </div>
      <Feedback feedback={feedback} />
    </div>
  );
}

/**
 * Every intervention for the active dataset, its offers, live impact and audit trail.
 * Buttons only appear when the backend says the coordinator may take that step now.
 */
export function InterventionBoard({ className }: { className?: string }) {
  const { role, interventions, selectedId, select, versionKey } = useWorkflow();
  const { config } = useSystemStatus();
  const items = interventions.data?.items ?? [];
  const selected = items.find((i) => i.id === selectedId) ?? items[0] ?? null;

  return (
    <section id="intervention-board" className={cn("scroll-mt-24", className)}>
      <SectionCard
        title="Interventions & audit trail"
        icon={ListChecks}
        description="Proposed, approved and active interventions, their offers and every recorded step."
        action={
          config?.pending_approvals ? (
            <TagBadge tone="warning">{config.pending_approvals} pending approval</TagBadge>
          ) : null
        }
      >
        {!config?.dataset_loaded ? (
          <EmptyState compact icon={ListChecks} title="No dataset loaded" />
        ) : interventions.error ? (
          <p className="text-sm text-critical-ink">{interventions.error}</p>
        ) : !interventions.data ? (
          <p className="text-sm text-muted-foreground">Loading interventions…</p>
        ) : items.length === 0 ? (
          <div className="space-y-3">
            <EmptyState
              compact
              icon={ListChecks}
              title="No interventions yet"
              description="Proposals appear here as soon as they are submitted."
            />
            <AuditTrail role={role} versionKey={versionKey} limit={15} />
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(16rem,22rem)_1fr]">
            <ul className="space-y-2" aria-label="Interventions">
              {items.map((i) => (
                <li key={i.id}>
                  <button
                    type="button"
                    onClick={() => select(i.id)}
                    aria-current={selected?.id === i.id}
                    className={cn(
                      "w-full space-y-1 rounded-lg border p-2.5 text-left text-sm transition-colors outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50",
                      selected?.id === i.id && "border-primary bg-primary/5",
                    )}
                  >
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="font-mono text-xs">{i.id}</span>
                      <InterventionStatusBadge status={i.status} />
                    </span>
                    <span className="block font-medium">{i.title}</span>
                    <span className="block text-xs text-muted-foreground">
                      Updated {formatTime(i.updated_at, i.problem.hospital_timezone)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>

            {selected ? (
              <div className="min-w-0 space-y-4">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-sm">{selected.id}</span>
                    <InterventionTypeBadge type={selected.type} />
                    <InterventionStatusBadge status={selected.status} />
                  </div>
                  <p className="font-semibold text-foreground">{selected.title}</p>
                  {NEXT_STEP[selected.status] ? (
                    <p className="text-sm text-muted-foreground">{NEXT_STEP[selected.status]}</p>
                  ) : null}
                  {selected.status_reason ? (
                    <p className="text-sm text-muted-foreground">
                      Reason: {selected.status_reason}
                    </p>
                  ) : null}
                  {selected.approval ? (
                    <p className="text-xs text-muted-foreground">
                      {selected.approval.decision === "approve" ? "Approved" : "Rejected"} by{" "}
                      {selected.approval.decided_by.actor_id} at{" "}
                      {formatTime(selected.approval.decided_at, selected.problem.hospital_timezone)}
                      {selected.approval.note ? ` — “${selected.approval.note}”` : ""}
                    </p>
                  ) : null}
                </div>
                <InterventionActions i={selected} />
                {selected.offers.length ? (
                  <div className="space-y-1">
                    <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                      Offers
                    </h4>
                    <OfferRows
                      offers={selected.offers}
                      tz={selected.problem.hospital_timezone}
                      actions={(o) => <OfferActions offer={o} />}
                    />
                  </div>
                ) : null}
                {selected.type === "split_shift" && selected.offers.length ? (
                  <ImpactView
                    role={role}
                    versionKey={versionKey}
                    interventionId={selected.id}
                    tz={selected.problem.hospital_timezone}
                  />
                ) : null}
                <AuditTrail
                  role={role}
                  versionKey={versionKey}
                  interventionId={selected.id}
                  tz={selected.problem.hospital_timezone}
                />
                <Disclosure summary="Full proposal: problem, eligibility evidence, impact, alternatives">
                  <InterventionDetailView intervention={selected} />
                </Disclosure>
              </div>
            ) : null}
          </div>
        )}
      </SectionCard>
    </section>
  );
}
