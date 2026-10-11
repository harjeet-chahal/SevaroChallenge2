"use client";

import {
  ArrowRightLeft,
  Building2,
  CalendarClock,
  ClipboardList,
  Clock,
  Megaphone,
  PhoneCall,
  Stethoscope,
  User,
} from "lucide-react";

import { useOptionalOptimization } from "@/components/optimization/optimization-provider";
import { RankedPhysicians } from "@/components/optimization/ranked-physicians";
import { Disclosure } from "@/components/optimization/shared";
import { InfoTip } from "@/components/shared/info-tip";
import { PendingActionButton } from "@/components/shared/pending-action-button";
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
import { formatElapsed, formatTime } from "@/lib/format";
import { ACTION_LABELS, INTERVENTION_STATUS_LABELS } from "@/lib/labels";
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

function Fact({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-xs text-muted-foreground">
        <Icon className="size-3" aria-hidden />
        {label}
      </dt>
      <dd className="truncate text-sm font-medium">{children}</dd>
    </div>
  );
}

/** Where a marker label sits so it never overflows the track. */
function labelShift(pct: number): string {
  if (pct > 85) return "-100%";
  if (pct < 10) return "0";
  return "-50%";
}

/** Elapsed time against the warning and critical standards, as one bar. */
function StandardMeter({ a }: { a: Alert }) {
  if (
    a.elapsed_seconds === null ||
    a.warning_after_seconds === null ||
    a.critical_after_seconds === null
  ) {
    return null;
  }
  const max = Math.max(a.elapsed_seconds, a.critical_after_seconds) * 1.15;
  const pct = (s: number) => Math.min(100, (s / max) * 100);
  const markers = [
    {
      at: a.warning_after_seconds,
      label: `warning ${formatElapsed(a.warning_after_seconds)}`,
      tone: "bg-warning",
    },
    {
      at: a.critical_after_seconds,
      label: `critical ${formatElapsed(a.critical_after_seconds)}`,
      tone: "bg-critical",
    },
  ];
  return (
    <div
      role="img"
      aria-label={`${formatElapsed(a.elapsed_seconds)} elapsed; warning at ${formatElapsed(a.warning_after_seconds)}, critical at ${formatElapsed(a.critical_after_seconds)}`}
    >
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-muted-foreground">Time against standard</span>
        <span className="font-semibold tabular-nums">{alertTiming(a)}</span>
      </div>
      <div className="relative mt-1.5 h-2 rounded-full bg-muted">
        <div
          className={cn("absolute inset-y-0 left-0 rounded-full", SEVERITY_RAIL[a.severity])}
          style={{ width: `${pct(a.elapsed_seconds)}%` }}
        />
        {markers.map((m) => (
          <span
            key={m.label}
            aria-hidden
            className={cn("absolute -inset-y-1 w-0.5 rounded-full", m.tone)}
            style={{ left: `${pct(m.at)}%` }}
          />
        ))}
      </div>
      <div aria-hidden className="relative mt-1 h-4 text-[0.6875rem] text-muted-foreground">
        {markers.map((m) => (
          <span
            key={m.label}
            className="absolute whitespace-nowrap"
            style={{ left: `${pct(m.at)}%`, transform: `translateX(${labelShift(pct(m.at))})` }}
          >
            {m.label}
          </span>
        ))}
      </div>
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

/** The one thing to do next: the recommendation and its button, or what is already under way. */
function NextStep({ a, linked }: { a: Alert; linked: Intervention[] }) {
  const workflow = useOptionalWorkflow();
  const inFlight = linked.filter((i) => !i.is_terminal);
  const recommendedType = ACTION_INTERVENTION_TYPES[a.recommended_action_type];
  // Any intervention under way counts: after escalating, don't keep pushing a reassignment.
  const handled = inFlight.length > 0;
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
            ? "Propose another reassignment"
            : "Propose reassignment"
          : done
            ? "Propose another split shift"
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
          reason={unavailable}
        />
      );
    }
    const primary = action === a.recommended_action_type && !done && !handled;
    return (
      <Button
        key={action}
        size={primary ? "default" : "sm"}
        variant={primary ? "default" : "outline"}
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
      </Button>
    );
  });

  return (
    <div
      className={cn(
        "space-y-3 rounded-lg border p-3",
        handled ? "border-info-border bg-info-soft/60" : "border-primary/30 bg-primary/5",
      )}
    >
      {inFlight.length ? (
        <div className="space-y-2">
          <p className="text-xs font-semibold tracking-wide text-info uppercase">In progress</p>
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
      ) : null}

      {handled ? null : (
        <div className="space-y-1">
          <p className="text-xs font-semibold tracking-wide text-primary uppercase">
            Recommended next step
          </p>
          <p className="flex items-center gap-1.5 font-semibold text-navy">
            <RecommendedIcon className="size-4 text-primary" aria-hidden />
            {ACTION_LABELS[a.recommended_action_type]}
          </p>
          <p className="text-xs text-muted-foreground">{a.recommended_action_reason}</p>
        </div>
      )}

      {handled ? null : <WhoToAsk a={a} />}

      {buttons.length ? (
        <div className="space-y-1.5">
          {handled || !recommendedType ? (
            <p className="text-xs text-muted-foreground">
              {handled ? "Other options" : "Or start an intervention"}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">{buttons}</div>
        </div>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Opens a proposal checked against the current data. Nobody is contacted until a clinical lead
        approves.
      </p>
    </div>
  );
}

/** Earlier interventions about the same problem that have finished. */
function History({ a, linked }: { a: Alert; linked: Intervention[] }) {
  const workflow = useOptionalWorkflow();
  const closed = linked.filter((i) => i.is_terminal);
  if (!closed.length) return null;
  return (
    <div className="space-y-1.5">
      <h3 className="flex items-center gap-1 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        Already done about this problem
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
              className="font-mono text-primary underline-offset-2 hover:underline"
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

/**
 * The selected alert, top to bottom in decision order: what is wrong, how late it is, what
 * to do next — then the rule, evidence and assumptions on demand.
 */
export function AlertDetails({ className }: { className?: string }) {
  const { alerts, selectedAlert: a } = useAnalysis();
  const linkedTo = useAlertInterventions();
  const linked = a ? linkedTo(a) : [];

  return (
    <SectionCard
      className={className}
      title="Alert detail"
      icon={ClipboardList}
      info="Why the selected alert fired and which intervention fits. Actions open a server-validated proposal; nothing is sent until a clinical lead approves."
    >
      {!alerts.data ? (
        <StateFallback
          resource={alerts}
          feature="alert detection"
          whenNoDataset="Select an alert once a dataset is loaded."
        />
      ) : !a ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Nothing needs attention at this simulation time.
        </p>
      ) : (
        <div className="space-y-4 text-sm">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <SeverityBadge severity={a.severity} />
              <TagBadge tone="neutral">Priority {a.priority}</TagBadge>
            </div>
            <h3 className="text-base leading-snug font-semibold text-navy">{a.title}</h3>
            <p className="text-muted-foreground">{a.summary}</p>
          </div>

          {a.hospital_name || a.consult_id || a.physician_name ? (
            <dl className="grid grid-cols-2 gap-3 rounded-lg border bg-muted/30 p-3 sm:grid-cols-3">
              {a.hospital_name ? (
                <Fact icon={Building2} label="Hospital">
                  {a.hospital_name}
                </Fact>
              ) : null}
              {a.consult_id ? (
                <Fact icon={Stethoscope} label="Consult">
                  {a.consult_id}
                </Fact>
              ) : null}
              {a.physician_name ? (
                <Fact icon={User} label="Physician">
                  {a.physician_name}
                </Fact>
              ) : null}
            </dl>
          ) : null}

          <StandardMeter a={a} />
          {a.warning_after_seconds === null && alertTiming(a) ? (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
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
                        <span className="font-normal text-muted-foreground">
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
      )}
    </SectionCard>
  );
}
