"use client";

import { formatClockTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSystemStatus, type Connection } from "./system-status-provider";

const CONNECTION_STYLES: Record<Connection, { label: string; dot: string }> = {
  checking: { label: "Checking backend…", dot: "bg-faint-foreground animate-ng-pulse" },
  online: { label: "Backend online", dot: "bg-success" },
  degraded: { label: "Backend degraded", dot: "bg-warning" },
  offline: { label: "Backend offline", dot: "bg-critical" },
};

/** Connection as a dot plus words; version, live/polling and freshness are in its title. */
export function BackendStatusBadge({ className }: { className?: string }) {
  const { connection, health, error, live, lastCheckedAt } = useSystemStatus();
  const style = CONNECTION_STYLES[connection];
  const title = [
    style.label,
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
        "inline-flex items-center gap-2 text-[13.5px] whitespace-nowrap text-foreground-2",
        className,
      )}
    >
      <span aria-hidden className={cn("size-2 shrink-0 rounded-full", style.dot)} />
      <span className="max-sm:sr-only">{style.label}</span>
    </span>
  );
}
