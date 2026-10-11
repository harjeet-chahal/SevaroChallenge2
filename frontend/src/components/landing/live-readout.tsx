"use client";

import { MonitorTrace } from "@/components/layout/ecg";
import { LiveIndicator } from "@/components/status/monitor-card";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { analysisApi } from "@/lib/api/endpoints";
import { clockParts } from "@/lib/format";

/** Backend metrics for the readout; null until the backend answers. */
export function useLandingMetrics() {
  const { config } = useSystemStatus();
  const key = config?.dataset_loaded
    ? `${config.data_version}|${config.simulation_time}|${config.workflow_version}`
    : null;
  const metrics = useKeyedResource(key, (signal) => analysisApi.metrics(signal)).data;
  const coverage = metrics?.coverage;
  return {
    critical: metrics ? (metrics.alerts_by_severity.critical ?? 0) : null,
    gaps: coverage ? Number(coverage.gap_now ?? 0) + Number(coverage.gap_projected ?? 0) : null,
    horizon: coverage?.horizon_minutes ?? null,
    pending: config ? config.pending_approvals : null,
  };
}

function Stat({ label, value, alert }: { label: string; value: number | null; alert?: boolean }) {
  return (
    <div className="min-w-0 rounded-[10px] bg-clock-fg/6 px-3 py-2.5">
      <dt className="truncate text-label opacity-65">{label}</dt>
      <dd
        className={
          "font-mono text-[30px] leading-tight font-semibold tabular-nums " +
          (value === null ? "opacity-45" : alert && value > 0 ? "text-[oklch(0.8_0.12_25)]" : "")
        }
      >
        {value ?? "—"}
      </dd>
    </div>
  );
}

/**
 * The hero's live tile: the real simulation clock and three backend figures. Nothing here
 * is scripted; with no backend or no dataset the values show a dash.
 */
export function LiveReadout() {
  const { config } = useSystemStatus();
  const clock = config?.simulation_time ? clockParts(config.simulation_time) : null;
  const m = useLandingMetrics();

  return (
    <section
      aria-label="Live network readout"
      className="relative flex flex-col gap-5 overflow-hidden rounded-3xl bg-clock-bg p-6 text-clock-fg sm:p-7"
    >
      <MonitorTrace className="top-10 h-36 opacity-90" />
      <div className="relative flex items-center justify-between gap-3 font-mono text-label tracking-[0.08em] uppercase">
        <span className="opacity-65">Simulation clock</span>
        <span className="normal-case">
          <LiveIndicator />
        </span>
      </div>
      <div className="relative">
        <p
          className="font-mono text-[64px] leading-none font-medium tracking-[-0.04em] tabular-nums sm:text-[76px]"
          aria-live="polite"
        >
          {clock?.time ?? "—:—"}
          {clock ? (
            <span className="ml-2 align-top font-sans text-base font-medium tracking-normal opacity-70">
              {clock.zone}
            </span>
          ) : null}
        </p>
        <p className="mt-2 font-mono text-label opacity-60">
          {clock ? clock.day : "No dataset loaded"}
          {config ? ` · data v${config.data_version} · wf v${config.workflow_version}` : ""}
        </p>
      </div>
      <dl className="relative grid grid-cols-3 gap-2">
        <Stat label="Critical alerts" value={m.critical} alert />
        <Stat
          label={m.horizon ? `Gaps ≤ ${m.horizon} min` : "Coverage gaps"}
          value={m.gaps}
          alert
        />
        <Stat label="Pending approvals" value={m.pending} />
      </dl>
    </section>
  );
}
