"use client";

import { Clock } from "lucide-react";

import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useSystemStatus } from "./system-status-provider";

const SOURCE_HINT = {
  environment: "From SIMULATION_REFERENCE_TIME (no dataset loaded)",
  dataset: "At the dataset reference time",
  manual: "Moved with the simulation controls",
  unset: "Set once a dataset is loaded",
} as const;

/**
 * The simulation's "now". Every elapsed time and forecast on screen is relative to it,
 * so it lives in the sticky header where it is always in view.
 */
export function SimClock({ className }: { className?: string }) {
  const { config } = useSystemStatus();
  const time = config?.simulation_time ?? null;

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-lg bg-white/10 px-2.5 py-1 text-navy-foreground",
        className,
      )}
      title={config ? SOURCE_HINT[config.simulation_time_source] : undefined}
    >
      <Clock className="size-4 shrink-0 text-navy-foreground/70" aria-hidden />
      <span className="leading-tight">
        <span className="block text-[0.625rem] font-semibold tracking-wider text-navy-foreground/70 uppercase">
          Sim time
        </span>
        <span
          className="block text-sm font-semibold whitespace-nowrap tabular-nums"
          aria-live="polite"
        >
          {time ? formatDateTime(time) : "Not set"}
        </span>
      </span>
    </div>
  );
}
