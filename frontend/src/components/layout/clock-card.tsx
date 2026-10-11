"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { simulationApi } from "@/lib/api/endpoints";
import { describeError } from "@/lib/api/errors";
import { formatDay, formatHm, zoneAbbr } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ClockTrace } from "./heartbeat";

/** Network-level times are Eastern (the scenario's reference zone). */
const ET = "America/New_York";

const STEPS = [
  { label: "+5", minutes: 5 },
  { label: "+15", minutes: 15 },
  { label: "+60", minutes: 60 },
  { label: "reset", minutes: 0 },
] as const;

function useClockControls() {
  const { config, refresh } = useSystemStatus();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function step(label: string, minutes: number) {
    setBusy(label);
    setError(null);
    try {
      if (minutes) await simulationApi.advance(minutes);
      else await simulationApi.reset();
      refresh();
    } catch (e) {
      setError(describeError(e));
    } finally {
      setBusy(null);
    }
  }
  return { config, busy, error, step, disabled: !config?.dataset_loaded || busy !== null };
}

function StepButtons({ className }: { className?: string }) {
  const { busy, error, step, disabled } = useClockControls();
  return (
    <>
      <div
        role="group"
        aria-label="Simulation clock controls"
        className={cn("grid grid-cols-4 gap-0.5 rounded-[9px] bg-clock-fg/8 p-0.5", className)}
      >
        {STEPS.map((s) => (
          <button
            key={s.label}
            type="button"
            disabled={disabled}
            onClick={() => step(s.label, s.minutes)}
            aria-label={s.minutes ? `Advance simulation ${s.minutes} minutes` : "Reset simulation clock"}
            title={s.minutes ? `Advance simulation ${s.minutes} minutes` : "Reset simulation clock"}
            className="flex h-7 items-center justify-center rounded-[7px] font-mono text-xs text-clock-fg/85 transition-colors hover:bg-clock-fg/14 hover:text-clock-fg disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy === s.label ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : s.label}
          </button>
        ))}
      </div>
      {error ? <p className="relative text-label text-clock-fg/80">{error}</p> : null}
    </>
  );
}

/** The signature "monitor" card: the simulation clock — never the wall clock. */
export function ClockCard({ className }: { className?: string }) {
  const { config, live } = useSystemStatus();
  const t = config?.simulation_time;
  return (
    <div
      role="group"
      aria-label="Simulation clock"
      className={cn(
        "relative flex flex-col gap-2.5 overflow-hidden rounded-2xl bg-clock-bg px-4 pt-4 pb-3.5 text-clock-fg",
        className,
      )}
    >
      <ClockTrace />
      <div className="relative flex items-center justify-between text-label">
        <span className="opacity-65">Simulation · {t ? zoneAbbr(t, ET) : "ET"}</span>
        <span className="flex items-center gap-1.5 opacity-80">
          <span
            aria-hidden
            className={cn(
              "size-1.5 rounded-full",
              live === "connected" ? "animate-ng-pulse bg-success [animation-duration:2s]" : "bg-clock-fg/50",
            )}
          />
          {live === "connected" ? "live" : "polling"}
        </span>
      </div>
      <span
        aria-live="polite"
        className="relative mt-1.5 font-mono text-[44px] leading-none font-medium tracking-[-0.04em] tabular-nums"
      >
        {t ? formatHm(t, ET) : "--:--"}
      </span>
      <div className="relative text-label tabular-nums opacity-60">
        {t ? formatDay(t, ET) : "Clock not set"}
        {config?.dataset_loaded ? ` · data v${config.data_version} · wf v${config.workflow_version}` : " · no dataset"}
      </div>
      <StepButtons className="relative" />
    </div>
  );
}

/** Compact clock for the top bar (mobile and the role views). */
export function ClockPill({ className }: { className?: string }) {
  const { config } = useSystemStatus();
  const t = config?.simulation_time;
  return (
    <span
      aria-label="Simulation time"
      className={cn("flex items-baseline gap-1.5 rounded-lg bg-clock-bg px-2.5 py-1.5 text-clock-fg", className)}
    >
      <span className="font-mono text-[15px] font-medium tabular-nums">{t ? formatHm(t, ET) : "--:--"}</span>
      <span className="text-[11px] opacity-75">{t ? zoneAbbr(t, ET) : "ET"}</span>
    </span>
  );
}

/** Mobile strip with the clock controls (the sidebar card is hidden below 900px). */
export function MobileClockControls({ className }: { className?: string }) {
  return (
    <div className={cn("rounded-xl bg-clock-bg p-2 text-clock-fg", className)}>
      <StepButtons />
    </div>
  );
}
