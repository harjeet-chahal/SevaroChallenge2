import { FlaskConical } from "lucide-react";

import type { Availability, ConsultStage } from "@/lib/api/types";
import { AVAILABILITY_LABELS, STAGE_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";

const chip =
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap";

const AVAILABILITY_STYLES: Record<Availability, string> = {
  busy: "border-critical-border bg-critical-soft text-critical",
  available: "border-success-border bg-success-soft text-success",
  unavailable: "border-warning-border bg-warning-soft text-warning",
  off_shift: "border-border bg-muted text-muted-foreground",
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
    <span className={cn(chip, AVAILABILITY_STYLES[value], className)}>
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {AVAILABILITY_LABELS[value]}
    </span>
  );
}

export function StageBadge({ stage, className }: { stage: ConsultStage; className?: string }) {
  const done = stage === "signed_off";
  return (
    <span
      className={cn(
        chip,
        done
          ? "border-border bg-muted text-muted-foreground"
          : "border-info-border bg-info-soft text-info",
        className,
      )}
    >
      {STAGE_LABELS[stage]}
    </span>
  );
}

export function SyntheticBadge({ className }: { className?: string }) {
  return (
    <span className={cn(chip, "border-warning-border bg-warning-soft text-warning", className)}>
      <FlaskConical className="size-3" aria-hidden />
      SYNTHETIC SAMPLE DATA
    </span>
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
  const tones = {
    neutral: "border-border bg-muted text-muted-foreground",
    info: "border-info-border bg-info-soft text-info",
    warning: "border-warning-border bg-warning-soft text-warning",
    critical: "border-critical-border bg-critical-soft text-critical",
    success: "border-success-border bg-success-soft text-success",
  };
  return (
    <span title={title} className={cn(chip, "font-medium", tones[tone])}>
      {children}
    </span>
  );
}
