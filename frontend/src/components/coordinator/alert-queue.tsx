"use client";

import { BellRing, Building2, ChevronRight, CircleCheck, Hourglass, User } from "lucide-react";

import { SectionCard } from "@/components/shared/section-card";
import { useAnalysis } from "@/components/state/analysis-provider";
import { StateFallback } from "@/components/state/state-fallback";
import { InterventionProgressBadge } from "@/components/workflow/status";
import {
  ACTION_INTERVENTION_TYPES,
  useAlertInterventions,
  useOptionalWorkflow,
} from "@/components/workflow/workflow-provider";
import type { Alert, Intervention, Severity } from "@/lib/api/types";
import { formatElapsed, formatTime } from "@/lib/format";
import { recommendationLabel } from "@/lib/labels";
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
  all: "border-foreground bg-foreground text-background",
  critical: "border-critical-border bg-critical-soft text-critical-ink",
  warning: "border-warning-border bg-warning-soft text-warning-ink",
  info: "border-info-border bg-info-soft text-info-ink",
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
        "group relative flex w-full items-start gap-3 overflow-hidden rounded-[10px] border border-border bg-card py-2.5 pr-2 pl-4 text-left outline-none hover:border-border-strong focus-visible:ring-3 focus-visible:ring-ring/50",
        active && "border-primary-border bg-primary-soft hover:border-primary-border",
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
        className="mt-px w-5 shrink-0 text-right font-mono text-xs font-semibold text-muted-foreground tabular-nums"
      >
        {a.priority}
      </span>
      <span className="min-w-0 flex-1 space-y-1">
        <span className="line-clamp-2 text-sm leading-snug font-medium text-foreground">
          {a.title}
        </span>
        <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-caption text-muted-foreground">
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
            <span className="inline-flex items-center gap-1 font-medium text-warning-ink">
              <Hourglass className="size-3 shrink-0" aria-hidden />
              {soon}
            </span>
          ) : null}
        </span>
        <span className="flex flex-wrap items-center gap-1.5 text-xs">
          {linked[0] ? <InterventionProgressBadge intervention={linked[0]} /> : null}
          {recommendationActedOn(a, linked) ? null : (
            <span className="font-medium text-primary-ink">
              Next: {recommendationLabel(a)}
            </span>
          )}
        </span>
      </span>
      <ChevronRight
        className={cn(
          "mt-0.5 size-4 shrink-0 text-faint-foreground/60 transition-colors group-hover:text-muted-foreground",
          active && "text-primary-ink group-hover:text-primary-ink",
        )}
        aria-hidden
      />
    </button>
  );
}

/** A problem already dealt with: muted, one line, with the intervention that handled it. */
function HandledRow({
  a,
  active,
  done,
  onSelect,
}: {
  a: Alert;
  active: boolean;
  done: Intervention | undefined;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-[10px] border border-border-subtle px-3 py-2 text-left outline-none hover:border-border-strong focus-visible:ring-3 focus-visible:ring-ring/50",
        active && "border-primary-border bg-primary-soft",
      )}
    >
      <CircleCheck className="size-4 shrink-0 text-success-ink" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-foreground-2">{a.title}</span>
        <span className="block truncate text-caption text-muted-foreground">
          {[a.hospital_name, done ? `${done.id} completed` : null].filter(Boolean).join(" · ")}
        </span>
      </span>
    </button>
  );
}

export function AlertQueue({ className }: { className?: string }) {
  const { alerts, selectedAlert, selectAlert } = useAnalysis();
  const { alertFilter: filter, setAlertFilter: setFilter } = useCoordinatorView();
  const linkedTo = useAlertInterventions();
  const workflow = useOptionalWorkflow();
  const data = alerts.data;
  const open = data?.alerts.filter((a) => !a.handled_by) ?? [];
  const handled = data?.alerts.filter((a) => a.handled_by) ?? [];
  const shown = open.filter((a) => filter === "all" || a.severity === filter);
  const byId = (id: string | null) =>
    workflow?.interventions.data?.items.find((i) => i.id === id);

  return (
    <SectionCard
      className={className}
      title="Needs attention"
      icon={BellRing}
      info="Live alerts ranked by the backend: severity first, then clinical urgency, elapsed time, coverage risk and workflows affected. When every intervention about a problem has finished and one completed, it moves to Handled and the rest move up."
      action={
        data ? (
          <span className="font-mono text-caption text-muted-foreground tabular-nums">
            {data.open_total} open
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
              const count = f === "all" ? data.open_total : data.counts_by_severity[f];
              return (
                <button
                  key={f}
                  type="button"
                  aria-pressed={filter === f}
                  onClick={() => setFilter(f)}
                  disabled={f !== "all" && count === 0}
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-label font-medium capitalize outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-40",
                    filter === f
                      ? FILTER_ACTIVE[f]
                      : "border-border bg-card text-muted-foreground enabled:hover:border-border-strong enabled:hover:text-foreground",
                  )}
                >
                  {f} <span className="font-mono tabular-nums">{count}</span>
                </button>
              );
            })}
          </div>
          <div className="space-y-3 lg:max-h-[calc(100dvh-16rem)] lg:min-h-[24rem] lg:overflow-y-auto lg:pr-1">
            {shown.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {data.open_total === 0
                  ? handled.length
                    ? "All clear: every alert has been handled."
                    : "All clear: no alerts at this simulation time."
                  : "No open alerts at this severity."}
              </p>
            ) : (
              <ol className="space-y-1.5">
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
            {handled.length ? (
              <details
                className="group"
                open={handled.some((a) => a.alert_id === selectedAlert?.alert_id) || undefined}
              >
                <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-[9px] py-1 text-label font-semibold tracking-[0.12em] text-muted-foreground uppercase outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
                  <ChevronRight
                    className="size-3.5 transition-transform group-open:rotate-90"
                    aria-hidden
                  />
                  Handled
                  <span className="font-mono tabular-nums">{handled.length}</span>
                </summary>
                <ul className="mt-1.5 space-y-1.5">
                  {handled.map((a) => (
                    <li key={a.alert_id}>
                      <HandledRow
                        a={a}
                        active={selectedAlert?.alert_id === a.alert_id}
                        done={byId(a.handled_by)}
                        onSelect={() => selectAlert(a.alert_id)}
                      />
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
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
