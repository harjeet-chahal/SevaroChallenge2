import { TagBadge } from "@/components/shared/status-badges";
import type { InterventionStatus, InterventionType, OfferStatus } from "@/lib/api/types";
import {
  INTERVENTION_STATUS_LABELS,
  INTERVENTION_TYPE_LABELS,
  OFFER_STATUS_LABELS,
} from "@/lib/labels";

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
  return <TagBadge tone={INTERVENTION_TONES[status]}>{INTERVENTION_STATUS_LABELS[status]}</TagBadge>;
}

export function OfferStatusBadge({ status }: { status: OfferStatus }) {
  return <TagBadge tone={OFFER_TONES[status]}>{OFFER_STATUS_LABELS[status]}</TagBadge>;
}

export function InterventionTypeBadge({ type }: { type: InterventionType }) {
  return <TagBadge tone="neutral">{INTERVENTION_TYPE_LABELS[type]}</TagBadge>;
}
