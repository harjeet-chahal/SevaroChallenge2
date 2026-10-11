"use client";

import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSystemStatus, type Connection } from "./system-status-provider";

const CONNECTION_STYLES: Record<Connection, { label: string; dot: string; chip: string }> = {
  checking: {
    label: "Checking API…",
    dot: "bg-muted-foreground animate-pulse",
    chip: "border-border bg-muted text-muted-foreground",
  },
  online: {
    label: "Live",
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

/** Connection and freshness in one chip; the detail is in its tooltip. */
export function BackendStatusBadge({ className }: { className?: string }) {
  const { connection, health, error, live, lastCheckedAt } = useSystemStatus();
  const style = CONNECTION_STYLES[connection];
  const polling = connection === "online" && live !== "connected";
  const label = polling ? "Connected" : style.label;
  const title = [
    connection === "online" ? "Backend API connected" : style.label,
    health ? `v${health.version} · ${health.environment}` : null,
    connection === "online"
      ? live === "connected"
        ? "live updates on"
        : "live updates unavailable (polling)"
      : null,
    lastCheckedAt ? `last checked ${formatClockTime(lastCheckedAt)}` : null,
    error,
  ]
    .filter(Boolean)
    .join(" · ");

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
      <span aria-hidden className="relative flex size-2">
        {connection === "online" && !polling ? (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-60" />
        ) : null}
        <span className={cn("relative inline-flex size-2 rounded-full", style.dot)} />
      </span>
      {label}
    </span>
  );
}
