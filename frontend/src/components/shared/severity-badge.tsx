import { CircleAlert, Info, OctagonAlert } from "lucide-react";

import type { Severity } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { Pill } from "./pill";

const SEVERITY_STYLES: Record<
  Severity,
  { label: string; icon: React.ComponentType<{ className?: string }> }
> = {
  critical: { label: "Critical", icon: OctagonAlert },
  warning: { label: "Warning", icon: CircleAlert },
  info: { label: "Info", icon: Info },
};

/** Severity is always conveyed by icon + text, never colour alone. */
export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const { label, icon } = SEVERITY_STYLES[severity];
  return (
    <Pill tone={severity} icon={icon} className={cn("font-semibold", className)}>
      {label}
    </Pill>
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
