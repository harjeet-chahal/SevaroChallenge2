"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { CoverageSegment, HospitalProjection } from "@/lib/api/types";
import { formatTime } from "@/lib/format";

interface Row {
  t: number;
  required: number | null;
  current: number;
  projected: number;
  deficitBefore: number | null;
  deficitAfter: number | null;
}

const QUARTER = 15 * 60 * 1000;
const STEP = 5 * 60 * 1000;

function at(segments: CoverageSegment[], t: number): CoverageSegment {
  return (
    segments.find((s) => new Date(s.start).getTime() <= t && t < new Date(s.end).getTime()) ??
    segments[segments.length - 1]
  );
}

function Key({
  kind,
  label,
}: {
  kind: "threshold" | "current" | "projected" | "closed" | "open";
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
    current: (
      <svg width="18" height="8" aria-hidden>
        <line x1="0" y1="4" x2="18" y2="4" stroke="var(--viz-confirmed)" strokeWidth="2" />
      </svg>
    ),
    projected: (
      <span
        className="block h-2.5 w-3.5 rounded-sm border"
        style={{
          background: "color-mix(in oklch, var(--viz-uncertain) 30%, transparent)",
          borderColor: "var(--viz-uncertain)",
        }}
      />
    ),
    closed: (
      <span className="block h-2.5 w-3.5 rounded-sm bg-success/15 ring-1 ring-success-border" />
    ),
    open: (
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
  const r = payload[0].payload;
  const line = (label: string, v: React.ReactNode, strong = false) => (
    <div className="flex justify-between gap-4">
      <dt className="text-muted-foreground">{label}</dt>
      <dd
        className={
          strong ? "font-semibold text-critical-ink font-mono tabular-nums" : "font-semibold font-mono tabular-nums"
        }
      >
        {v}
      </dd>
    </div>
  );
  return (
    <div className="rounded-lg border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium text-muted-foreground">
        {formatTime(new Date(r.t).toISOString(), timezone)}
      </p>
      <dl className="space-y-0.5">
        {line("Required", r.required ?? "—")}
        {line("Available — current forecast", r.current)}
        {line("Available — projected if accepted", r.projected)}
        {line("Shortfall — current", r.deficitBefore ?? "—", Boolean(r.deficitBefore))}
        {line("Shortfall — if accepted", r.deficitAfter ?? "—", Boolean(r.deficitAfter))}
      </dl>
    </div>
  );
}

/**
 * Current forecast vs the projection if a proposal were accepted, from the backend's two
 * coverage runs. The projection is drawn as its own series and never replaces the forecast.
 */
export function ProjectionChart({ projection }: { projection: HospitalProjection }) {
  const { before, after } = projection;
  const tz = before.timezone;
  const start = new Date(before.as_of).getTime();
  const end = new Date(before.horizon_end).getTime();
  const times = new Set<number>([end]);
  for (const s of [...before.segments, ...after.segments]) times.add(new Date(s.start).getTime());
  for (let t = start; t < end; t += STEP) times.add(t);
  const rows: Row[] = [...times]
    .sort((a, b) => a - b)
    .map((t) => {
      const b = at(before.segments, t);
      const a = at(after.segments, t);
      return {
        t,
        required: b.required,
        current: b.available,
        projected: a.available,
        deficitBefore: b.deficit,
        deficitAfter: a.deficit,
      };
    });
  const top = Math.max(1, ...rows.map((r) => Math.max(r.required ?? 0, r.projected))) + 1;
  const ticks: number[] = [];
  for (let t = Math.ceil(start / QUARTER) * QUARTER; t <= end; t += QUARTER) ticks.push(t);
  const shading: { x1: number; x2: number; open: boolean }[] = [];
  for (let i = 0; i < rows.length - 1; i += 1) {
    const r = rows[i];
    if (!r.deficitBefore && !r.deficitAfter) continue;
    shading.push({ x1: r.t, x2: rows[i + 1].t, open: Boolean(r.deficitAfter) });
  }

  return (
    <figure className="space-y-2">
      <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Chart legend">
        <Key kind="threshold" label="Required" />
        <Key kind="current" label="Available — current forecast" />
        <Key kind="projected" label="Available — projected if accepted" />
        <Key kind="closed" label="Shortfall closed if accepted" />
        <Key kind="open" label="Shortfall remaining" />
      </ul>
      <div
        className="h-56 w-full"
        role="img"
        aria-label={`${projection.hospital_name}: deficit ${projection.deficit_physician_minutes_before} to ${projection.deficit_physician_minutes_after} physician-minutes if accepted (projection, not confirmed).`}
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
            {shading.map((s) => (
              <ReferenceArea
                key={s.x1}
                x1={s.x1}
                x2={s.x2}
                y1={0}
                y2={top}
                fill={s.open ? "var(--critical)" : "var(--success)"}
                fillOpacity={0.12}
                strokeOpacity={0}
                ifOverflow="hidden"
              />
            ))}
            <Area
              type="stepAfter"
              dataKey="projected"
              stroke="var(--viz-uncertain)"
              strokeWidth={2}
              fill="var(--viz-uncertain)"
              fillOpacity={0.15}
              isAnimationActive={false}
            />
            <Line
              type="stepAfter"
              dataKey="current"
              stroke="var(--viz-confirmed)"
              strokeWidth={2}
              dot={false}
              activeDot={false}
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
              cursor={{
                stroke: "var(--foreground)",
                strokeWidth: 1,
                strokeOpacity: 0.3,
              }}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-xs text-muted-foreground">
        Times in {tz}. Projected if accepted — not confirmed coverage. The live forecast above is
        unchanged until an offer is actually accepted.
      </figcaption>
    </figure>
  );
}
