"use client";

import { cn } from "@/lib/utils";

import { useSystemStatus, type Connection } from "./system-status-provider";

const CONNECTION_STYLES: Record<Connection, { label: string; dot: string; chip: string }> = {
  checking: {
    label: "Checking API…",
    dot: "bg-muted-foreground animate-pulse",
    chip: "border-border bg-muted text-muted-foreground",
  },
  online: {
    label: "API connected",
    dot: "bg-success",
    chip: "border-success-border bg-success-soft text-success",
  },
  degraded: {
    label: "API degraded",
    dot: "bg-warning",
    chip: "border-warning-border bg-warning-soft text-warning",
  },
  offline: {
    label: "API unreachable",
    dot: "bg-critical",
    chip: "border-critical-border bg-critical-soft text-critical",
  },
};

export function BackendStatusBadge({ className }: { className?: string }) {
  const { connection, health, error } = useSystemStatus();
  const style = CONNECTION_STYLES[connection];
  const title = [
    style.label,
    health ? `v${health.version} · ${health.environment}` : null,
    error,
  ]
    .filter(Boolean)
    .join(" — ");

  return (
    <span
      role="status"
      aria-live="polite"
      title={title}
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium whitespace-nowrap",
        style.chip,
        className,
      )}
    >
      <span aria-hidden className={cn("size-2 rounded-full", style.dot)} />
      {style.label}
    </span>
  );
}
