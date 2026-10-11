import { TagBadge } from "@/components/shared/status-badges";
import type {
  Intervention,
  InterventionStatus,
  InterventionType,
  OfferStatus,
} from "@/lib/api/types";
import {
  INTERVENTION_STATUS_LABELS,
  INTERVENTION_TYPE_LABELS,
  OFFER_STATUS_LABELS,
} from "@/lib/labels";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "info" | "warning" | "critical" | "success";

const INTERVENTION_TONES: Record<InterventionStatus, Tone> = {
  proposed: "info",
  pending_approval: "warning",
  approved: "info",
  rejected: "neutral",
  offer_sent: "info",
  accepted: "info",
  declined: "neutral",
  expired: "neutral",
  activated: "success",
  completed: "success",
  cancelled: "neutral",
  no_longer_required: "neutral",
};

const OFFER_TONES: Record<OfferStatus, Tone> = {
  sent: "warning",
  accepted: "info",
  active: "success",
  completed: "success",
  declined: "neutral",
  expired: "neutral",
  withdrawn: "neutral",
  redundant: "neutral",
  cancelled: "neutral",
};

export function InterventionStatusBadge({ status }: { status: InterventionStatus }) {
  return (
    <TagBadge tone={INTERVENTION_TONES[status]}>{INTERVENTION_STATUS_LABELS[status]}</TagBadge>
  );
}

export function OfferStatusBadge({ status }: { status: OfferStatus }) {
  return <TagBadge tone={OFFER_TONES[status]}>{OFFER_STATUS_LABELS[status]}</TagBadge>;
}

export function InterventionTypeBadge({ type }: { type: InterventionType }) {
  return <TagBadge tone="neutral">{INTERVENTION_TYPE_LABELS[type]}</TagBadge>;
}

/** "Clinical escalation · Completed": what was done about a problem, and where it stands. */
export function InterventionProgressBadge({ intervention: i }: { intervention: Intervention }) {
  return (
    <TagBadge tone={INTERVENTION_TONES[i.status]} title={`${i.id}: ${i.title}`}>
      {INTERVENTION_TYPE_LABELS[i.type]} · {INTERVENTION_STATUS_LABELS[i.status]}
    </TagBadge>
  );
}

/** Interventions waiting on a coordinator step (send offers, apply, resolve). */
export function needsCoordinator(i: Intervention): boolean {
  return i.allowed_actions.some((a) => a === "send_offers" || a === "apply" || a === "resolve");
}

/** The happy path for each intervention type, as milestones. */
const MILESTONES: Record<InterventionType, { status: InterventionStatus; label: string }[]> = {
  split_shift: [
    { status: "pending_approval", label: "Proposed" },
    { status: "approved", label: "Approved" },
    { status: "offer_sent", label: "Offer sent" },
    { status: "accepted", label: "Accepted" },
    { status: "activated", label: "Online" },
    { status: "completed", label: "Completed" },
  ],
  escalation: [
    { status: "pending_approval", label: "Requested" },
    { status: "approved", label: "Approved" },
    { status: "completed", label: "Resolved" },
  ],
  reassign_consult: [
    { status: "proposed", label: "Proposed" },
    { status: "completed", label: "Applied" },
  ],
};

/**
 * Where an intervention is on its path, as labelled steps. Off-path outcomes (rejected,
 * declined, expired, cancelled, ...) have no position, so the status badge says it alone.
 */
export function InterventionStepper({ intervention: i }: { intervention: Intervention }) {
  const steps = MILESTONES[i.type];
  const at = steps.findIndex((s) => s.status === i.status);
  if (at === -1) return null;
  const finished = i.status === "completed";
  return (
    <ol className="flex items-start" aria-label="Progress">
      {steps.map((s, idx) => {
        const done = idx < at || finished;
        const current = idx === at && !finished;
        return (
          <li
            key={s.status}
            className="flex min-w-0 flex-1 flex-col items-center gap-1 text-center"
          >
            <span className="flex w-full items-center">
              <span
                aria-hidden
                className={cn(
                  "h-0.5 flex-1",
                  idx === 0 ? "bg-transparent" : done || current ? "bg-primary" : "bg-border",
                )}
              />
              <span
                aria-hidden
                className={cn(
                  "flex size-3 shrink-0 rounded-full border-2",
                  done && "border-primary bg-primary",
                  current && "border-primary bg-card ring-3 ring-primary/20",
                  !done && !current && "border-border bg-card",
                )}
              />
              <span
                aria-hidden
                className={cn(
                  "h-0.5 flex-1",
                  idx === steps.length - 1 ? "bg-transparent" : done ? "bg-primary" : "bg-border",
                )}
              />
            </span>
            <span
              className={cn(
                "px-0.5 text-[0.6875rem] leading-tight",
                current ? "font-semibold text-foreground" : "text-muted-foreground",
              )}
              aria-current={current ? "step" : undefined}
            >
              {s.label}
              <span className="sr-only">{done ? " (done)" : current ? " (current)" : ""}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
