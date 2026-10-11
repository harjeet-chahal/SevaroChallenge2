import { ArrowDown, ArrowUp, FlaskConical, HandHeart } from "lucide-react";

import type { Availability, ConsultStage, VoluntaryMatch, VoluntaryStatus } from "@/lib/api/types";
import { AVAILABILITY_LABELS, STAGE_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { PILL_TONES, Pill, type PillTone } from "./pill";

const chip =
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-label font-medium whitespace-nowrap";

const AVAILABILITY_TONES: Record<Availability, PillTone> = {
  busy: "critical",
  available: "success",
  unavailable: "warning",
  off_shift: "muted",
};

/** Availability as decided by the backend's precedence rules. Text, not colour alone. */
export function AvailabilityBadge({
  value,
  className,
}: {
  value: Availability;
  className?: string;
}) {
  return (
    <Pill tone={AVAILABILITY_TONES[value]} dot className={className}>
      {AVAILABILITY_LABELS[value]}
    </Pill>
  );
}

export function StageBadge({ stage, className }: { stage: ConsultStage; className?: string }) {
  const done = stage === "signed_off";
  return (
    <Pill tone={done ? "muted" : "info"} className={className}>
      {STAGE_LABELS[stage]}
    </Pill>
  );
}

export function SyntheticBadge({ className }: { className?: string }) {
  return (
    <Pill tone="warning" icon={FlaskConical} className={cn("font-semibold", className)}>
      Synthetic sample data
    </Pill>
  );
}

export function TagBadge({
  children,
  tone = "neutral",
  title,
}: {
  children: React.ReactNode;
  tone?: "neutral" | "info" | "warning" | "critical" | "success";
  title?: string;
}) {
  return (
    <Pill tone={tone === "neutral" ? "muted" : tone} title={title}>
      {children}
    </Pill>
  );
}

const VOLUNTARY_NOTES: Record<VoluntaryStatus, string | null> = {
  applied: null,
  not_eligible: "not eligible",
  no_shortage_overlap: "outside the shortage",
  no_offer_fits: "window too short",
  outside_tolerance: "covers less",
  not_needed: "not needed",
  disabled: "not used",
};

/**
 * The physician shared voluntary availability. Green only when it counts for this offer
 * (inside the window, every rule passed); otherwise muted, with the reason in words.
 */
export function VoluntaryBadge({
  match,
  className,
}: {
  match: VoluntaryMatch | null | undefined;
  className?: string;
}) {
  if (!match) return null;
  const note = VOLUNTARY_NOTES[match.status];
  return (
    <span
      title={match.message}
      className={cn(
        chip,
        note === null ? PILL_TONES.success : PILL_TONES.muted,
        className,
      )}
    >
      <HandHeart className="size-3" aria-hidden />
      Voluntarily Available
      {note ? <span className="font-normal">· {note}</span> : null}
      <span className="sr-only">. {match.message}</span>
    </span>
  );
}

/** Rank change caused by voluntary availability ("Up from #2"). */
export function RankMovement({ movement, from }: { movement: number; from: number | null }) {
  if (!movement || from === null) return null;
  const up = movement > 0;
  const Icon = up ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-semibold whitespace-nowrap",
        up ? "text-success-ink" : "text-muted-foreground",
      )}
    >
      <Icon className="size-3" aria-hidden />
      {up ? "Up" : "Down"} from #{from}
    </span>
  );
}
