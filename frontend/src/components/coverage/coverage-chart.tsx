"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { HospitalCoverage } from "@/lib/api/types";
import { formatTime } from "@/lib/format";

interface Row {
  t: number;
  confirmed: number;
  uncertain: number;
  required: number | null;
  deficit: number | null;
  spike: boolean | null;
}

const QUARTER = 15 * 60 * 1000;

function LegendKey({
  kind,
  label,
}: {
  kind: "threshold" | "confirmed" | "uncertain" | "shortfall";
  label: string;
}) {
  const swatch = {
    threshold: (
      <svg width="18" height="8" aria-hidden>
        <line
          x1="0"
          y1="4"
          x2="18"
          y2="4"
          stroke="var(--viz-threshold)"
          strokeWidth="2"
          strokeDasharray="4 3"
        />
      </svg>
    ),
    confirmed: (
      <span
        className="block h-2.5 w-3.5 rounded-sm"
        style={{ background: "var(--viz-confirmed)" }}
      />
    ),
    uncertain: (
      <span
        className="block h-2.5 w-3.5 rounded-sm border border-dashed"
        style={{
          background: "color-mix(in oklch, var(--viz-uncertain) 35%, transparent)",
          borderColor: "var(--viz-uncertain)",
        }}
      />
    ),
    shortfall: (
      <span className="block h-2.5 w-3.5 rounded-sm bg-critical/15 ring-1 ring-critical-border" />
    ),
  }[kind];
  return (
    <li className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {swatch}
      {label}
    </li>
  );
}

function ChartTooltip({
  active,
  payload,
  timezone,
}: {
  active?: boolean;
  payload?: { payload: Row }[];
  timezone: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const available = row.confirmed + row.uncertain;
  return (
    <div className="rounded-lg border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-muted-foreground">
        {formatTime(new Date(row.t).toISOString(), timezone, true)}
      </p>
      <dl className="space-y-0.5">
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Required</dt>
          <dd className="font-semibold font-mono tabular-nums">{row.required ?? "—"}</dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Available (confirmed + uncertain)</dt>
          <dd className="font-semibold font-mono tabular-nums">
            {available} ({row.confirmed} + {row.uncertain})
          </dd>
        </div>
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">Shortfall</dt>
          <dd
            className={
              row.deficit
                ? "font-semibold text-critical-ink font-mono tabular-nums"
                : "font-semibold font-mono tabular-nums"
            }
          >
            {row.deficit ?? "—"}
          </dd>
        </div>
        {row.spike ? (
          <p className="pt-0.5 text-warning-ink">Demand-spike adjustment active (+1)</p>
        ) : null}
      </dl>
    </div>
  );
}

/** Required vs available coverage over the forecast horizon, as exact step functions. */
export function CoverageChart({ coverage }: { coverage: HospitalCoverage }) {
  const tz = coverage.timezone;
  const start = new Date(coverage.as_of).getTime();
  const end = new Date(coverage.horizon_end).getTime();
  const rows: Row[] = coverage.points.map((p) => ({
    t: new Date(p.at).getTime(),
    confirmed: p.available_confirmed,
    uncertain: p.available_uncertain,
    required: p.required,
    deficit: p.deficit,
    spike: p.spike_active,
  }));
  const top =
    Math.max(1, ...rows.map((r) => Math.max(r.required ?? 0, r.confirmed + r.uncertain))) + 1;
  const ticks: number[] = [];
  for (let t = Math.ceil(start / QUARTER) * QUARTER; t <= end; t += QUARTER) ticks.push(t);
  const markers = coverage.annotations.filter(
    (a) => a.kind === "shift_end" || a.kind === "shift_start",
  );

  return (
    <figure className="space-y-2">
      <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Chart legend">
        <LegendKey kind="threshold" label="Required" />
        <LegendKey kind="confirmed" label="Available — confirmed" />
        <LegendKey kind="uncertain" label="Available — uncertain" />
        <LegendKey kind="shortfall" label="Shortfall" />
      </ul>
      <div
        className="h-64 w-full"
        role="img"
        aria-label={`Coverage forecast for ${coverage.hospital_name}: ${coverage.explanations[0] ?? ""}`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke="var(--viz-grid)" strokeWidth={1} />
            <XAxis
              dataKey="t"
              type="number"
              domain={[start, end]}
              ticks={ticks}
              tickFormatter={(t: number) =>
                formatTime(new Date(t).toISOString(), tz).replace(/\s\S+$/, "")
              }
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              stroke="var(--viz-grid)"
              tickLine={false}
            />
            <YAxis
              allowDecimals={false}
              domain={[0, top]}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              stroke="var(--viz-grid)"
              tickLine={false}
              width={44}
            />
            {coverage.segments
              .filter((s) => s.deficit)
              .map((s) => (
                <ReferenceArea
                  key={s.start}
                  x1={new Date(s.start).getTime()}
                  x2={new Date(s.end).getTime()}
                  y1={0}
                  y2={top}
                  fill="var(--critical)"
                  fillOpacity={0.1}
                  strokeOpacity={0}
                  ifOverflow="hidden"
                />
              ))}
            {markers.map((m) => (
              <ReferenceLine
                key={`${m.at}-${m.label}`}
                x={new Date(m.at).getTime()}
                stroke="var(--muted-foreground)"
                strokeOpacity={0.5}
                strokeWidth={1}
              />
            ))}
            <Area
              type="stepAfter"
              dataKey="confirmed"
              stackId="available"
              stroke="var(--viz-confirmed)"
              strokeWidth={2}
              fill="var(--viz-confirmed)"
              fillOpacity={0.12}
              isAnimationActive={false}
            />
            <Area
              type="stepAfter"
              dataKey="uncertain"
              stackId="available"
              stroke="var(--viz-uncertain)"
              strokeWidth={2}
              strokeDasharray="4 3"
              fill="var(--viz-uncertain)"
              fillOpacity={0.1}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="required"
              stroke="var(--viz-threshold)"
              strokeWidth={2}
              strokeDasharray="6 4"
              dot={false}
              activeDot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Tooltip
              content={<ChartTooltip timezone={tz} />}
              cursor={{ stroke: "var(--foreground)", strokeWidth: 1, strokeOpacity: 0.3 }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-xs text-muted-foreground">
        Times in {tz}. Steps change only at exact boundaries (shift starts/ends, local requirement
        blocks, demand-window exits). Vertical rules mark shift changes. Modeled from schedules and
        current signals — not measured outcomes.
      </figcaption>
    </figure>
  );
}
