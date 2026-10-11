"use client";

import { Loader2, TriangleAlert } from "lucide-react";

import { DataEmptyState } from "@/components/shared/data-empty-state";
import { EmptyState } from "@/components/shared/empty-state";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import type { KeyedResource } from "@/hooks/use-keyed-resource";
import type { AvailabilityClass, EvidenceConfidence, LsmPhase, RootCause } from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn(className, "animate-spin")} />;
}

/** Loading / error / no-dataset handling for a backend-computed NEUROGRID resource. */
export function Gate<T>({
  resource,
  feature,
  children,
}: {
  resource: KeyedResource<T>;
  feature: string;
  children: (data: T) => React.ReactNode;
}) {
  const { availability, config } = useSystemStatus();
  if (availability === "offline" || availability === "degraded" || !config?.dataset_loaded) {
    return <DataEmptyState feature={feature} whenNoDataset={`Load a dataset to see ${feature}.`} />;
  }
  if (resource.data) return <>{children(resource.data)}</>;
  if (resource.error) {
    return (
      <EmptyState icon={TriangleAlert} title={`Could not load ${feature}`} description={resource.error}>
        <Button variant="outline" size="sm" onClick={resource.reload}>
          Retry
        </Button>
      </EmptyState>
    );
  }
  return <EmptyState icon={Spinner} title="Computing…" description={`Running ${feature} on the current state.`} />;
}

export type Tone = "critical" | "warning" | "success" | "info" | "muted" | "primary";

const TONES: Record<Tone, string> = {
  critical: "border-critical-border bg-critical-soft text-critical",
  warning: "border-warning-border bg-warning-soft text-warning",
  success: "border-success-border bg-success-soft text-success",
  info: "border-info-border bg-info-soft text-info",
  muted: "border-border bg-muted text-muted-foreground",
  primary: "border-primary/40 bg-primary/10 text-primary",
};

export function Pill({
  tone = "muted",
  icon: Icon,
  children,
  className,
  title,
}: {
  tone?: Tone;
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {Icon ? <Icon className="size-3.5" aria-hidden /> : null}
      {children}
    </span>
  );
}

export const CLASS_LABEL: Record<AvailabilityClass, string> = {
  OFF_SHIFT: "Off shift",
  AVAILABLE: "Available",
  BUSY_CALL: "On call",
  BUSY_VIDEO: "On video",
  PROBABLY_BUSY_EXTERNAL: "Probably busy (external)",
  INTERRUPTIBLE_MEETING: "In meeting (interruptible)",
  UNAVAILABLE: "Unavailable",
  UNCERTAIN: "Uncertain",
  UNKNOWN: "Unknown",
};

export const CLASS_TONE: Record<AvailabilityClass, Tone> = {
  OFF_SHIFT: "muted",
  AVAILABLE: "success",
  BUSY_CALL: "info",
  BUSY_VIDEO: "info",
  PROBABLY_BUSY_EXTERNAL: "warning",
  INTERRUPTIBLE_MEETING: "primary",
  UNAVAILABLE: "critical",
  UNCERTAIN: "warning",
  UNKNOWN: "muted",
};

export function ClassBadge({ cls }: { cls: AvailabilityClass }) {
  return <Pill tone={CLASS_TONE[cls]}>{CLASS_LABEL[cls]}</Pill>;
}

export function ConfidenceBadge({ c }: { c: EvidenceConfidence }) {
  const tone: Tone = c === "CONFIRMED" ? "success" : c === "LIKELY" ? "info" : "warning";
  return (
    <Pill tone={tone} title="Evidence label — not a calibrated probability">
      {c.toLowerCase()}
    </Pill>
  );
}

export const PHASE: Record<LsmPhase, { label: string; tone: Tone }> = {
  green: { label: "Window open", tone: "success" },
  amber: { label: "Act soon", tone: "warning" },
  red: { label: "Act now", tone: "critical" },
  missed: { label: "Proactive window missed", tone: "critical" },
  no_candidate: { label: "No eligible candidate", tone: "critical" },
};

export const CAUSE_LABEL: Record<RootCause, string> = {
  TOTAL_CAPACITY_SHORTAGE: "Total capacity shortage",
  CREDENTIALING_BOTTLENECK: "Credentialing bottleneck",
  SHIFT_COLLISION: "Shift collision",
  ROUTING_ELIGIBILITY_FAILURE: "Routing eligibility failure",
  WORKLOAD_CONCENTRATION: "Workload concentration",
  AVAILABILITY_UNCERTAINTY: "Availability uncertainty",
  DOCUMENTATION_HANDOFF_RISK: "Documentation handoff risk",
  MULTI_FACTOR: "Multi-factor",
};

export const CONTRACT_TONE: Record<string, Tone> = {
  PROPOSED: "info",
  AWAITING_APPROVAL: "warning",
  REVALIDATION_REQUIRED: "warning",
  READY_TO_DISPATCH: "primary",
  RESPONSE_PENDING: "info",
  ACTIVATION_PENDING: "info",
  ACTIVE: "success",
  VERIFYING: "info",
  RESOLVED: "success",
  PARTIALLY_RESOLVED: "warning",
  FAILED: "critical",
  EXPIRED: "critical",
  REJECTED: "muted",
  CANCELLED: "muted",
  ESCALATED: "warning",
};

export function ContractPhaseBadge({ phase }: { phase: string }) {
  return <Pill tone={CONTRACT_TONE[phase] ?? "muted"}>{phase.replaceAll("_", " ").toLowerCase()}</Pill>;
}

/** Label that says a number is projected, not observed. */
export function Projected({ className }: { className?: string }) {
  return (
    <span className={cn("text-[0.68rem] font-semibold tracking-wider text-muted-foreground uppercase", className)}>
      projected
    </span>
  );
}

export function KeyValue({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 rounded-lg border bg-muted/40 px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-lg font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-[0.7rem] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function fmtMin(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  const r = Math.round(n);
  if (Math.abs(r) < 60) return `${r} min`;
  const h = Math.trunc(r / 60);
  const m = Math.abs(r % 60);
  return m ? `${h} h ${m} min` : `${h} h`;
}

export function fmtPm(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : `${Math.round(n * 10) / 10} phys-min`;
}
