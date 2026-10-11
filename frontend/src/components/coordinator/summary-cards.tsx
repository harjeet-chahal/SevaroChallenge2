"use client";

import { Hospital, Inbox, ListChecks, OctagonAlert, Stethoscope, UserX } from "lucide-react";

import { MetricCard } from "@/components/shared/metric-card";
import { useAnalysis } from "@/components/state/analysis-provider";
import { useOperationalState } from "@/components/state/operational-state-provider";
import { useSystemStatus, type DataAvailability } from "@/components/status/system-status-provider";
import { needsCoordinator } from "@/components/workflow/status";
import { useOptionalWorkflow } from "@/components/workflow/workflow-provider";
import { formatElapsed, formatTime } from "@/lib/format";

import { useCoordinatorView } from "./view-provider";

const HINTS: Record<DataAvailability, string> = {
  checking: "Connecting…",
  offline: "Backend unreachable",
  degraded: "Backend degraded",
  "no-dataset": "Awaiting dataset",
  "awaiting-feature": "Loading…",
};

/**
 * The network at a glance, ordered by what needs attention first. Colour appears only
 * when a number is a problem, and every tile drills into the section that explains it.
 */
export function CoordinatorSummaryCards() {
  const { availability } = useSystemStatus();
  const { data } = useOperationalState();
  const { alerts, metrics } = useAnalysis();
  const workflow = useOptionalWorkflow();
  const view = useCoordinatorView();
  const summary = data?.summary ?? null;
  const hint = HINTS[availability];
  const counts = alerts.data?.counts_by_severity;
  const coverage = metrics.data?.coverage;
  const gapNow = coverage ? Number(coverage.gap_now ?? 0) : 0;
  const gapSoon = coverage ? Number(coverage.gap_projected ?? 0) : 0;
  const earliest = metrics.data?.earliest_projected_gap_at;
  const longest = metrics.data?.longest_open_wait_seconds ?? null;

  const items = workflow?.interventions.data?.items ?? null;
  const open = items?.filter((i) => !i.is_terminal) ?? [];
  const mine = open.filter(needsCoordinator).length;
  const awaitingLead = open.filter((i) => i.status === "pending_approval").length;

  return (
    <section
      aria-label="Network summary"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6"
    >
      <MetricCard
        label="Critical alerts"
        value={counts?.critical ?? null}
        hint={counts ? `${counts.warning} warning · ${counts.info} info` : hint}
        icon={OctagonAlert}
        tone={counts?.critical ? "critical" : "neutral"}
        actionLabel="Show critical alerts"
        onClick={() => {
          view.setAlertFilter(counts?.critical ? "critical" : "all");
          view.focus("triage");
        }}
      />
      <MetricCard
        label="Coverage gaps"
        value={coverage ? gapNow + gapSoon : null}
        suffix={coverage ? (gapNow + gapSoon === 1 ? "hospital" : "hospitals") : undefined}
        hint={
          !coverage
            ? hint
            : gapNow + gapSoon === 0
              ? `None in the next ${coverage.horizon_minutes} min`
              : `${gapNow} now · ${gapSoon} within ${coverage.horizon_minutes} min` +
                (earliest && !gapNow ? ` · first ${formatTime(earliest)}` : "")
        }
        icon={Hospital}
        tone={gapNow ? "critical" : gapSoon ? "warning" : "neutral"}
        actionLabel="Open the coverage forecast"
        onClick={() => view.focus("detail", "coverage")}
      />
      <MetricCard
        label="Unassigned consults"
        value={summary?.consults_open_unassigned ?? null}
        hint={summary ? `of ${summary.consults_open} open` : hint}
        icon={UserX}
        tone={summary?.consults_open_unassigned ? "warning" : "neutral"}
        actionLabel="Show unassigned consults"
        onClick={() => {
          view.setConsultFilter(summary?.consults_open_unassigned ? "unassigned" : "open");
          view.focus("detail", "consults");
        }}
      />
      <MetricCard
        label="Interventions in progress"
        value={items ? open.length : null}
        hint={
          !items
            ? hint
            : open.length === 0
              ? "Nothing in flight"
              : [
                  mine ? `${mine} need${mine === 1 ? "s" : ""} you` : null,
                  awaitingLead ? `${awaitingLead} awaiting approval` : null,
                ]
                  .filter(Boolean)
                  .join(" · ") || "Waiting on physicians"
        }
        icon={ListChecks}
        tone={mine ? "warning" : "neutral"}
        actionLabel="Go to interventions"
        onClick={() => view.focus("interventions")}
      />
      <MetricCard
        label="Physicians available"
        value={summary?.on_shift_available ?? null}
        suffix={summary ? `/ ${summary.physicians_on_shift} on shift` : undefined}
        hint={
          summary
            ? `${summary.on_shift_busy} busy · ${summary.on_shift_unavailable} unavailable`
            : hint
        }
        icon={Stethoscope}
        tone={
          summary && summary.physicians_on_shift > 0 && !summary.on_shift_available
            ? "warning"
            : "neutral"
        }
        actionLabel="Show physician activity"
        onClick={() => view.focus("detail", "physicians")}
      />
      <MetricCard
        label="Open consults"
        value={summary?.consults_open ?? null}
        hint={
          summary
            ? `${summary.consults_open_assigned} assigned` +
              (longest !== null ? ` · longest ${formatElapsed(longest)}` : "")
            : hint
        }
        icon={Inbox}
        actionLabel="Show open consults"
        onClick={() => {
          view.setConsultFilter("open");
          view.focus("detail", "consults");
        }}
      />
    </section>
  );
}
