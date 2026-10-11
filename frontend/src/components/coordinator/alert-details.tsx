"use client";

import { ArrowRightLeft, CalendarClock, ClipboardList, Megaphone, PhoneCall } from "lucide-react";

import { PendingActionButton } from "@/components/shared/pending-action-button";
import { Button } from "@/components/ui/button";
import { InterventionProgressBadge } from "@/components/workflow/status";
import {
  ACTION_INTERVENTION_TYPES,
  useAlertInterventions,
  useOptionalWorkflow,
} from "@/components/workflow/workflow-provider";
import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { TagBadge } from "@/components/shared/status-badges";
import { useAnalysis } from "@/components/state/analysis-provider";
import { StateFallback } from "@/components/state/state-fallback";
import type { RecommendedAction } from "@/lib/api/types";
import { formatElapsed, formatTime } from "@/lib/format";
import { ACTION_LABELS, INTERVENTION_STATUS_LABELS } from "@/lib/labels";

import { alertTiming } from "./alert-queue";

const ACTION_ICONS: Record<RecommendedAction, React.ComponentType<{ className?: string }>> = {
  reassign_consult: ArrowRightLeft,
  escalate: Megaphone,
  contact_physician: PhoneCall,
  propose_split_shift: CalendarClock,
  monitor: ClipboardList,
};

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </div>
  );
}

/** Evidence, rule, severity and priority reasoning for the selected alert. */
export function AlertDetails({ className }: { className?: string }) {
  const { alerts, selectedAlert: a } = useAnalysis();
  const workflow = useOptionalWorkflow();
  const linkedTo = useAlertInterventions();
  const linked = a ? linkedTo(a) : [];

  return (
    <SectionCard
      className={className}
      title="Alert details"
      icon={ClipboardList}
      description="Why the selected alert fired and what kind of intervention fits. Actions open a server-validated proposal; nothing is sent until a clinical lead approves."
    >
      {!alerts.data ? (
        <StateFallback
          resource={alerts}
          feature="alert detection"
          whenNoDataset="Select an alert once a dataset is loaded."
        />
      ) : !a ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No alerts at this simulation time.
        </p>
      ) : (
        <div className="space-y-4 text-sm">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <SeverityBadge severity={a.severity} />
              <TagBadge tone="neutral">Priority {a.priority}</TagBadge>
            </div>
            <p className="font-semibold text-navy">{a.title}</p>
            <p className="text-muted-foreground">{a.summary}</p>
          </div>

          <Block title="Triggering rule">
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
          </Block>

          <Block title="Severity">
            <p>{a.severity_reason}</p>
            {a.warning_after_seconds !== null && a.critical_after_seconds !== null ? (
              <p className="text-xs text-muted-foreground">
                Standard: warning at {formatElapsed(a.warning_after_seconds)}, critical at{" "}
                {formatElapsed(a.critical_after_seconds)}
                {a.elapsed_seconds !== null ? `; elapsed ${formatElapsed(a.elapsed_seconds)}` : ""}.
              </p>
            ) : null}
            {alertTiming(a) ? (
              <p className="text-xs text-muted-foreground">{alertTiming(a)}</p>
            ) : null}
          </Block>

          <Block title="Why this priority">
            <ul className="list-disc space-y-0.5 pl-4 text-xs">
              {a.priority_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </Block>

          <Block title="Evidence">
            <dl className="space-y-1.5 rounded-lg border bg-muted/30 p-2.5 text-xs">
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
          </Block>

          {a.assumptions.length ? (
            <Block title="Assumptions">
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                {a.assumptions.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
            </Block>
          ) : null}

          {linked.length ? (
            <Block title="Already done about this problem">
              <ul className="space-y-1.5">
                {linked.map((i) => (
                  <li key={i.id} className="space-y-0.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <button
                        type="button"
                        className="font-mono text-xs text-primary underline-offset-2 hover:underline"
                        onClick={() => {
                          workflow?.select(i.id);
                          document
                            .getElementById("intervention-board")
                            ?.scrollIntoView({ behavior: "smooth", block: "start" });
                        }}
                      >
                        {i.id}
                      </button>
                      <InterventionProgressBadge intervention={i} />
                      <span className="text-xs text-muted-foreground">
                        updated {formatTime(i.updated_at, a.hospital_timezone)}
                      </span>
                    </div>
                    {i.status_reason ? (
                      <p className="text-xs text-muted-foreground">{i.status_reason}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">
                This alert comes from the live data, so it stays until the problem itself
                changes (for example, a doctor is assigned to the consult). Completing an
                escalation records the clinical lead&apos;s action; it does not change the
                consult.
              </p>
            </Block>
          ) : null}

          <Block title="Suggested intervention category">
            <p className="font-medium">{ACTION_LABELS[a.recommended_action_type]}</p>
            <p className="text-xs text-muted-foreground">{a.recommended_action_reason}</p>
            <div className="flex flex-wrap gap-2 pt-1">
              {(["propose_split_shift", "escalate", "reassign_consult"] as const).map((action) => {
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
                const unavailable =
                  !workflow
                    ? "Open the coordinator view to propose interventions."
                    : action === "reassign_consult" && !a.consult_id
                      ? "This alert is not about a single consult."
                      : action === "propose_split_shift" && !a.hospital_id
                        ? "This alert is not tied to a hospital's coverage."
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
                return (
                  <Button
                    key={action}
                    size="sm"
                    variant={action === a.recommended_action_type && !done ? "default" : "outline"}
                    onClick={() =>
                      workflow!.openComposer({
                        type,
                        alertId: a.alert_id,
                        consultId: a.consult_id,
                        hospitalIds: action === "propose_split_shift" && a.hospital_id ? [a.hospital_id] : undefined,
                      })
                    }
                  >
                    <Icon aria-hidden />
                    {label}
                  </Button>
                );
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              Opens a proposal that the backend validates against the current data. A split
              shift becomes a pending clinical-lead approval; nobody is contacted.
            </p>
          </Block>
        </div>
      )}
    </SectionCard>
  );
}
