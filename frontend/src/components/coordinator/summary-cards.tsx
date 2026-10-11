"use client";

import { Bell, Hospital, Inbox, Stethoscope, UserX } from "lucide-react";

import { MetricCard } from "@/components/shared/metric-card";
import { formatTime } from "@/lib/format";
import { useAnalysis } from "@/components/state/analysis-provider";
import { useOperationalState } from "@/components/state/operational-state-provider";
import { useSystemStatus, type DataAvailability } from "@/components/status/system-status-provider";

const HINTS: Record<DataAvailability, string> = {
  checking: "Connecting…",
  offline: "Backend unreachable",
  degraded: "Backend degraded",
  "no-dataset": "Awaiting dataset",
  "awaiting-feature": "Loading…",
};

/** Network-wide headline figures, straight from backend state, alerts and forecasts. */
export function CoordinatorSummaryCards() {
  const { availability } = useSystemStatus();
  const { data } = useOperationalState();
  const { alerts, metrics } = useAnalysis();
  const summary = data?.summary ?? null;
  const hint = HINTS[availability];
  const counts = alerts.data?.counts_by_severity;
  const coverage = metrics.data?.coverage;
  const gaps = coverage
    ? Number(coverage.gap_now ?? 0) + Number(coverage.gap_projected ?? 0)
    : null;
  const earliest = metrics.data?.earliest_projected_gap_at;

  return (
    <section
      aria-label="Network summary"
      className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,170px),1fr))] gap-3"
    >
      <MetricCard
        label="Physicians on shift"
        value={summary?.physicians_on_shift ?? null}
        hint={
          summary
            ? `${summary.on_shift_busy} busy · ${summary.on_shift_available} available · ${summary.on_shift_unavailable} unavailable`
            : hint
        }
        icon={Stethoscope}
      />
      <MetricCard
        label="Open consults"
        value={summary?.consults_open ?? null}
        hint={summary ? `${summary.consults_open_assigned} assigned` : hint}
        icon={Inbox}
      />
      <MetricCard
        label="Unassigned consults"
        value={summary?.consults_open_unassigned ?? null}
        hint={summary ? "Open with no physician" : hint}
        risk={(summary?.consults_open_unassigned ?? 0) > 0}
        icon={UserX}
      />
      <MetricCard
        label="Open alerts"
        value={alerts.data?.total ?? null}
        hint={
          counts
            ? `${counts.critical} critical · ${counts.warning} warning · ${counts.info} info`
            : hint
        }
        icon={Bell}
        risk={(counts?.critical ?? 0) > 0}
      />
      <MetricCard
        label="Hospitals with coverage gaps"
        value={gaps}
        hint={
          coverage
            ? `${coverage.gap_now} now · ${coverage.gap_projected} within ${coverage.horizon_minutes} min` +
              (earliest ? ` (first ${formatTime(earliest)})` : "")
            : hint
        }
        icon={Hospital}
        risk={(gaps ?? 0) > 0}
      />
    </section>
  );
}
