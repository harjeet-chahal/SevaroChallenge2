"use client";

import {
  CircleAlert,
  Clock,
  Hospital,
  ShieldCheck,
  Stethoscope,
  UserRound,
} from "lucide-react";

import { CheckMark, Bullets, Disclosure } from "@/components/optimization/shared";
import { RULE_SHORT, TrapSummary } from "@/components/optimization/staffing-view";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { TagBadge } from "@/components/shared/status-badges";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  CandidateEligibility,
  CoverageImpact,
  Intervention,
  OfferPlanItem,
  ShiftOffer,
} from "@/lib/api/types";
import { formatDateTime, formatDuration, formatElapsed, formatTime } from "@/lib/format";
import { OFFER_STATUS_LABELS } from "@/lib/labels";

import { OfferStatusBadge } from "./status";

export function Block({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon?: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-1.5">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {Icon ? <Icon className="size-3.5" aria-hidden /> : null}
        {title}
      </h3>
      {children}
    </section>
  );
}

/** What is wrong: the source problem, where, how urgent, and the time limits. */
export function ProblemBlock({ intervention: i }: { intervention: Intervention }) {
  const p = i.problem;
  const tz = p.hospital_timezone;
  return (
    <Block title="What is wrong" icon={CircleAlert}>
      <div className="space-y-1 rounded-lg border bg-muted/30 p-3 text-sm">
        <div className="flex flex-wrap items-center gap-1.5">
          {p.severity ? <SeverityBadge severity={p.severity} /> : null}
          {p.priority ? <TagBadge tone="neutral">Priority {p.priority}</TagBadge> : null}
          {p.rule_code ? (
            <span className="font-mono text-xs text-muted-foreground">{p.rule_code}</span>
          ) : null}
        </div>
        <p className="font-semibold text-foreground">{p.title}</p>
        <p className="text-muted-foreground">{p.summary}</p>
        <dl className="grid gap-x-4 gap-y-1 pt-1 text-xs sm:grid-cols-2">
          {p.hospital_names.length ? (
            <div className="flex gap-1.5">
              <Hospital className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <dt className="sr-only">Hospitals</dt>
              <dd>{p.hospital_names.join(", ")}</dd>
            </div>
          ) : null}
          {p.consult_id ? (
            <div className="flex gap-1.5">
              <Stethoscope className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <dt className="sr-only">Consult</dt>
              <dd>
                {p.consult_id}
                {p.consult_type ? ` · ${p.consult_type}` : ""}
              </dd>
            </div>
          ) : null}
          {p.physician_name ? (
            <div className="flex gap-1.5">
              <UserRound className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <dt className="sr-only">Physician</dt>
              <dd>{p.physician_name}</dd>
            </div>
          ) : null}
          {p.elapsed_seconds !== null && p.critical_after_seconds !== null ? (
            <div className="flex gap-1.5">
              <Clock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <dt className="sr-only">Time limits</dt>
              <dd>
                Waited {formatElapsed(p.elapsed_seconds)} · warning{" "}
                {formatElapsed(p.warning_after_seconds ?? 0)} · critical{" "}
                {formatElapsed(p.critical_after_seconds)}
              </dd>
            </div>
          ) : null}
          {p.impact_at ? (
            <div className="flex gap-1.5">
              <Clock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <dt className="sr-only">Starts</dt>
              <dd>Shortfall from {formatTime(p.impact_at, tz)}</dd>
            </div>
          ) : null}
        </dl>
        <p className="text-xs text-muted-foreground">
          Captured at simulation time {formatTime(p.captured_at, tz)} · data version{" "}
          {p.data_version}
        </p>
      </div>
    </Block>
  );
}

export function ImpactTable({ impact, tz }: { impact: CoverageImpact; tz?: string | null }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-muted-foreground">{impact.label}</p>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Hospital</TableHead>
              <TableHead className="text-right">Deficit (physician-min)</TableHead>
              <TableHead className="text-right">Short now</TableHead>
              <TableHead>First shortfall</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {impact.hospitals.map((h) => (
              <TableRow key={h.hospital_id}>
                <TableCell className="font-medium">{h.hospital_name}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {h.deficit_before} → {h.deficit_after}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {h.shortfall_now_before} → {h.shortfall_now_after}
                </TableCell>
                <TableCell className="text-xs">
                  {h.first_shortfall_before ? formatTime(h.first_shortfall_before, tz) : "none"} →{" "}
                  {h.first_shortfall_after ? formatTime(h.first_shortfall_after, tz) : "none"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        Over the next {impact.horizon_minutes} min, computed at {formatTime(impact.computed_at, tz)}{" "}
        (data version {impact.data_version}).
      </p>
      <Bullets items={impact.notes} className="text-xs" />
    </div>
  );
}

function PlanItem({ item, tz }: { item: OfferPlanItem; tz?: string | null }) {
  const failed = item.checks.filter((c) => !c.passed);
  return (
    <li className="space-y-2 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold text-foreground">{item.display_name}</span>
        <TagBadge tone={item.role === "primary" ? "info" : "neutral"}>
          {item.role === "primary" ? "Proposed physician" : "Backup"}
        </TagBadge>
        <TagBadge tone={item.eligible ? "success" : "critical"}>
          {item.eligible ? "Passes every rule" : `Fails ${failed.length} rule(s)`}
        </TagBadge>
      </div>
      <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Hospitals covered</dt>
          <dd>{item.hospital_names.join(", ")}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Shift</dt>
          <dd>
            {formatTime(item.start_at, tz)} – {formatTime(item.end_at, tz)} (
            {formatDuration(item.duration_minutes)})
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Expected activation</dt>
          <dd>
            {formatTime(item.expected_online_at, tz)} · {item.minutes_to_online} min to come online
            {item.online_time_assumed ? " (assumed)" : ""}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Useful coverage</dt>
          <dd>{formatDuration(item.coverage_minutes)} after coming online</dd>
        </div>
      </dl>
      {item.projected_effects.length ? (
        <ul className="space-y-0.5 text-xs text-muted-foreground">
          {item.projected_effects.map((e) => (
            <li key={`${e.hospital_id}-${e.horizon_minutes}`}>
              {e.hospital_name}: deficit {e.deficit_physician_minutes_before} →{" "}
              {e.deficit_physician_minutes_after} physician-min over {e.horizon_minutes} min if
              accepted (projected)
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex gap-2 rounded-md border border-success-border bg-success-soft/50 p-2 text-xs">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success-ink" aria-hidden />
        <div className="space-y-0.5">
          <p className="font-semibold text-foreground">
            Routing scope while on the split shift: {item.routing_scope_hospital_ids.join(", ")}
            {item.excluded_credentialed_hospital_ids.length
              ? ` (not ${item.excluded_credentialed_hospital_ids.join(", ")})`
              : ""}
          </p>
          <Bullets items={item.protection_rationale} className="text-xs" />
        </div>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {item.checks.map((c) => (
          <CheckMark key={c.code} check={c} showLabel />
        ))}
      </div>
    </li>
  );
}

export function CandidateTable({ candidates }: { candidates: CandidateEligibility[] }) {
  if (!candidates.length) {
    return <p className="text-sm text-muted-foreground">No off-shift roster in this dataset.</p>;
  }
  const codes = candidates[0].checks.map((c) => c.code);
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Physician</TableHead>
            {codes.map((code) => (
              <TableHead key={code} className="text-center">
                {RULE_SHORT[code] ?? code}
              </TableHead>
            ))}
            <TableHead>Why</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {candidates.map((c) => (
            <TableRow key={c.physician_id}>
              <TableCell className="font-medium">{c.display_name}</TableCell>
              {c.checks.map((check) => (
                <TableCell key={check.code} className="text-center">
                  <CheckMark check={check} />
                </TableCell>
              ))}
              <TableCell className="min-w-64 text-xs whitespace-normal">
                <TagBadge tone={c.eligible ? "success" : "neutral"}>
                  {c.eligible ? "Eligible" : "Excluded"}
                </TagBadge>{" "}
                {c.summary}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function OfferRows({
  offers,
  tz,
  actions,
}: {
  offers: ShiftOffer[];
  tz?: string | null;
  actions?: (offer: ShiftOffer) => React.ReactNode;
}) {
  return (
    <ul className="space-y-2">
      {offers.map((o) => (
        <li key={o.id} className="space-y-1 rounded-lg border p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="flex flex-wrap items-center gap-1.5">
              <span className="font-medium">{o.display_name}</span>
              <span className="font-mono text-xs text-muted-foreground">{o.id}</span>
              <OfferStatusBadge status={o.status} />
              {o.plan_role === "backup" ? <TagBadge tone="neutral">backup</TagBadge> : null}
            </p>
            {actions ? <div className="flex flex-wrap gap-2">{actions(o)}</div> : null}
          </div>
          <p className="text-xs text-muted-foreground">
            {o.hospitals.map((h) => h.name).join(", ")} · {formatTime(o.start_at, tz)}–
            {formatTime(o.end_at, tz)} · approved by {o.approved_by.actor_id} · sent{" "}
            {formatTime(o.sent_at, tz)} via simulated {o.channel ?? "app"} · expires{" "}
            {formatTime(o.expires_at, tz)}
          </p>
          {o.responses.length ? (
            <ul className="text-xs text-muted-foreground">
              {o.responses.map((r) => (
                <li key={r.id}>
                  Reply “{r.response}” at {formatTime(r.received_at, tz)}
                  {r.response_seconds !== null ? ` (${formatElapsed(r.response_seconds)} after sending)` : ""}{" "}
                  → {r.outcome.replaceAll("_", " ")}
                  {r.detail ? ` — ${r.detail}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
          {o.expected_online_at || o.activated_at ? (
            <p className="text-xs">
              {o.activated_at
                ? `Online since ${formatTime(o.activated_at, tz)} (${(o.activation_source ?? "").replaceAll("_", " ")}); routable only at ${o.routing_scope_hospital_ids.join(", ")}.`
                : `Accepted — expected online ${formatTime(o.expected_online_at!, tz)}. Not counted as active capacity yet.`}
            </p>
          ) : null}
          {o.status_reason && o.status !== "accepted" && o.status !== "active" ? (
            <p className="text-xs text-muted-foreground">
              {OFFER_STATUS_LABELS[o.status]}: {o.status_reason}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Everything a decision-maker needs about one intervention (proposal or record). */
export function InterventionDetailView({
  intervention: i,
  showCandidates = true,
}: {
  intervention: Intervention;
  showCandidates?: boolean;
}) {
  const tz = i.problem.hospital_timezone;
  const r = i.recommendation;
  return (
    <div className="space-y-4 text-sm">
      <ProblemBlock intervention={i} />

      <Block title="Recommended intervention" icon={ShieldCheck}>
        <p className="font-medium">{r.summary}</p>
        <p className="text-xs text-muted-foreground">
          {r.algorithm} · policy {r.policy_version} · approved by{" "}
          {r.approver_role === "clinical_lead" ? "the clinical lead" : "the coordinator"}
        </p>
        {i.type === "split_shift" ? (
          <p className="text-xs">
            Coverage need: {i.problem.hospital_names.join(", ") || i.problem.hospital_ids.join(", ")}{" "}
            · {i.required_physicians} physician(s) required at the peak of the gap.
          </p>
        ) : null}
        <Disclosure summary="Why this intervention">
          <Bullets items={r.why} className="text-xs" />
        </Disclosure>
      </Block>

      {i.offer_plan.length ? (
        <Block title="Proposed split shift">
          <ul className="space-y-2">
            {i.offer_plan.map((item) => (
              <PlanItem key={item.physician_id} item={item} tz={tz} />
            ))}
          </ul>
        </Block>
      ) : null}

      {i.reassignment ? (
        <Block title="Proposed reassignment">
          <div className="space-y-1 rounded-lg border p-3">
            <p>
              <span className="font-medium">{i.reassignment.consult_id}</span>
              {i.reassignment.consult_type ? ` (${i.reassignment.consult_type})` : ""} at{" "}
              {i.reassignment.hospital_name}: {i.reassignment.current_physician_name ?? "unassigned"}{" "}
              → <span className="font-semibold">{i.reassignment.target_physician_name}</span>
            </p>
            {i.reassignment.workload_note ? (
              <p className="text-xs text-muted-foreground">{i.reassignment.workload_note}</p>
            ) : null}
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              {i.reassignment.checks.map((c) => (
                <CheckMark key={c.code} check={c} showLabel />
              ))}
            </div>
            {i.reassignment.excluded.length ? (
              <Disclosure summary={`Other physicians considered (${i.reassignment.excluded.length})`}>
                <ul className="space-y-0.5 text-xs">
                  {i.reassignment.excluded.map((x) => (
                    <li key={x.physician_id}>
                      <span className="font-medium">{x.display_name}</span>: {x.reasons.join("; ")}
                    </li>
                  ))}
                </ul>
              </Disclosure>
            ) : null}
          </div>
        </Block>
      ) : null}

      {i.escalation ? (
        <Block title="Escalation request">
          <div className="space-y-1 rounded-lg border p-3">
            <p className="font-medium">{i.escalation.requested_decision}</p>
            <p className="text-xs text-muted-foreground">Reason: {i.escalation.reason}</p>
            <Bullets items={i.escalation.blocking_facts} className="text-xs" />
          </div>
        </Block>
      ) : null}

      {i.impact ? (
        <Block title="Estimated impact on coverage">
          <ImpactTable impact={i.impact} tz={tz} />
        </Block>
      ) : null}

      {showCandidates && i.candidates.length ? (
        <Block title={`Every off-shift physician evaluated (${i.candidates.length})`}>
          <CandidateTable candidates={i.candidates} />
        </Block>
      ) : null}

      {i.trap ? (
        <Disclosure summary="Split-shift trap protection (modeled routing)">
          <TrapSummary trap={i.trap} />
        </Disclosure>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <Block title="Alternatives">
          <ul className="space-y-1 text-xs">
            {r.alternatives.map((a) => (
              <li key={a.label}>
                <TagBadge tone={a.available ? "info" : "neutral"}>
                  {a.available ? "Available" : "Not available"}
                </TagBadge>{" "}
                <span className="font-medium">{a.label}</span> — {a.reason}
              </li>
            ))}
          </ul>
        </Block>
        <Block title="Uncertainty and restrictions">
          <Bullets items={[...r.uncertainty, ...r.restrictions]} className="text-xs" />
        </Block>
      </div>

      {i.rationale ? (
        <p className="text-xs text-muted-foreground">
          Coordinator note (internal, never sent to physicians): {i.rationale}
        </p>
      ) : null}
      {i.id !== "PREVIEW" ? (
        <p className="text-xs text-muted-foreground">
          {i.id} · proposed by {i.proposed_by.actor_id} at {formatDateTime(i.proposed_at, tz)} ·
          version {i.version}
        </p>
      ) : null}
    </div>
  );
}
