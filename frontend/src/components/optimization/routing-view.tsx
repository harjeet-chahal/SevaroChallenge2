"use client";

import { ArrowRight, PhoneCall, UserCheck } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { PendingActionButton } from "@/components/shared/pending-action-button";
import { AvailabilityBadge, TagBadge } from "@/components/shared/status-badges";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DispatchRecommendation, DispatchResult, UnassignedConsult } from "@/lib/api/types";

import { Bullets, Disclosure, ProposedNote, SolverLine, urgencyTone } from "./shared";

const KIND_LABEL: Record<DispatchRecommendation["kind"], string> = {
  assign: "Assign",
  reassign: "Reassign (proposal)",
  confirm_ringing: "Ringing — let it connect",
};

const REASON_LABEL: Record<UnassignedConsult["reason_code"], string> = {
  no_credentialed_on_shift: "Nobody credentialed on shift",
  no_eligible_physician: "No eligible physician",
  capacity_used_by_higher_priority: "Taken by higher priority",
  missing_hospital: "Hospital unknown",
};

function RecommendationCard({ rec }: { rec: DispatchRecommendation }) {
  return (
    <li className="space-y-2 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="font-semibold tabular-nums text-muted-foreground">
              #{rec.priority}
            </span>
            <span className="font-semibold">
              {rec.consult_type ?? "Consult"} {rec.consult_id}
            </span>
            <span className="text-muted-foreground">at {rec.hospital_name}</span>
          </p>
          <p className="flex flex-wrap items-center gap-1.5 text-sm">
            <TagBadge tone={urgencyTone(rec.urgency_tier)}>{rec.urgency_label}</TagBadge>
            <TagBadge tone="info">{KIND_LABEL[rec.kind]}</TagBadge>
            <ArrowRight className="size-3.5 text-muted-foreground" aria-label="to" />
            <span className="font-semibold text-navy">{rec.physician_name}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {rec.waiting_minutes !== null
              ? `Waiting ${Math.round(rec.waiting_minutes)} min · `
              : ""}
            Workload {rec.workload.consults_this_shift_before} →{" "}
            {rec.workload.consults_this_shift_after} consults this shift · cost {rec.edge_cost}
          </p>
        </div>
        <PendingActionButton
          label={rec.kind === "confirm_ringing" ? "Confirm" : "Assign"}
          icon={UserCheck}
          size="sm"
          reason="Proposal only. Acting on recommendations arrives with the approval workflow (Phase 5)."
        />
      </div>
      <Disclosure summary="Why this recommendation">
        <Bullets items={rec.explanation} />
        <div className="grid gap-3 md:grid-cols-2">
          <div>
            <h4 className="text-xs font-semibold text-foreground">Eligibility evidence</h4>
            <Bullets items={rec.eligibility_evidence} className="text-xs" />
          </div>
          <div>
            <h4 className="text-xs font-semibold text-foreground">Cost breakdown (lower wins)</h4>
            {rec.cost_breakdown.length ? (
              <ul className="space-y-0.5 text-xs text-muted-foreground">
                {rec.cost_breakdown.map((c) => (
                  <li key={c.name} className="flex justify-between gap-3">
                    <span>{c.detail}</span>
                    <span className="font-medium tabular-nums text-foreground">+{c.value}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">No cost components (cost 0).</p>
            )}
          </div>
        </div>
        {rec.excluded.length ? (
          <div>
            <h4 className="text-xs font-semibold text-foreground">Excluded for this consult</h4>
            <Bullets
              items={rec.excluded.map((x) => `${x.display_name} — ${x.reasons.join("; ")}`)}
              className="text-xs"
            />
          </div>
        ) : null}
        {rec.uncertainty.length ? (
          <p className="text-xs text-warning">Uncertainty: {rec.uncertainty.join("; ")}.</p>
        ) : null}
      </Disclosure>
    </li>
  );
}

export function RoutingView({ data }: { data: DispatchResult }) {
  const { plan } = data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SolverLine run={data.solver} />
        <span className="text-xs text-muted-foreground">{data.explanations[0]}</span>
      </div>
      <ProposedNote>
        {data.label} Hard rules (credentialing, on shift, not busy, no ringing phone, 2-minute call
        cool-down) are never traded for workload balance.
      </ProposedNote>

      {plan.recommendations.length ? (
        <ul className="space-y-2" aria-label="Proposed routing">
          {plan.recommendations.map((rec) => (
            <RecommendationCard key={rec.consult_id} rec={rec} />
          ))}
        </ul>
      ) : (
        <EmptyState
          compact
          icon={PhoneCall}
          title="No routing proposals"
          description={data.explanations.join(" ")}
        />
      )}

      {plan.unassigned.length ? (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold">Cannot be placed now</h3>
          <ul className="space-y-2">
            {plan.unassigned.map((u) => (
              <li
                key={u.consult_id}
                className="space-y-1 rounded-lg border border-critical-border/60 bg-critical-soft/40 p-3"
              >
                <p className="flex flex-wrap items-center gap-1.5 text-sm">
                  <span className="font-semibold">
                    {u.consult_type ?? "Consult"} {u.consult_id}
                  </span>
                  <span className="text-muted-foreground">at {u.hospital_name}</span>
                  <TagBadge tone={urgencyTone(u.urgency_tier)}>{u.urgency_label}</TagBadge>
                  <TagBadge tone="critical">{REASON_LABEL[u.reason_code]}</TagBadge>
                </p>
                <Bullets items={u.explanation} className="text-xs" />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <Disclosure summary="Routing view of on-shift physicians">
        <p className="text-xs text-muted-foreground">
          Coverage counts a physician who is on duty even while busy; routing needs them free right
          now. The two are computed separately.
        </p>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Physician</TableHead>
                <TableHead>Availability</TableHead>
                <TableHead>Counts for coverage</TableHead>
                <TableHead>Can take a new consult</TableHead>
                <TableHead className="text-right">Consults</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.physicians.map((p) => {
                const blocked = p.checks.find((c) => !c.passed);
                return (
                  <TableRow key={p.physician_id}>
                    <TableCell className="font-medium">{p.display_name}</TableCell>
                    <TableCell>
                      <AvailabilityBadge value={p.availability} />
                    </TableCell>
                    <TableCell className="text-xs">
                      {p.counts_for_coverage ? `Yes (${p.coverage_hospital_ids.join(", ")})` : "No"}
                    </TableCell>
                    <TableCell className="text-xs whitespace-normal">
                      {p.effective_routing_capacity > 0 ? (
                        <span className="text-success">Yes</span>
                      ) : (
                        <span className="text-critical">
                          No — {blocked?.message ?? "no capacity"}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right text-xs tabular-nums">
                      {p.consults_this_shift}
                      {p.open_consults ? ` (${p.open_consults} open)` : ""}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </Disclosure>

      {data.skipped.length ? (
        <Disclosure summary={`Not part of this decision (${data.skipped.length})`}>
          <Bullets
            items={data.skipped.map((s) => `${s.consult_id}: ${s.reason}`)}
            className="text-xs"
          />
        </Disclosure>
      ) : null}

      <Disclosure summary="Rules, assumptions and implementation choices">
        <h4 className="text-xs font-semibold">From the brief</h4>
        <Bullets items={data.policy.rules} className="text-xs" />
        <h4 className="text-xs font-semibold">Assumptions</h4>
        <Bullets items={data.policy.assumptions} className="text-xs" />
        <h4 className="text-xs font-semibold">Implementation choices</h4>
        <Bullets items={data.policy.implementation_choices} className="text-xs" />
      </Disclosure>
    </div>
  );
}
