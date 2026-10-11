"use client";

import { MonitorTrace } from "@/components/layout/ecg";
import { clockParts } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSystemStatus } from "./system-status-provider";
import { TimeControls } from "./time-controls";

const SOURCE_HINT = {
  environment: "From SIMULATION_REFERENCE_TIME (no dataset loaded)",
  dataset: "At the dataset reference time",
  manual: "Moved with the simulation controls",
  unset: "Set once a dataset is loaded",
} as const;

/** Live (SSE) or polling, as a dot and a word; never colour alone. */
function LiveIndicator({ dark = true }: { dark?: boolean }) {
  const { connection, live } = useSystemStatus();
  const state =
    connection === "offline" || connection === "degraded"
      ? "offline"
      : connection === "checking"
        ? "checking"
        : live === "connected"
          ? "live"
          : "polling";
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={
        state === "live"
          ? "Live updates over server-sent events"
          : state === "polling"
            ? "Live stream unavailable; refreshing by polling"
            : undefined
      }
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          state === "live" && "animate-[ng-pulse_2s_ease-in-out_infinite] bg-success",
          state === "polling" && (dark ? "bg-clock-fg/45" : "bg-faint-foreground"),
          state === "checking" && "animate-ng-pulse bg-clock-fg/45",
          state === "offline" && "bg-critical",
        )}
      />
      {state}
    </span>
  );
}

/**
 * The signature element: the simulation's "now" on a dark monitor. Every elapsed time and
 * forecast on screen is relative to it, so it sits at the top of the sidebar.
 */
export function MonitorCard({ className }: { className?: string }) {
  const { config } = useSystemStatus();
  const clock = config?.simulation_time ? clockParts(config.simulation_time) : null;

  return (
    <section
      aria-label="Simulation clock"
      className={cn(
        "relative flex flex-col gap-2.5 overflow-hidden rounded-2xl bg-clock-bg px-4 pt-4 pb-3.5 text-clock-fg",
        className,
      )}
    >
      <MonitorTrace className="top-6 h-24" />
      <div className="relative flex items-center justify-between gap-2 text-label">
        <span className="opacity-65">Simulation{clock ? ` · ${clock.zone}` : ""}</span>
        <LiveIndicator />
      </div>
      <p
        className="relative font-mono text-[44px] leading-none font-medium tracking-[-0.04em] tabular-nums"
        aria-live="polite"
        title={config ? SOURCE_HINT[config.simulation_time_source] : undefined}
      >
        {clock ? (
          <>
            <span className="sr-only">Simulation time </span>
            {clock.time}
          </>
        ) : (
          <span className="opacity-50" aria-label="Simulation time not set">
            —:—
          </span>
        )}
      </p>
      <p className="relative truncate font-mono text-micro opacity-60">
        {clock ? clock.day : "No clock yet"}
        {config ? ` · data v${config.data_version} · wf v${config.workflow_version}` : ""}
      </p>
      <TimeControls className="relative" />
    </section>
  );
}

/** The compact dark clock for the top bar when the sidebar is hidden or absent. */
export function ClockPill({ className }: { className?: string }) {
  const { config } = useSystemStatus();
  const clock = config?.simulation_time ? clockParts(config.simulation_time) : null;
  return (
    <span
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-[9px] bg-clock-bg px-2.5 text-clock-fg",
        className,
      )}
      title={clock ? `Simulation time · ${clock.day}` : "Simulation time not set"}
      aria-live="polite"
    >
      <span className="sr-only">Simulation time </span>
      <span className="font-mono text-[15px] font-semibold tracking-[-0.02em] tabular-nums">
        {clock?.time ?? "—:—"}
      </span>
      {clock ? <span className="text-micro opacity-70">{clock.zone}</span> : null}
    </span>
  );
}

export { LiveIndicator };
