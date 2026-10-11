"use client";

import { cn } from "@/lib/utils";

import { useSystemStatus, type Connection } from "./system-status-provider";

const CONNECTION: Record<Connection, { label: string; dot: string }> = {
  checking: { label: "Checking backend…", dot: "bg-faint-foreground animate-ng-pulse" },
  online: { label: "Backend online", dot: "bg-success" },
  degraded: { label: "Backend degraded", dot: "bg-warning" },
  offline: { label: "Backend unreachable", dot: "bg-critical animate-ng-pulse" },
};

/** Connection state as a dot plus text (text from 1280px; always in the tooltip and to AT). */
export function BackendStatusBadge({ className }: { className?: string }) {
  const { connection, health, error } = useSystemStatus();
  const style = CONNECTION[connection];
  const title = [style.label, health ? `v${health.version} · ${health.environment}` : null, error]
    .filter(Boolean)
    .join(" — ");

  return (
    <span
      role="status"
      aria-live="polite"
      title={title}
      className={cn("inline-flex items-center gap-2 text-caption whitespace-nowrap text-muted-foreground", className)}
    >
      <span aria-hidden className={cn("size-2 rounded-full", style.dot)} />
      <span className="sr-only xl:not-sr-only">{style.label}</span>
    </span>
  );
}
