"use client";

import { BellRing, Building2, Clock, Stethoscope, User } from "lucide-react";
import { useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { TagBadge } from "@/components/shared/status-badges";
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

const FILTERS: (Severity | "all")[] = ["all", "critical", "warning", "info"];

/** True when the recommended intervention is already under way or was completed. */
export function recommendationActedOn(a: Alert, linked: Intervention[]): boolean {
  const type = ACTION_INTERVENTION_TYPES[a.recommended_action_type];
  return linked.some((i) => i.type === type && (!i.is_terminal || i.status === "completed"));
}

export function AlertQueue({ className }: { className?: string }) {
  const { alerts, selectedAlert, selectAlert } = useAnalysis();
  const linkedTo = useAlertInterventions();
  const [filter, setFilter] = useState<Severity | "all">("all");
  const data = alerts.data;
  const shown = data?.alerts.filter((a) => filter === "all" || a.severity === filter) ?? [];

  return (
    <SectionCard
      className={className}
      title="Alert queue"
      icon={BellRing}
      description="Ranked by the backend: severity first, then clinical urgency, elapsed time, coverage risk and workflows affected. Select an alert to see why."
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
                  className={cn(
                    "rounded-full border px-2.5 py-0.5 text-xs font-medium capitalize outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                    filter === f
                      ? "border-primary bg-primary text-primary-foreground"
                      : "bg-card text-muted-foreground hover:bg-muted",
                  )}
                >
                  {f} · {count}
                </button>
              );
            })}
          </div>
          {shown.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              {data.total === 0
                ? "No alerts at this simulation time."
                : "No alerts at this severity."}
            </p>
          ) : (
            <ol className="max-h-[34rem] space-y-2 overflow-y-auto pr-1">
              {shown.map((a) => {
                const active = selectedAlert?.alert_id === a.alert_id;
                const timing = alertTiming(a);
                const linked = linkedTo(a);
                return (
                  <li key={a.alert_id}>
                    <button
                      type="button"
                      onClick={() => selectAlert(a.alert_id)}
                      aria-pressed={active}
                      className={cn(
                        "w-full rounded-lg border bg-card p-3 text-left transition-colors outline-none hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50",
                        active && "border-primary ring-1 ring-primary/40",
                      )}
                    >
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 w-6 shrink-0 text-right text-xs font-semibold text-muted-foreground tabular-nums">
                          {a.priority}
                        </span>
                        <div className="min-w-0 flex-1 space-y-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <SeverityBadge severity={a.severity} />
                            <span className="text-sm font-semibold text-navy">{a.title}</span>
                          </div>
                          <p className="line-clamp-2 text-sm text-muted-foreground">{a.summary}</p>
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                            {a.hospital_name ? (
                              <span className="inline-flex items-center gap-1">
                                <Building2 className="size-3" aria-hidden />
                                {a.hospital_name}
                              </span>
                            ) : null}
                            {a.consult_id ? (
                              <span className="inline-flex items-center gap-1">
                                <Stethoscope className="size-3" aria-hidden />
                                {a.consult_id}
                              </span>
                            ) : null}
                            {a.physician_name ? (
                              <span className="inline-flex items-center gap-1">
                                <User className="size-3" aria-hidden />
                                {a.physician_name}
                              </span>
                            ) : null}
                            {timing ? (
                              <span className="inline-flex items-center gap-1">
                                <Clock className="size-3" aria-hidden />
                                {timing}
                              </span>
                            ) : null}
                            {linked[0] ? <InterventionProgressBadge intervention={linked[0]} /> : null}
                            {recommendationActedOn(a, linked) ? null : (
                              <TagBadge tone="info">
                                {ACTION_LABELS[a.recommended_action_type]}
                              </TagBadge>
                            )}
                          </div>
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
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
