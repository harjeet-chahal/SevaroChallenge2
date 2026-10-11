"use client";

import {
  Ban,
  CheckCheck,
  ChevronDown,
  ListChecks,
  Loader2,
  Play,
  Power,
  Send,
  Undo2,
} from "lucide-react";
import { useState } from "react";

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
import {
  InterventionStatusBadge,
  InterventionStepper,
  InterventionTypeBadge,
  needsCoordinator,
} from "./status";
import { sentOffersFeedback, useAction } from "./use-action";
import { useWorkflow } from "./workflow-provider";

/** Who the intervention is waiting on, and what happens next — from the coordinator's seat. */
function nextStep(i: Intervention): { owner: string; text: string } | null {
  switch (i.status) {
    case "proposed":
      return { owner: "You", text: "Apply the reassignment." };
    case "pending_approval":
      return {
        owner: "Clinical lead",
        text: "Waiting for approval. No physician has been contacted.",
      };
    case "approved":
      return i.type === "split_shift"
        ? { owner: "You", text: "Approved. Send the offer (simulated)." }
        : { owner: "You", text: "Approved. Mark it resolved once handled." };
    case "offer_sent":
      return {
        owner: "Physician",
        text: "Waiting for a reply. Offers expire 10 min after sending.",
      };
    case "accepted":
      return { owner: "Physician", text: "Preparing to come online. Not active capacity yet." };
    case "activated":
      return { owner: "In effect", text: "Online and routable within the approved scope." };
    default:
      return null;
  }
}

function InterventionActions({ i }: { i: Intervention }) {
  const { role, select } = useWorkflow();
  const { pending, feedback, run: runAction } = useAction();
  // Keep this intervention in view after acting, so the outcome stays next to it even when
  // the action moves it to another group.
  const run: typeof runAction = (key, action) => {
    select(i.id);
    return runAction(key, action);
  };
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
                return sentOffersFeedback(
                  sent,
                  "(simulated delivery; nothing leaves the system). They expire 10 simulated minutes after sending.",
                );
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

function ListItem({
  i,
  active,
  onSelect,
}: {
  i: Intervention;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active}
      className={cn(
        "w-full space-y-1 rounded-lg border bg-card p-2.5 text-left text-sm transition-colors outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50",
        active && "border-primary bg-primary/5 hover:bg-primary/5",
      )}
    >
      <span className="line-clamp-2 font-medium">{i.title}</span>
      <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        <InterventionStatusBadge status={i.status} />
        <span className="font-mono">{i.id}</span>
        <span>· {formatTime(i.updated_at, i.problem.hospital_timezone)}</span>
      </span>
    </button>
  );
}

function Group({
  title,
  count,
  tone = "neutral",
  children,
}: {
  title: string;
  count: number;
  tone?: "warning" | "neutral";
  children: React.ReactNode;
}) {
  if (!count) return null;
  return (
    <div className="space-y-1.5">
      <h3
        className={cn(
          "flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase",
          tone === "warning" ? "text-warning" : "text-muted-foreground",
        )}
      >
        {title}
        <span className="tabular-nums">({count})</span>
      </h3>
      {children}
    </div>
  );
}

function SelectedIntervention({ i }: { i: Intervention }) {
  const { role, versionKey } = useWorkflow();
  const next = nextStep(i);
  const tz = i.problem.hospital_timezone;
  const mine = needsCoordinator(i);
  return (
    <div className="min-w-0 space-y-4">
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <InterventionTypeBadge type={i.type} />
          <InterventionStatusBadge status={i.status} />
          <span className="font-mono text-xs text-muted-foreground">{i.id}</span>
        </div>
        <p className="text-base font-semibold text-navy">{i.title}</p>
      </div>

      <InterventionStepper intervention={i} />

      {next || i.status_reason || i.approval || i.allowed_actions.length ? (
        <div
          className={cn(
            "space-y-2 rounded-lg border p-3",
            mine ? "border-warning-border bg-warning-soft/60" : "bg-muted/30",
          )}
        >
          {next ? (
            <p className="text-sm">
              <span
                className={cn(
                  "mr-1.5 text-xs font-semibold tracking-wide uppercase",
                  mine ? "text-warning" : "text-muted-foreground",
                )}
              >
                {mine
                  ? "Your move"
                  : next.owner === "In effect"
                    ? "In effect"
                    : `Waiting on ${next.owner.toLowerCase()}`}
              </span>
              {next.text}
            </p>
          ) : null}
          {i.status_reason ? (
            <p className="text-sm text-muted-foreground">Reason: {i.status_reason}</p>
          ) : null}
          {i.approval ? (
            <p className="text-xs text-muted-foreground">
              {i.approval.decision === "approve" ? "Approved" : "Rejected"} by{" "}
              {i.approval.decided_by.actor_id} at {formatTime(i.approval.decided_at, tz)}
              {i.approval.note ? ` — “${i.approval.note}”` : ""}
            </p>
          ) : null}
          {/* Keyed: a result or spinner never carries over to another intervention. */}
          <InterventionActions key={i.id} i={i} />
        </div>
      ) : null}

      {i.offers.length ? (
        <div className="space-y-1">
          <h4 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
            Offers
          </h4>
          <OfferRows offers={i.offers} tz={tz} actions={(o) => <OfferActions offer={o} />} />
        </div>
      ) : null}
      {i.type === "split_shift" && i.offers.length ? (
        <ImpactView role={role} versionKey={versionKey} interventionId={i.id} tz={tz} />
      ) : null}
      <div className="space-y-2">
        <Disclosure summary="Audit trail: every recorded step">
          <AuditTrail role={role} versionKey={versionKey} interventionId={i.id} tz={tz} />
        </Disclosure>
        <Disclosure summary="Full proposal: problem, eligibility evidence, impact, alternatives">
          <InterventionDetailView intervention={i} />
        </Disclosure>
      </div>
    </div>
  );
}

/**
 * Everything the coordinator has set in motion, grouped by who has to act next. Buttons
 * only appear when the backend says the coordinator may take that step now.
 */
export function InterventionBoard({ className }: { className?: string }) {
  const { role, interventions, selectedId, select, versionKey } = useWorkflow();
  const { config } = useSystemStatus();
  const [showClosed, setShowClosed] = useState(false);
  const items = interventions.data?.items ?? [];
  const open = items.filter((i) => !i.is_terminal);
  const mine = open.filter(needsCoordinator);
  const waiting = open.filter((i) => !needsCoordinator(i));
  const closed = items.filter((i) => i.is_terminal);
  const picked = items.find((i) => i.id === selectedId);
  const selected = picked ?? mine[0] ?? waiting[0] ?? null;
  const closedVisible = showClosed || (picked?.is_terminal ?? false);

  const item = (i: Intervention) => (
    <li key={i.id}>
      <ListItem i={i} active={selected?.id === i.id} onSelect={() => select(i.id)} />
    </li>
  );

  return (
    <SectionCard
      id="intervention-board"
      className={className}
      title="Interventions"
      icon={ListChecks}
      info="Proposed, approved and active interventions for this dataset, their offers and every recorded step. Grouped by who has to act next."
      action={
        open.length ? (
          <span className="flex flex-wrap items-center justify-end gap-1.5">
            {mine.length ? <TagBadge tone="warning">{mine.length} need you</TagBadge> : null}
            {waiting.length ? <TagBadge tone="neutral">{waiting.length} waiting</TagBadge> : null}
          </span>
        ) : null
      }
    >
      <div className="space-y-3">
        {!config?.dataset_loaded ? (
          <EmptyState compact icon={ListChecks} title="No dataset loaded" />
        ) : interventions.error ? (
          <p className="text-sm text-critical">{interventions.error}</p>
        ) : !interventions.data ? (
          <p className="text-sm text-muted-foreground">Loading interventions…</p>
        ) : items.length === 0 ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Nothing in flight. Proposals you start from an alert or a split-shift recommendation
              appear here.
            </p>
            <Disclosure summary="Recent workflow activity">
              <AuditTrail role={role} versionKey={versionKey} limit={15} />
            </Disclosure>
          </div>
        ) : !selected && !closedVisible ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">
              Nothing in flight right now. New proposals appear here.
            </p>
            <Button
              variant="ghost"
              size="xs"
              className="text-muted-foreground"
              onClick={() => setShowClosed(true)}
            >
              <ChevronDown aria-hidden />
              Show closed ({closed.length})
            </Button>
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[minmax(16rem,22rem)_1fr]">
            <div className="space-y-4" aria-label="Interventions">
              <Group title="Needs you" count={mine.length} tone="warning">
                <ul className="space-y-1.5">{mine.map(item)}</ul>
              </Group>
              <Group title="Waiting on others" count={waiting.length}>
                <ul className="space-y-1.5">{waiting.map(item)}</ul>
              </Group>
              {open.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nothing in flight right now.</p>
              ) : null}
              {closed.length ? (
                <div className="space-y-1.5">
                  <Button
                    variant="ghost"
                    size="xs"
                    className="-ml-2 text-muted-foreground"
                    aria-expanded={closedVisible}
                    onClick={() => setShowClosed(!closedVisible)}
                  >
                    <ChevronDown
                      className={cn("transition-transform", closedVisible && "rotate-180")}
                      aria-hidden
                    />
                    {closedVisible ? "Hide" : "Show"} closed ({closed.length})
                  </Button>
                  {closedVisible ? <ul className="space-y-1.5">{closed.map(item)}</ul> : null}
                </div>
              ) : null}
            </div>

            {selected ? (
              <SelectedIntervention i={selected} />
            ) : (
              <p className="self-center text-center text-sm text-muted-foreground">
                Select an intervention to see its offers, impact and audit trail.
              </p>
            )}
          </div>
        )}
      </div>
    </SectionCard>
  );
}
