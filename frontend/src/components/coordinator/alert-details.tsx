"use client";

import {
  ArrowRight,
  ArrowRightLeft,
  CalendarClock,
  CircleCheck,
  ClipboardList,
  Clock,
  Megaphone,
  PhoneCall,
} from "lucide-react";

import { useOptionalOptimization } from "@/components/optimization/optimization-provider";
import { RankedPhysicians } from "@/components/optimization/ranked-physicians";
import { Disclosure } from "@/components/optimization/shared";
import { InfoTip } from "@/components/shared/info-tip";
import { EYEBROW } from "@/components/shared/page-header";
import { PendingActionButton } from "@/components/shared/pending-action-button";
import { PILL_TONES, Pill } from "@/components/shared/pill";
import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { TagBadge } from "@/components/shared/status-badges";
import { useAnalysis } from "@/components/state/analysis-provider";
import { StateFallback } from "@/components/state/state-fallback";
import { Button } from "@/components/ui/button";
import { InterventionProgressBadge } from "@/components/workflow/status";
import {
  ACTION_INTERVENTION_TYPES,
  useAlertInterventions,
  useOptionalWorkflow,
} from "@/components/workflow/workflow-provider";
import type { Alert, Intervention, RecommendedAction } from "@/lib/api/types";
import { formatDuration, formatElapsed, formatElapsedPrecise, formatTime } from "@/lib/format";
import { ACTION_LABELS, INTERVENTION_STATUS_LABELS, recommendationLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { SEVERITY_RAIL, alertTiming } from "./alert-queue";
import { SECTION_IDS } from "./section-ids";
import { scrollToSection } from "./view-provider";

const ACTION_ICONS: Record<RecommendedAction, React.ComponentType<{ className?: string }>> = {
  reassign_consult: ArrowRightLeft,
  escalate: Megaphone,
  contact_physician: PhoneCall,
  propose_split_shift: CalendarClock,
  monitor: ClipboardList,
};

const WORKFLOW_ACTIONS = ["reassign_consult", "escalate", "propose_split_shift"] as const;

/**
 * Elapsed time against the warning and critical standards. The scale stops a little past
 * the critical standard so both marks stay readable; how far past it is said in words.
 */
function StandardMeter({ a }: { a: Alert }) {
  const elapsed = a.elapsed_seconds;
  const warning = a.warning_after_seconds;
  const critical = a.critical_after_seconds;
  if (elapsed === null || warning === null || critical === null) return null;
  const max = critical * 1.25;
  const pct = (s: number) => Math.min(100, (s / max) * 100);
  const status =
    elapsed >= critical
      ? { text: `${formatElapsed(elapsed - critical)} past critical`, tone: "text-critical-ink" }
      : elapsed >= warning
        ? { text: `critical in ${formatElapsed(critical - elapsed)}`, tone: "text-warning-ink" }
        : { text: `warning in ${formatElapsed(warning - elapsed)}`, tone: "text-muted-foreground" };

  return (
    <div
      role="img"
      aria-label={`${formatElapsed(elapsed)} elapsed, ${status.text}; warning at ${formatElapsed(warning)}, critical at ${formatElapsed(critical)}`}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className={EYEBROW}>Against standard</span>
        <span className={cn("font-mono text-caption font-medium tabular-nums", status.tone)}>
          {status.text}
        </span>
      </div>
      <div className="relative mt-2.5 h-2 rounded-full bg-border">
        <div
          className={cn(
            "absolute inset-y-0 left-0 origin-left animate-ng-fill rounded-full",
            SEVERITY_RAIL[a.severity],
          )}
          style={{ width: `${pct(elapsed)}%` }}
        />
        <span aria-hidden className="absolute -inset-y-1.5 left-0 w-0.5 rounded-full bg-foreground" />
        <span
          aria-hidden
          className="absolute -inset-y-1.5 w-0.5 rounded-full bg-warning"
          style={{ left: `${pct(warning)}%` }}
        />
        <span
          aria-hidden
          className="absolute -inset-y-1.5 w-0.5 rounded-full bg-critical"
          style={{ left: `${pct(critical)}%` }}
        />
      </div>
      <p aria-hidden className="mt-2 flex gap-4 text-micro text-muted-foreground uppercase">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-0.5 rounded-full bg-warning" />
          Warning {formatElapsed(warning)}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-0.5 rounded-full bg-critical" />
          Critical {formatElapsed(critical)}
        </span>
      </p>
    </div>
  );
}

function viewIntervention(select: ((id: string) => void) | undefined, id: string) {
  select?.(id);
  scrollToSection(SECTION_IDS.interventions);
}

/**
 * For a coverage gap: the backend's ranked physicians for this hospital, top three, so the
 * coordinator sees who would be asked (and any volunteer who moved up) before proposing.
 */
function WhoToAsk({ a }: { a: Alert }) {
  const optimization = useOptionalOptimization();
  const ranking = optimization?.staffing.data?.rankings.find(
    (r) => r.hospital_ids.length === 1 && r.hospital_ids[0] === a.hospital_id,
  );
  if (!a.hospital_id || !a.rule_code.startsWith("COVERAGE_GAP") || !ranking) return null;
  if (!ranking.entries.some((e) => e.rank !== null)) return null;
  return (
    <RankedPhysicians
      ranking={ranking}
      tz={a.hospital_timezone}
      compact
      limit={3}
      title="Who to ask first"
    />
  );
}

const PROPOSAL_NOTE =
  "Opens a proposal checked against the current data. Nobody is contacted until a clinical lead approves.";

/**
 * The one thing to do next: the recommendation and its button, what is already under way,
 * or what handled it. Other actions stay available but quiet.
 */
function NextStep({ a, linked }: { a: Alert; linked: Intervention[] }) {
  const workflow = useOptionalWorkflow();
  const inFlight = linked.filter((i) => !i.is_terminal);
  const doneBy = a.handled_by ? linked.find((i) => i.id === a.handled_by) : undefined;
  // Under way or handled: don't keep pushing the recommendation (e.g. after escalating).
  const settled = inFlight.length > 0 || Boolean(a.handled_by);
  const RecommendedIcon = ACTION_ICONS[a.recommended_action_type];

  // The recommended action first; actions that cannot apply to this alert are left out.
  const actions = [...WORKFLOW_ACTIONS]
    .sort(
      (x, y) => Number(y === a.recommended_action_type) - Number(x === a.recommended_action_type),
    )
    .filter((action) =>
      action === "reassign_consult"
        ? Boolean(a.consult_id)
        : action === "propose_split_shift"
          ? Boolean(a.hospital_id)
          : true,
    );

  const buttons = actions.map((action) => {
    const Icon = ACTION_ICONS[action];
    const type = ACTION_INTERVENTION_TYPES[action]!;
    const open = linked.find((i) => i.type === type && !i.is_terminal);
    const done = linked.some((i) => i.type === type && i.status === "completed");
    const label =
      action === "escalate"
        ? done
          ? "Escalate again"
          : "Request escalation"
        : action === "reassign_consult"
          ? done
            ? "Reassign again"
            : "Propose reassignment"
          : done
            ? "Another split shift"
            : ACTION_LABELS[action];
    const unavailable = !workflow
      ? "Open the coordinator view to propose interventions."
      : open
        ? `${open.id} is already ${INTERVENTION_STATUS_LABELS[open.status].toLowerCase()}.`
        : null;
    if (unavailable) {
      return (
        <PendingActionButton
          key={action}
          label={label}
          icon={Icon}
          size="sm"
          variant="ghost"
          reason={unavailable}
        />
      );
    }
    const primary = action === a.recommended_action_type && !done && !settled;
    return (
      <Button
        key={action}
        size={primary ? "lg" : "sm"}
        variant={primary ? "default" : "ghost"}
        title={PROPOSAL_NOTE}
        className={primary ? "mr-1" : undefined}
        onClick={() =>
          workflow!.openComposer({
            type,
            alertId: a.alert_id,
            consultId: a.consult_id,
            hospitalIds:
              action === "propose_split_shift" && a.hospital_id ? [a.hospital_id] : undefined,
          })
        }
      >
        <Icon aria-hidden />
        {label}
        {primary ? <ArrowRight data-icon="inline-end" aria-hidden /> : null}
      </Button>
    );
  });

  const tone = inFlight.length
    ? "border-info-border bg-info-soft"
    : a.handled_by
      ? "border-success-border bg-success-soft"
      : "border-primary/30 bg-primary/8";

  return (
    <div className={cn("space-y-3 rounded-[10px] border px-3.5 py-3", tone)}>
      {inFlight.length ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-info-ink uppercase">
            In progress
          </p>
          <ul className="space-y-1.5">
            {inFlight.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-2">
                <InterventionProgressBadge intervention={i} />
                <Button
                  variant="link"
                  size="xs"
                  className="h-auto px-0"
                  onClick={() => viewIntervention(workflow?.select, i.id)}
                >
                  View {i.id}
                </Button>
                {i.status_reason ? (
                  <span className="basis-full text-xs text-muted-foreground">
                    {i.status_reason}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : a.handled_by ? (
        <div className="space-y-1.5">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-success-ink uppercase">
            Handled
          </p>
          <p className="flex flex-wrap items-center gap-2">
            {doneBy ? <InterventionProgressBadge intervention={doneBy} /> : null}
            <Button
              variant="link"
              size="xs"
              className="h-auto px-0"
              onClick={() => viewIntervention(workflow?.select, a.handled_by!)}
            >
              View {a.handled_by}
            </Button>
          </p>
          <p className="text-caption text-foreground-2">
            Moved below the open queue. The condition is still in the live data, so act again
            only if more is needed.
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-primary-ink uppercase">
            Recommended
          </p>
          <p className="flex items-center gap-1.5 text-base font-semibold text-foreground">
            <RecommendedIcon className="size-4 text-primary-ink" aria-hidden />
            {recommendationLabel(a)}
          </p>
          <p className="text-caption text-foreground-2">{a.recommended_action_reason}</p>
          {a.recommended_action_type === "contact_physician" ? (
            <p className="text-caption text-muted-foreground">
              A direct call or message from you; Sevaro Pulse doesn&apos;t contact anyone for this
              step.
              {/* An escalation must name a consult or hospital; physician-only signals have neither. */}
              {a.consult_id || a.hospital_id
                ? " If they can't be reached, request an escalation below."
                : null}
            </p>
          ) : null}
        </div>
      )}

      {settled ? null : <WhoToAsk a={a} />}

      {buttons.length ? (
        <div className="flex flex-wrap items-center gap-1">{buttons}</div>
      ) : null}
    </div>
  );
}

/** Earlier interventions about the same problem that have finished. */
function History({ a, linked }: { a: Alert; linked: Intervention[] }) {
  const workflow = useOptionalWorkflow();
  // The intervention that handled the alert is already shown in the next-step box.
  const closed = linked.filter((i) => i.is_terminal && i.id !== a.handled_by);
  if (!closed.length) return null;
  return (
    <div className="space-y-1.5">
      <h3 className={cn("flex items-center gap-1", EYEBROW)}>
        Earlier on this problem
        <InfoTip label="Why the alert is still open">
          Alerts come from the live data, so this one stays until the problem itself changes (for
          example, a doctor is assigned to the consult). Completing an escalation records the
          clinical lead&apos;s action; it does not change the consult.
        </InfoTip>
      </h3>
      <ul className="space-y-1">
        {closed.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-1.5 text-xs">
            <InterventionProgressBadge intervention={i} />
            <button
              type="button"
              className="font-mono text-primary-ink underline-offset-2 hover:underline"
              onClick={() => viewIntervention(workflow?.select, i.id)}
            >
              {i.id}
            </button>
            <span className="text-muted-foreground">
              updated {formatTime(i.updated_at, a.hospital_timezone)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The big readout shows elapsed time (not a countdown to impact). */
function showsElapsed(a: Alert): boolean {
  return !(a.minutes_to_impact !== null && a.minutes_to_impact > 0) && a.elapsed_seconds !== null;
}

/**
 * The title without what the panel already shows above and below it: a leading
 * "<consult | hospital | physician>: " (in the subject line) and, beside the elapsed readout,
 * a trailing " — 1 h 13 min".
 */
function headline(a: Alert): string {
  let text = a.title;
  for (const prefix of [a.consult_id, a.hospital_name, a.physician_name]) {
    if (prefix && text.startsWith(`${prefix}: `)) {
      text = text.slice(prefix.length + 2);
      break;
    }
  }
  if (showsElapsed(a)) {
    text = text.replace(/\s+—\s+(\d+\s*h(\s+\d+\s*min)?|\d+\s*min|\d+\s*s)$/, "");
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Big readout of how long the condition has run (or how soon it bites), from backend fields. */
function Countdown({ a }: { a: Alert }) {
  const tone =
    a.severity === "critical"
      ? "text-critical-ink"
      : a.severity === "warning"
        ? "text-warning-ink"
        : "text-foreground";
  if (a.minutes_to_impact !== null && a.minutes_to_impact > 0) {
    return (
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className={cn(
            "font-mono text-[40px] leading-none font-semibold tracking-[-0.03em] tabular-nums",
            tone,
          )}
        >
          {formatDuration(Math.round(a.minutes_to_impact))}
        </span>
        <span className="text-caption text-muted-foreground">
          until {a.critical_after_seconds ? "critical" : "impact"}
          {a.impact_at ? ` · ${formatTime(a.impact_at, a.hospital_timezone)}` : ""}
        </span>
      </p>
    );
  }
  if (a.elapsed_seconds === null) return null;
  return (
    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span
        className={cn(
          "font-mono text-[40px] leading-none font-semibold tracking-[-0.03em] tabular-nums",
          tone,
        )}
      >
        {formatElapsedPrecise(a.elapsed_seconds)}
      </span>
      <span className="text-caption text-muted-foreground">
        elapsed
        {a.condition_since ? ` · since ${formatTime(a.condition_since, a.hospital_timezone)}` : ""}
      </span>
    </p>
  );
}

const INFO =
  "Why the selected alert fired and which intervention fits. Actions open a server-validated proposal; nothing is sent until a clinical lead approves.";

/**
 * The selected alert as the page's hero: what is wrong, how late it is, what to do next —
 * then the rule, evidence and assumptions on demand. A severity rail runs down the left.
 */
export function AlertDetails({ className }: { className?: string }) {
  const { alerts, selectedAlert: a } = useAnalysis();
  const linkedTo = useAlertInterventions();
  const linked = a ? linkedTo(a) : [];

  if (!alerts.data || !a) {
    return (
      <SectionCard className={className} title="Priority one" icon={ClipboardList} info={INFO}>
        {!alerts.data ? (
          <StateFallback
            resource={alerts}
            feature="alert detection"
            whenNoDataset="The most urgent alert appears here once a dataset is loaded."
          />
        ) : (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Nothing needs attention at this simulation time.
          </p>
        )}
      </SectionCard>
    );
  }

  const top = a.priority === 1 && !a.handled_by;

  return (
    <section
      aria-labelledby="alert-detail-title"
      className={cn(
        "relative min-w-0 overflow-hidden rounded-xl bg-card ring-1",
        a.severity === "critical" && !a.handled_by ? "ring-critical-border" : "ring-border",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute inset-y-0 left-0 w-1",
          a.handled_by ? "bg-success" : SEVERITY_RAIL[a.severity],
        )}
      />
      <div className="space-y-4 py-5 pr-5 pl-6 text-sm sm:py-6 sm:pr-6 sm:pl-7">
        <div className="flex flex-wrap items-center gap-1.5">
          {a.handled_by ? (
            <Pill tone="success" icon={CircleCheck} className="font-semibold">
              Handled
            </Pill>
          ) : (
            <span
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold tracking-[0.1em] uppercase",
                PILL_TONES[a.severity],
              )}
            >
              {top ? "Priority one" : `Priority ${a.priority}`}
            </span>
          )}
          <SeverityBadge severity={a.severity} />
          <InfoTip label="About this panel" className="ml-auto">
            {INFO}
          </InfoTip>
        </div>

        <div className="space-y-2">
          <p className="flex flex-wrap items-center gap-x-1.5 text-[13px] text-muted-foreground">
            {[a.consult_id, a.hospital_name, a.physician_name]
              .filter(Boolean)
              .map((part, i) => (
                <span key={part} className={cn(i === 0 && a.consult_id && "font-mono")}>
                  {i > 0 ? <span aria-hidden className="mr-1.5">·</span> : null}
                  {part}
                </span>
              ))}
          </p>
          <h2
            id="alert-detail-title"
            title={a.title}
            className="text-2xl leading-tight font-semibold text-pretty text-foreground"
          >
            {headline(a)}
          </h2>
          <Countdown a={a} />
          <p className="max-w-[680px] text-body text-foreground-2">{a.summary}</p>
        </div>

        <StandardMeter a={a} />
        {a.warning_after_seconds === null && alertTiming(a) ? (
          <p className="flex items-center gap-1.5 text-caption text-muted-foreground">
            <Clock className="size-3.5" aria-hidden />
            {alertTiming(a)}
          </p>
        ) : null}

        <NextStep a={a} linked={linked} />
        <History a={a} linked={linked} />

        <div className="space-y-2">
          <Disclosure summary="Why this alert and this priority">
            <p className="font-medium">
              {a.rule_name}{" "}
              <span className="font-mono text-xs text-muted-foreground">({a.rule_code})</span>
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <TagBadge tone={a.rule_source === "challenge_brief" ? "success" : "warning"}>
                {a.rule_source === "challenge_brief"
                  ? "From the challenge brief"
                  : "Documented assumption"}
              </TagBadge>
            </div>
            <p className="text-xs text-muted-foreground">{a.rule_reference}</p>
            <p className="text-xs">
              <span className="font-medium">Severity: </span>
              {a.severity_reason}
            </p>
            <ul className="list-disc space-y-0.5 pl-4 text-xs">
              {a.priority_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </Disclosure>

          <Disclosure summary={`Evidence (${a.evidence.length})`}>
            <dl className="space-y-1.5 text-xs">
              {a.evidence.map((e, i) => (
                <div key={`${e.label}-${i}`}>
                  <dt className="font-medium text-foreground">
                    {e.label}
                    {e.at ? (
                      <span className="font-mono font-normal text-muted-foreground">
                        {" "}
                        · {formatTime(e.at, a.hospital_timezone, true)}
                      </span>
                    ) : null}
                  </dt>
                  <dd className="break-words text-muted-foreground">{e.value}</dd>
                </div>
              ))}
            </dl>
            {a.event_ids.length ? (
              <p className="text-xs text-muted-foreground">
                Source events: <span className="font-mono">{a.event_ids.join(", ")}</span>
              </p>
            ) : null}
          </Disclosure>

          {a.assumptions.length ? (
            <Disclosure summary={`Assumptions (${a.assumptions.length})`}>
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                {a.assumptions.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </Disclosure>
          ) : null}
        </div>
      </div>
    </section>
  );
}
