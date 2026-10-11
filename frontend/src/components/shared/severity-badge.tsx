import { CircleAlert, Info, OctagonAlert } from "lucide-react";

import type { Severity } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const SEVERITY_STYLES: Record<
  Severity,
  { label: string; className: string; icon: React.ComponentType<{ className?: string }> }
> = {
  critical: {
    label: "Critical",
    className: "border-critical-border bg-critical-soft text-critical-ink",
    icon: OctagonAlert,
  },
  warning: {
    label: "Warning",
    className: "border-warning-border bg-warning-soft text-warning-ink",
    icon: CircleAlert,
  },
  info: {
    label: "Info",
    className: "border-info-border bg-info-soft text-info-ink",
    icon: Info,
  },
};

/** Severity is always conveyed by icon + text, never colour alone. */
export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const { label, className: tone, icon: Icon } = SEVERITY_STYLES[severity];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-label font-medium whitespace-nowrap",
        tone,
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden />
      {label}
    </span>
  );
}

export function SeverityLegend({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)} aria-label="Severity legend">
      <SeverityBadge severity="critical" />
      <SeverityBadge severity="warning" />
      <SeverityBadge severity="info" />
    </div>
  );
}
