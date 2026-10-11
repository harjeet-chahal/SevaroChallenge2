"use client";

import { BellRing, Building2, ChevronRight, Hourglass, User } from "lucide-react";

import { SectionCard } from "@/components/shared/section-card";
import { useAnalysis } from "@/components/state/analysis-provider";
import { StateFallback } from "@/components/state/state-fallback";
import { InterventionProgressBadge } from "@/components/workflow/status";
import {
  ACTION_INTERVENTION_TYPES,
  useAlertInterventions,
} from "@/components/workflow/workflow-provider";
import type { Alert, Intervention, Severity } from "@/lib/api/types";
import { formatElapsed, formatTime } from "@/lib/format";
import { ACTION_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { type AlertFilter, useCoordinatorView } from "./view-provider";

/** Elapsed time or predicted time — always from backend-computed fields. */
export function alertTiming(a: Alert): string | null {
  if (a.minutes_to_impact !== null && a.minutes_to_impact > 0 && a.impact_at) {
    const label = a.critical_after_seconds ? "critical" : "expected";
    return `${label} in ${Math.round(a.minutes_to_impact)} min (${formatTime(a.impact_at, a.hospital_timezone)})`;
  }
  if (a.elapsed_seconds !== null) return `${formatElapsed(a.elapsed_seconds)} elapsed`;
  if (a.condition_since) return `since ${formatTime(a.condition_since, a.hospital_timezone)}`;
  return null;
}

/** "Critical in 10 min": only for alerts that will get worse soon. */
function upcoming(a: Alert): string | null {
  if (a.minutes_to_impact === null || a.minutes_to_impact <= 0) return null;
  return `${a.critical_after_seconds ? "Critical" : "Due"} in ${Math.round(a.minutes_to_impact)} min`;
}

const FILTERS: AlertFilter[] = ["all", "critical", "warning", "info"];

export const SEVERITY_RAIL: Record<Severity, string> = {
  critical: "bg-critical",
  warning: "bg-warning",
  info: "bg-info",
};

const FILTER_ACTIVE: Record<AlertFilter, string> = {
  all: "border-primary bg-primary text-primary-foreground",
  critical: "border-critical bg-critical text-white",
  warning: "border-warning bg-warning text-white",
  info: "border-info bg-info text-white",
};

/**
 * True when someone is already acting on the alert (any linked intervention under way, e.g. an
 * escalation instead of the recommended reassignment) or the recommended one was completed.
 */
export function recommendationActedOn(a: Alert, linked: Intervention[]): boolean {
  const type = ACTION_INTERVENTION_TYPES[a.recommended_action_type];
  return linked.some((i) => !i.is_terminal || (i.type === type && i.status === "completed"));
}

function AlertRow({
  a,
  active,
  linked,
  onSelect,
}: {
  a: Alert;
  active: boolean;
  linked: Intervention[];
  onSelect: () => void;
}) {
  const soon = upcoming(a);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cn(
        "group relative flex w-full items-start gap-3 overflow-hidden rounded-lg border bg-card py-2.5 pr-2 pl-4 text-left transition-colors outline-none hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50",
        active && "border-primary bg-primary/5 hover:bg-primary/5",
      )}
    >
      <span
        aria-hidden
        className={cn("absolute inset-y-0 left-0 w-1", SEVERITY_RAIL[a.severity])}
      />
      <span className="sr-only">
        {a.severity} severity, priority {a.priority}.{" "}
      </span>
      <span
        aria-hidden
        className="mt-px w-4 shrink-0 text-right text-xs font-semibold text-muted-foreground tabular-nums"
      >
        {a.priority}
      </span>
      <span className="min-w-0 flex-1 space-y-1">
        <span className="line-clamp-2 text-sm leading-snug font-medium text-foreground">
          {a.title}
        </span>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          {a.hospital_name ? (
            <span className="inline-flex min-w-0 items-center gap-1">
              <Building2 className="size-3 shrink-0" aria-hidden />
              <span className="truncate">{a.hospital_name}</span>
            </span>
          ) : null}
          {a.physician_name ? (
            <span className="inline-flex items-center gap-1">
              <User className="size-3 shrink-0" aria-hidden />
              {a.physician_name}
            </span>
          ) : null}
          {soon ? (
            <span className="inline-flex items-center gap-1 font-medium text-warning">
              <Hourglass className="size-3 shrink-0" aria-hidden />
              {soon}
            </span>
          ) : null}
        </span>
        <span className="flex flex-wrap items-center gap-1.5 text-xs">
          {linked[0] ? <InterventionProgressBadge intervention={linked[0]} /> : null}
          {recommendationActedOn(a, linked) ? null : (
            <span className="font-medium text-primary">
              Next: {ACTION_LABELS[a.recommended_action_type]}
            </span>
          )}
        </span>
      </span>
      <ChevronRight
        className={cn(
          "mt-0.5 size-4 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-muted-foreground",
          active && "text-primary group-hover:text-primary",
        )}
        aria-hidden
      />
    </button>
  );
}

export function AlertQueue({ className }: { className?: string }) {
  const { alerts, selectedAlert, selectAlert } = useAnalysis();
  const { alertFilter: filter, setAlertFilter: setFilter } = useCoordinatorView();
  const linkedTo = useAlertInterventions();
  const data = alerts.data;
  const shown = data?.alerts.filter((a) => filter === "all" || a.severity === filter) ?? [];

  return (
    <SectionCard
      className={className}
      title="Needs attention"
      icon={BellRing}
      info="Live alerts ranked by the backend: severity first, then clinical urgency, elapsed time, coverage risk and workflows affected. An alert clears when the underlying problem changes."
      action={
        data ? (
          <span className="text-xs text-muted-foreground tabular-nums">
            {data.total} alert{data.total === 1 ? "" : "s"}
          </span>
        ) : null
      }
    >
      {data ? (
        <div className={cn("space-y-3", alerts.loading && "opacity-60 transition-opacity")}>
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label="Filter by severity"
          >
            {FILTERS.map((f) => {
              const count = f === "all" ? data.total : data.counts_by_severity[f];
              return (
                <button
                  key={f}
                  type="button"
                  aria-pressed={filter === f}
                  onClick={() => setFilter(f)}
                  disabled={f !== "all" && count === 0}
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-40",
                    filter === f
                      ? FILTER_ACTIVE[f]
                      : "bg-card text-muted-foreground enabled:hover:bg-muted",
                  )}
                >
                  {f} <span className="tabular-nums">{count}</span>
                </button>
              );
            })}
          </div>
          {shown.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {data.total === 0
                ? "All clear: no alerts at this simulation time."
                : "No alerts at this severity."}
            </p>
          ) : (
            <ol className="space-y-1.5 lg:max-h-[calc(100dvh-16rem)] lg:min-h-[24rem] lg:overflow-y-auto lg:pr-1">
              {shown.map((a) => (
                <li key={a.alert_id}>
                  <AlertRow
                    a={a}
                    active={selectedAlert?.alert_id === a.alert_id}
                    linked={linkedTo(a)}
                    onSelect={() => selectAlert(a.alert_id)}
                  />
                </li>
              ))}
            </ol>
          )}
          {data.notes.map((note) => (
            <p key={note} className="text-xs text-muted-foreground">
              Note: {note}
            </p>
          ))}
        </div>
      ) : (
        <StateFallback
          resource={alerts}
          feature="alert detection"
          whenNoDataset="Alerts appear once a dataset is loaded: stage-time breaches, unassigned consults, routing failures, demand spikes, coverage gaps and conflicting physician signals."
        />
      )}
    </SectionCard>
  );
}
