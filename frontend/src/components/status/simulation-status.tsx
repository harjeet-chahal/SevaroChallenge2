"use client";

import { Clock, Database, RefreshCw, Server } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatClockTime, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSystemStatus } from "./system-status-provider";

function StatusItem({
  icon: Icon,
  label,
  value,
  hint,
  tone = "default",
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "muted" | "critical" | "warning" | "success";
}) {
  return (
    <div className="flex min-w-0 items-start gap-3">
      <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
        <Icon className="size-4" aria-hidden />
      </span>
      <div className="min-w-0">
        <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
          {label}
        </dt>
        <dd
          className={cn(
            "truncate text-sm font-semibold tabular-nums",
            tone === "muted" && "text-muted-foreground",
            tone === "critical" && "text-critical",
            tone === "warning" && "text-warning",
            tone === "success" && "text-success",
          )}
        >
          {value}
        </dd>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </div>
    </div>
  );
}

const SOURCE_HINT = {
  environment: "From SIMULATION_REFERENCE_TIME (no dataset loaded)",
  dataset: "At the dataset reference time",
  manual: "Moved with the simulation controls",
  unset: "Set once a dataset is loaded",
} as const;

/** Simulation clock, dataset state and API connectivity — all read from the backend. */
export function SimulationStatus({ className }: { className?: string }) {
  const { connection, config, health, error, lastCheckedAt, refresh, live } = useSystemStatus();
  const reachable = connection === "online" || connection === "degraded";

  const apiValue = {
    checking: "Checking…",
    online: "Connected",
    degraded: "Degraded",
    offline: "Unreachable",
  }[connection];
  const apiTone = {
    checking: "muted",
    online: "success",
    degraded: "warning",
    offline: "critical",
  } as const;

  return (
    <section
      aria-label="Simulation status"
      className={cn("rounded-xl border bg-card p-4 shadow-xs", className)}
    >
      <dl className="grid gap-4 sm:grid-cols-3">
        <StatusItem
          icon={Clock}
          label="Simulation time"
          value={config?.simulation_time ? formatDateTime(config.simulation_time) : "Not set"}
          tone={config?.simulation_time ? "default" : "muted"}
          hint={config ? SOURCE_HINT[config.simulation_time_source] : undefined}
        />
        <StatusItem
          icon={Database}
          label="Dataset"
          value={!config ? "Unknown" : config.dataset_loaded ? "Loaded" : "Not loaded"}
          tone={!config ? "muted" : config.dataset_loaded ? "success" : "warning"}
          hint={config && !config.dataset_loaded ? "No operational data yet" : undefined}
        />
        <StatusItem
          icon={Server}
          label="Backend API"
          value={apiValue}
          tone={apiTone[connection]}
          hint={
            reachable && health
              ? `v${health.version} · ${health.environment}`
              : (error ?? undefined)
          }
        />
      </dl>
      <div className="mt-3 flex items-center justify-between gap-2 border-t pt-3 text-xs text-muted-foreground">
        <span aria-live="polite">
          {lastCheckedAt ? `Last checked ${formatClockTime(lastCheckedAt)}` : "Checking…"} ·{" "}
          {live === "connected"
            ? "live updates on"
            : live === "connecting"
              ? "connecting live updates…"
              : "live updates unavailable (polling)"}
        </span>
        <Button variant="ghost" size="xs" onClick={refresh}>
          <RefreshCw aria-hidden />
          Refresh
        </Button>
      </div>
    </section>
  );
}
