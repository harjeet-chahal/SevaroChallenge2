"use client";

import { Eye, Send, ShieldCheck, UserPlus } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { PendingActionButton } from "@/components/shared/pending-action-button";
import { TagBadge } from "@/components/shared/status-badges";
import { useAnalysis } from "@/components/state/analysis-provider";
import { useOptionalWorkflow } from "@/components/workflow/workflow-provider";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ShiftRecommendation, StaffingResult, TrapAnalysis } from "@/lib/api/types";
import { formatDuration, formatTime } from "@/lib/format";

import { useOptimization } from "./optimization-provider";
import { Bullets, CheckMark, Disclosure, ProposedNote, SolverLine } from "./shared";

export const RULE_SHORT: Record<string, string> = {
  opt_in: "Opt-in",
  credentialed_at_gap: "Gap hospital",
  off_shift: "Off shift",
  rest_10h: "10 h rest",
  weekly_hours: "≤ 60 h / 7 d",
  no_overlap: "No overlap",
  min_length: "≥ 2 h",
  notification_limits: "Offer limits",
};

/** Hospital id -> time zone, from the coverage report (display only). */
export function useHospitalZones(): Record<string, string> {
  const { coverage } = useAnalysis();
  return Object.fromEntries(
    (coverage.data?.hospitals ?? []).map((h) => [h.hospital_id, h.timezone]),
  );
}

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function ShiftCard({ rec, tz }: { rec: ShiftRecommendation; tz: string | undefined }) {
  const { preview } = useOptimization();
  const workflow = useOptionalWorkflow();
  const planningHorizon = Math.max(...rec.effects.map((e) => e.horizon_minutes));
  const planning = rec.effects.filter((e) => e.horizon_minutes === planningHorizon);
  const dashboard = rec.effects.filter((e) => e.horizon_minutes < planningHorizon);
  return (
    <li className="space-y-3 rounded-lg border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold text-foreground">{rec.display_name}</span>
            <TagBadge tone="info">Recommendation · needs clinical-lead approval</TagBadge>
          </p>
          <p className="text-sm">
            {formatTime(rec.offer_start, tz)} – {formatTime(rec.offer_end, tz)} (
            {formatDuration(rec.offer_minutes)}) · online about {formatTime(rec.online_at, tz)}
          </p>
          <p className="text-xs text-muted-foreground">{rec.hospital_names.join(", ")}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              preview({
                kind: "split_shift",
                physician_id: rec.physician_id,
                start: rec.offer_start,
                duration_minutes: rec.offer_minutes,
                hospital_ids: rec.hospital_ids,
              })
            }
          >
            <Eye aria-hidden />
            Preview impact
          </Button>
          {workflow ? (
            <Button
              size="sm"
              onClick={() =>
                workflow.openComposer({
                  type: "split_shift",
                  physicianIds: [rec.physician_id],
                  hospitalIds: rec.hospital_ids,
                })
              }
            >
              <Send aria-hidden />
              Propose (needs approval)
            </Button>
          ) : (
            <PendingActionButton
              label="Propose (needs approval)"
              icon={Send}
              size="sm"
              reason="Proposals are made from the coordinator view."
            />
          )}
        </div>
      </div>
      <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {planning.map((e) => {
          const dash = dashboard.find((d) => d.hospital_id === e.hospital_id);
          return (
            <div key={e.hospital_id} className="rounded-md border p-2 text-sm">
              <dt className="font-medium">{e.hospital_name}</dt>
              <dd className="text-xs text-muted-foreground tabular-nums">
                Deficit {e.deficit_physician_minutes_before} → {e.deficit_physician_minutes_after}{" "}
                physician-min (next {e.horizon_minutes} min)
                {dash
                  ? `; ${dash.deficit_physician_minutes_before} → ${dash.deficit_physician_minutes_after} in the ${dash.horizon_minutes}-min forecast`
                  : ""}
              </dd>
            </div>
          );
        })}
      </dl>
      <div className="flex gap-2 rounded-md border border-success-border bg-success-soft/50 p-2 text-xs">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
        <div className="space-y-0.5">
          <p className="font-semibold text-foreground">Split-shift trap protection</p>
          <Bullets items={rec.protection.rationale} className="text-xs" />
        </div>
      </div>
      <Disclosure summary="Why this offer">
        <Bullets items={rec.explanation} className="text-xs" />
      </Disclosure>
    </li>
  );
}

export function TrapSummary({ trap }: { trap: TrapAnalysis }) {
  const rows = [
    [
      "Modeled consults in window",
      trap.unrestricted.modeled_arrivals,
      trap.protected.modeled_arrivals,
    ],
    [
      `Routed to ${trap.display_name}`,
      trap.unrestricted.routed_to_joiner,
      trap.protected.routed_to_joiner,
    ],
    [
      "…at hospitals without a gap",
      trap.unrestricted.routed_to_joiner_elsewhere,
      trap.protected.routed_to_joiner_elsewhere,
    ],
    [
      "Highest consults, any physician",
      trap.unrestricted.max_consults_any_physician,
      trap.protected.max_consults_any_physician,
    ],
  ] as const;
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold">Split-shift trap (simulated)</h3>
      <p className="text-sm text-muted-foreground">{trap.conclusion}</p>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Modeled routing</TableHead>
              <TableHead className="text-right">Unrestricted (starts at 0)</TableHead>
              <TableHead className="text-right">Protected</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(([label, u, p]) => (
              <TableRow key={label}>
                <TableCell className="whitespace-normal">{label}</TableCell>
                <TableCell className="text-right tabular-nums">{u}</TableCell>
                <TableCell className="text-right tabular-nums">{p}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Bullets items={trap.assumptions} className="text-xs" />
    </div>
  );
}

export function StaffingView({ data }: { data: StaffingResult }) {
  const zones = useHospitalZones();
  const t = data.totals;
  const codes = data.candidates[0]?.checks.map((c) => c.code) ?? [];
  return (
    <div className="space-y-4">
      <SolverLine run={data.solver} />
      <ProposedNote>{data.label}</ProposedNote>
      <Bullets items={data.explanations} />

      <dl className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Stat
          label={`Deficit, next ${t.planning_horizon_minutes} min`}
          value={`${t.deficit_physician_minutes_before} → ${t.deficit_physician_minutes_after}`}
          hint="physician-minutes, projected if accepted"
        />
        <Stat label="Physicians to contact" value={t.physicians_used} />
        <Stat label="Hours offered" value={formatDuration(t.offered_minutes)} />
        <Stat
          label="Excess coverage"
          value={t.excess_physician_minutes}
          hint="physician-minutes above requirement"
        />
      </dl>

      {data.recommendations.length ? (
        <ul className="space-y-2" aria-label="Proposed split shifts">
          {data.recommendations.map((rec) => (
            <ShiftCard key={rec.physician_id} rec={rec} tz={zones[rec.hospital_ids[0]]} />
          ))}
        </ul>
      ) : (
        <EmptyState
          compact
          icon={UserPlus}
          title="No split shift proposed"
          description={data.explanations.at(-1)}
        />
      )}

      {data.infeasibility.length ? (
        <div className="space-y-1">
          <h3 className="text-sm font-semibold">Gaps the plan cannot close</h3>
          <Bullets items={data.infeasibility} />
        </div>
      ) : null}

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">
          Every off-shift physician considered ({data.candidates.length})
        </h3>
        {data.candidates.length ? (
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
                  <TableHead>Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.candidates.map((c) => (
                  <TableRow key={c.physician_id}>
                    <TableCell className="font-medium">
                      {c.display_name}
                      <span className="block text-xs font-normal text-muted-foreground">
                        {c.roster_role ?? "role unknown"}
                      </span>
                    </TableCell>
                    {c.checks.map((check) => (
                      <TableCell key={check.code} className="text-center">
                        <CheckMark check={check} />
                      </TableCell>
                    ))}
                    <TableCell className="min-w-64 text-xs whitespace-normal">
                      <TagBadge tone={c.eligible ? "success" : "neutral"}>
                        {c.eligible ? "Eligible" : "Not eligible"}
                      </TagBadge>{" "}
                      {c.summary}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No off-shift roster in this dataset.</p>
        )}
        <p className="text-xs text-muted-foreground">
          Hover a mark for the value it was checked against. Missing data never passes.
        </p>
      </div>

      {data.trap ? <TrapSummary trap={data.trap} /> : null}

      <Disclosure summary="Rules and assumptions">
        <h4 className="text-xs font-semibold">From the brief</h4>
        <Bullets items={data.rules} className="text-xs" />
        <h4 className="text-xs font-semibold">Assumptions and choices</h4>
        <Bullets items={data.assumptions} className="text-xs" />
        <h4 className="text-xs font-semibold">Solver</h4>
        <Bullets
          items={[
            ...data.solver.stages.map(
              (s) =>
                `${s.name}: ${s.status}${s.objective !== null ? ` (objective ${s.objective})` : ""}`,
            ),
            ...data.solver.notes,
          ]}
          className="text-xs"
        />
      </Disclosure>
    </div>
  );
}
