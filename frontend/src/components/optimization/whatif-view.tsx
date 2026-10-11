"use client";

import { FlaskConical, Loader2, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { ProjectionChart } from "@/components/coverage/projection-chart";
import { EmptyState } from "@/components/shared/empty-state";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { optimizationApi } from "@/lib/api/endpoints";
import type { SplitShiftAction, StaffingResult } from "@/lib/api/types";
import { formatDuration, formatTime } from "@/lib/format";

import { useOptimization } from "./optimization-provider";
import { Bullets, ProposedNote } from "./shared";
import { useHospitalZones } from "./staffing-view";

const DURATIONS = [90, 120, 180, 240, 360];
const selectClass =
  "h-8 w-full rounded-lg border bg-background px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/** Canonical ISO form so the same instant is never listed twice. */
function iso(value: string): string {
  return new Date(value).toISOString();
}

function startOptions(staffing: StaffingResult, physicianId: string, current?: string | null) {
  const c = staffing.candidates.find((x) => x.physician_id === physicianId);
  const options = new Map<string, string>();
  if (c?.proposed_start) options.set(iso(c.proposed_start), "Recommended start");
  if (c?.earliest_valid_start) {
    options.set(iso(c.earliest_valid_start), "Earliest valid start");
    const base = new Date(c.earliest_valid_start).getTime();
    for (const extra of [30, 60]) {
      options.set(new Date(base + extra * 60_000).toISOString(), `Earliest + ${extra} min`);
    }
  }
  if (!options.has(iso(staffing.as_of))) options.set(iso(staffing.as_of), "Now");
  if (current && !options.has(iso(current))) options.set(iso(current), "Selected start");
  return [...options.entries()];
}

function Preview({ action }: { action: SplitShiftAction }) {
  const { config } = useSystemStatus();
  const zones = useHospitalZones();
  const key = config?.dataset_loaded
    ? `${config.data_version}|${config.simulation_time}|${JSON.stringify(action)}`
    : null;
  const result = useKeyedResource(key, (signal) => optimizationApi.simulate(action, signal));
  const data = result.data;

  if (result.error) {
    return (
      <EmptyState compact icon={TriangleAlert} title="Preview failed" description={result.error} />
    );
  }
  if (!data) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden /> Running the coverage engine…
      </p>
    );
  }
  if (!data.allowed) {
    return (
      <div className="space-y-2 rounded-lg border border-critical-border bg-critical-soft/50 p-3">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-critical-ink">
          <TriangleAlert className="size-4" aria-hidden />
          Not allowed — this offer breaks a rule
        </p>
        <Bullets items={data.violations.map((v) => `${v.label}: ${v.message}`)} />
        <p className="text-xs text-muted-foreground">
          No projection is shown for an offer that breaks a hard rule.
        </p>
      </div>
    );
  }
  return (
    <div className={result.loading ? "space-y-4 opacity-60" : "space-y-4"}>
      <ProposedNote>{data.label}. Nothing is created, approved or sent.</ProposedNote>
      <Bullets items={data.explanations} />
      {data.projections.map((p) => {
        const tz = zones[p.hospital_id] ?? p.before.timezone;
        return (
          <section key={p.hospital_id} className="space-y-2" aria-label={p.hospital_name}>
            <h3 className="text-sm font-semibold">{p.hospital_name}</h3>
            <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
              <div className="rounded-md border p-2">
                <dt className="text-xs text-muted-foreground">
                  Deficit (next {data.horizon_minutes} min)
                </dt>
                <dd className="font-semibold font-mono tabular-nums">
                  {p.deficit_physician_minutes_before} → {p.deficit_physician_minutes_after}
                </dd>
              </div>
              <div className="rounded-md border p-2">
                <dt className="text-xs text-muted-foreground">First shortfall</dt>
                <dd className="font-semibold">
                  {p.first_shortfall_before ? formatTime(p.first_shortfall_before, tz) : "None"} →{" "}
                  {p.first_shortfall_after ? formatTime(p.first_shortfall_after, tz) : "None"}
                </dd>
              </div>
              <div className="rounded-md border p-2">
                <dt className="text-xs text-muted-foreground">Shortfall now</dt>
                <dd className="font-semibold font-mono tabular-nums">
                  {p.deficit_now_before ?? "—"} → {p.deficit_now_after ?? "—"}
                </dd>
              </div>
            </dl>
            <ProjectionChart projection={p} />
          </section>
        );
      })}
      <div className="space-y-1">
        <h3 className="text-xs font-semibold">Not modeled</h3>
        <Bullets items={data.effects_not_modeled} className="text-xs" />
      </div>
    </div>
  );
}

function Form({ initial, staffing }: { initial: SplitShiftAction; staffing: StaffingResult }) {
  const [action, setAction] = useState<SplitShiftAction>(initial);
  const zones = useHospitalZones();
  const candidate = staffing.candidates.find((c) => c.physician_id === action.physician_id);
  const tz = zones[candidate?.gap_hospital_ids[0] ?? ""];
  const starts = startOptions(staffing, action.physician_id, action.start);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="space-y-1 text-xs font-medium">
          Physician
          <select
            className={selectClass}
            value={action.physician_id}
            onChange={(e) =>
              setAction({
                kind: "split_shift",
                physician_id: e.target.value,
                duration_minutes: action.duration_minutes,
                start:
                  staffing.candidates.find((c) => c.physician_id === e.target.value)
                    ?.earliest_valid_start ?? null,
              })
            }
          >
            {staffing.candidates.map((c) => (
              <option key={c.physician_id} value={c.physician_id}>
                {c.display_name}
                {c.eligible ? "" : " (not eligible)"}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs font-medium">
          Offered start
          <select
            className={selectClass}
            value={action.start ? iso(action.start) : ""}
            onChange={(e) => setAction({ ...action, start: e.target.value })}
          >
            {starts.map(([value, label]) => (
              <option key={value} value={value}>
                {label} — {formatTime(value, tz)}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs font-medium">
          Length
          <select
            className={selectClass}
            value={action.duration_minutes}
            onChange={(e) => setAction({ ...action, duration_minutes: Number(e.target.value) })}
          >
            {[...new Set([...DURATIONS, action.duration_minutes])]
              .sort((a, b) => a - b)
              .map((m) => (
                <option key={m} value={m}>
                  {formatDuration(m)}
                  {m < 120 ? " (below the 2 h minimum)" : ""}
                </option>
              ))}
          </select>
        </label>
      </div>
      <Preview action={{ ...action, hospital_ids: action.hospital_ids ?? null }} />
    </div>
  );
}

export function WhatIfView({ staffing }: { staffing: StaffingResult }) {
  const { previewAction } = useOptimization();
  const fallback: SplitShiftAction | null = staffing.candidates[0]
    ? {
        kind: "split_shift",
        physician_id: staffing.candidates[0].physician_id,
        start: staffing.candidates[0].earliest_valid_start,
        duration_minutes: 120,
      }
    : null;
  const initial = previewAction ?? fallback;
  if (!initial) {
    return (
      <EmptyState
        compact
        icon={FlaskConical}
        title="Nothing to preview"
        description="There is no off-shift physician in this dataset to model."
      />
    );
  }
  return <Form key={JSON.stringify(initial)} initial={initial} staffing={staffing} />;
}
