/** Human-readable labels for backend enum values. Presentation only — no logic. */

import type {
  Availability,
  ConsultStage,
  DerivedActivity,
  InterventionStatus,
  InterventionType,
  OfferStatus,
  RecommendedAction,
} from "@/lib/api/types";

export const STAGE_LABELS: Record<ConsultStage, string> = {
  received: "Received",
  triaged: "Triaged",
  assigned: "Assigned",
  provider_contacted: "Provider contacted",
  imaging_pending: "CT/CTA or imaging pending",
  imaging_review: "Imaging review",
  video_in_progress: "Video in progress",
  note_pending: "Note pending",
  documentation: "Documentation",
  signed_off: "Signed off",
};

export const ACTIVITY_LABELS: Record<DerivedActivity, string> = {
  available: "Available",
  incoming_call: "Incoming hospital call",
  outgoing_call: "Outgoing hospital call",
  video_consult: "Video consult",
  documentation: "Documentation / note",
  external_video_suspected: "Camera on, no Synapse session",
  in_meeting: "In meeting",
  temporarily_unavailable: "Temporarily unavailable",
  off_shift: "Off shift",
};

export const AVAILABILITY_LABELS: Record<Availability, string> = {
  busy: "Busy",
  available: "Available",
  unavailable: "Unavailable",
  off_shift: "Off shift",
};

export function eventTypeLabel(eventType: string): string {
  return eventType.replaceAll("_", " ");
}

export const ACTION_LABELS: Record<RecommendedAction, string> = {
  reassign_consult: "Reassign consult",
  escalate: "Escalate to clinical lead",
  contact_physician: "Contact physician",
  propose_split_shift: "Propose split shift",
  monitor: "Monitor",
};

export const INTERVENTION_TYPE_LABELS: Record<InterventionType, string> = {
  split_shift: "Split-shift staffing request",
  reassign_consult: "Consult reassignment",
  escalation: "Clinical escalation",
};

export const INTERVENTION_STATUS_LABELS: Record<InterventionStatus, string> = {
  proposed: "Proposed",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  offer_sent: "Offer sent",
  accepted: "Accepted · preparing",
  declined: "Declined",
  expired: "Expired",
  activated: "Activated",
  completed: "Completed",
  cancelled: "Cancelled",
  no_longer_required: "No longer required",
};

export const OFFER_STATUS_LABELS: Record<OfferStatus, string> = {
  sent: "Awaiting reply",
  accepted: "Accepted · preparing",
  active: "Online",
  completed: "Completed",
  declined: "Declined",
  expired: "Expired",
  withdrawn: "Withdrawn",
  redundant: "Not needed (redundant)",
  cancelled: "Cancelled",
};

/** Plain-language names for audit actions (falls back to the raw code). */
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  intervention_proposed: "Proposed",
  approval_requested: "Approval requested",
  intervention_approved: "Approved",
  intervention_rejected: "Rejected",
  approval_blocked: "Approval blocked by revalidation",
  offer_sent: "Offer sent (simulated)",
  offers_sent: "Offers sent",
  offer_not_sent: "Offer not sent",
  offer_accepted: "Accepted",
  offer_accepted_redundant: "Accepted after need was met",
  offer_declined: "Declined",
  offer_expired: "Expired",
  offer_withdrawn: "Withdrawn",
  duplicate_response_ignored: "Duplicate reply ignored",
  response_rejected: "Reply refused",
  redundant_acceptance_recorded: "Redundant acceptance recorded",
  conflict_detected: "Conflict detected",
  conflict_resolved: "Conflict resolved",
  physician_activated: "Physician online",
  coverage_recalculated: "Coverage recalculated",
  split_shift_completed: "Shift completed",
  split_shift_cancelled: "Shift cancelled",
  split_shift_lapsed: "Shift lapsed",
  intervention_cancelled: "Cancelled",
  intervention_no_longer_required: "No longer required",
  intervention_accepted: "Status: accepted",
  intervention_activated: "Status: activated",
  intervention_completed: "Status: completed",
  intervention_declined: "Status: declined",
  intervention_expired: "Status: expired",
  intervention_offer_sent: "Status: offer sent",
  reassignment_applied: "Reassignment applied",
  apply_blocked: "Apply blocked by revalidation",
  escalation_resolved: "Escalation resolved",
  intervention_closed_dataset_replaced: "Closed: dataset replaced",
  offer_closed_dataset_replaced: "Offer closed: dataset replaced",
};

/** Short dataset name: its label, or the file count when the source is a list of CSVs. */
export function datasetName(active: { label: string | null; source_name: string }): string {
  if (active.label) return active.label;
  const files = active.source_name.split(",").filter((f) => f.trim());
  return files.length > 1 ? `${files.length} CSV files` : active.source_name;
}
