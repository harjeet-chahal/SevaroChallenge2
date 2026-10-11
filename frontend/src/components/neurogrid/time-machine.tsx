"use client";

import { Activity, CalendarClock, Gauge, Pause, Play, Radio, SkipForward, Waves } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SectionCard } from "@/components/shared/section-card";
import { Button } from "@/components/ui/button";
import { useLiveResource } from "@/hooks/use-live-resource";
import { formatTime } from "@/lib/format";
import { neurogridApi, type TimeMachineFrame, type TimeMachineReport } from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import { CLASS_LABEL, Gate, KeyValue, Pill, Projected, fmtMin } from "./kit";

const MARKERS = [0, 15, 30, 60, 90];

function nearest(frames: TimeMachineFrame[], offset: number): number {
  let best = 0;
  frames.forEach((f, i) => {
    if (Math.abs(f.offset_minutes - offset) < Math.abs(frames[best].offset_minutes - offset)) best = i;
  });
  return best;
}

/** Network-level times use the scenario's reference zone (Eastern); per-hospital
 * tooltips use each hospital's own zone. */
const NETWORK_ZONE = "America/New_York";

function zoneOf(r: TimeMachineReport): string {
  void r;
  return NETWORK_ZONE;
}

function Scrubber({
  r,
  index,
  setIndex,
}: {
  r: TimeMachineReport;
  index: number;
  setIndex: (i: number) => void;
}) {
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setIndex(index + 1 >= r.frames.length ? 0 : index + 1);
    }, 700);
    return () => window.clearInterval(id);
  }, [playing, index, r.frames.length, setIndex]);
  const f = r.frames[index];
  const tz = zoneOf(r);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant={playing ? "secondary" : "default"}
          onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? "Pause projection playback" : "Play projection playback"}
        >
          {playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
          {playing ? "Pause" : "Play"}
        </Button>
        {MARKERS.map((m) => (
          <Button
            key={m}
            size="sm"
            variant="outline"
            onClick={() => setIndex(nearest(r.frames, m))}
            className={cn(Math.abs(f.offset_minutes - m) < 0.01 && "border-primary text-primary")}
          >
            {m === 0 ? "Now" : `+${m}`}
          </Button>
        ))}
        <span className="ml-auto flex items-center gap-2 text-sm">
          {f.observed ? (
            <Pill tone="success" icon={Radio}>
              Observed now
            </Pill>
          ) : (
            <Pill tone="info" icon={SkipForward}>
              Projected +{fmtMin(f.offset_minutes)}
            </Pill>
          )}
          <span className="font-semibold tabular-nums">{formatTime(f.at, tz)}</span>
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={r.frames.length - 1}
        value={index}
        onChange={(e) => setIndex(Number(e.target.value))}
        aria-label="Scrub the projected timeline"
        aria-valuetext={`${formatTime(f.at, tz)}, ${f.observed ? "observed" : "projected"}`}
        className="w-full accent-[var(--primary)]"
      />
      <p className="text-xs text-muted-foreground">
        Playback steps through the backend&apos;s projected frames; it does not move the simulation clock. Exact
        shift and requirement boundaries are included as their own frames.
      </p>
    </div>
  );
}

function NetworkChart({ r, index }: { r: TimeMachineReport; index: number }) {
  const tz = zoneOf(r);
  const rows = r.frames.map((f) => ({
    t: new Date(f.at).getTime(),
    deficit: f.network_deficit,
    short: f.hospitals_short,
    required: f.network_required,
    observed: f.observed,
    labels: f.labels,
  }));
  const sel = rows[index]?.t;
  const top = Math.max(2, ...rows.map((x) => x.deficit)) + 1;
  return (
    <figure className="space-y-1">
      <figcaption className="text-sm font-medium">
        Network coverage deficit (physicians short, summed over hospitals) <Projected className="ml-1" />
      </figcaption>
      <div className="h-52 w-full" role="img" aria-label="Projected network coverage deficit over the horizon">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) => formatTime(new Date(t).toISOString(), tz).replace(/\s\S+$/, "")}
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
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const row = payload[0].payload as (typeof rows)[number];
                return (
                  <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
                    <p className="font-medium text-muted-foreground">
                      {formatTime(new Date(row.t).toISOString(), tz)} · {row.observed ? "observed" : "projected"}
                    </p>
                    <p>
                      Deficit <b className="tabular-nums">{row.deficit}</b> · hospitals short{" "}
                      <b className="tabular-nums">{row.short}</b>
                    </p>
                    {row.labels.length ? <p className="text-muted-foreground">{row.labels.join(", ")}</p> : null}
                  </div>
                );
              }}
            />
            <Area
              type="stepAfter"
              dataKey="deficit"
              stroke="var(--viz-critical)"
              strokeWidth={2}
              fill="var(--viz-critical)"
              fillOpacity={0.18}
              isAnimationActive={false}
            />
            {sel ? <ReferenceLine x={sel} stroke="var(--primary)" strokeWidth={2} /> : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function cellState(h: TimeMachineFrame["hospitals"][number]) {
  if (h.required === null) return { tone: "bg-muted/40", label: "no requirement" };
  if ((h.deficit ?? 0) > 0) return { tone: "bg-critical/70", label: `short ${h.deficit}` };
  const spare = h.confirmed + h.uncertain - h.required;
  if (spare === 0) return { tone: "bg-warning/55", label: "zero spare" };
  if (h.confirmed < h.required) return { tone: "bg-info/45", label: "relies on uncertain" };
  return { tone: "bg-success/30", label: `spare ${spare}` };
}

function HospitalGrid({ r, index, setIndex }: { r: TimeMachineReport; index: number; setIndex: (i: number) => void }) {
  const tz = zoneOf(r);
  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Grid legend">
        <li className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-critical/70" />Short</li>
        <li className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-warning/55" />Zero spare</li>
        <li className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-info/45" />Met only with uncertain capacity</li>
        <li className="flex items-center gap-1.5"><span className="size-3 rounded-sm bg-success/30" />Spare capacity</li>
      </ul>
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-[2px] text-xs">
          <thead>
            <tr>
              <th className="sticky left-0 z-10 bg-card pr-2 text-left font-medium text-muted-foreground">Hospital</th>
              {r.frames.map((f, i) => (
                <th key={f.at} className="min-w-5 font-normal">
                  <button
                    type="button"
                    onClick={() => setIndex(i)}
                    className={cn(
                      "w-full rounded px-0.5 text-[0.6rem] text-muted-foreground tabular-nums hover:text-foreground",
                      i === index && "bg-primary/20 text-primary",
                    )}
                    title={formatTime(f.at, tz)}
                  >
                    {f.kind === "boundary" ? "•" : Math.round(f.offset_minutes)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {r.hospitals.map((h) => (
              <tr key={h.hospital_id}>
                <th scope="row" className="sticky left-0 z-10 max-w-40 truncate bg-card pr-2 text-left font-medium">
                  {h.name}
                </th>
                {r.frames.map((f, i) => {
                  const cell = f.hospitals.find((x) => x.hospital_id === h.hospital_id);
                  if (!cell) return <td key={f.at} />;
                  const s = cellState(cell);
                  return (
                    <td
                      key={f.at}
                      title={`${h.name} ${formatTime(f.at, h.timezone)}: required ${cell.required ?? "—"}, confirmed ${cell.confirmed}, uncertain ${cell.uncertain} — ${s.label}${f.observed ? "" : " (projected)"}`}
                      onClick={() => setIndex(i)}
                      className={cn("h-5 cursor-pointer rounded-sm", s.tone, i === index && "ring-2 ring-primary")}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Column numbers are minutes from now; • marks an exact shift/requirement boundary. Hover a cell for the counts.
      </p>
    </div>
  );
}

function RankingAt({ r, index }: { r: TimeMachineReport; index: number }) {
  const f = r.frames[index];
  const names = Object.fromEntries(r.hospitals.map((h) => [h.hospital_id, h.name]));
  const rows = [...f.hospitals]
    .filter((h) => h.required !== null)
    .map((h) => ({ ...h, spare: h.confirmed + h.uncertain - (h.required ?? 0) }))
    .sort((a, b) => (b.deficit ?? 0) - (a.deficit ?? 0) || a.spare - b.spare || a.hospital_id.localeCompare(b.hospital_id))
    .slice(0, 6);
  return (
    <ol className="space-y-1.5 text-sm">
      {rows.map((h, i) => (
        <li key={h.hospital_id} className="flex items-center gap-2">
          <span className="w-4 text-right text-muted-foreground tabular-nums">{i + 1}</span>
          <span className="min-w-0 flex-1 truncate">{names[h.hospital_id]}</span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {h.confirmed + h.uncertain}/{h.required}
          </span>
          {(h.deficit ?? 0) > 0 ? (
            <Pill tone="critical">short {h.deficit}</Pill>
          ) : h.spare === 0 ? (
            <Pill tone="warning">zero spare</Pill>
          ) : (
            <Pill tone="success">+{h.spare}</Pill>
          )}
        </li>
      ))}
    </ol>
  );
}

function Lanes({ r, index }: { r: TimeMachineReport; index: number }) {
  const start = new Date(r.as_of).getTime();
  const end = start + r.horizon_minutes * 60_000;
  const pct = (t: number) => `${Math.min(100, Math.max(0, ((t - start) / (end - start)) * 100))}%`;
  const sel = new Date(r.frames[index].at).getTime();
  const tz = zoneOf(r);
  const tone = {
    scheduled: "bg-[var(--viz-confirmed)]",
    assumed: "bg-[var(--viz-uncertain)]/70 border border-dashed border-[var(--viz-uncertain)]",
    rescue_pending: "bg-warning/60 border border-dashed border-warning",
    rescue_active: "bg-primary",
  } as const;
  const visible = r.lanes.filter((l) => l.segments.some((s) => new Date(s.start).getTime() < end && (!s.end || new Date(s.end).getTime() > start)));
  return (
    <div className="space-y-2">
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-[var(--viz-confirmed)]" />Scheduled</li>
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm border border-dashed border-[var(--viz-uncertain)] bg-[var(--viz-uncertain)]/70" />Assumed (end unknown)</li>
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm border border-dashed border-warning bg-warning/60" />Rescue pending activation</li>
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-primary" />Rescue active</li>
      </ul>
      <div className="relative space-y-1.5">
        <div className="pointer-events-none absolute inset-y-0 left-40 right-0">
          <div className="absolute inset-y-0 w-0.5 bg-primary" style={{ left: pct(sel) }} />
        </div>
        {visible.map((l) => (
          <div key={l.physician_id} className="flex items-center gap-2">
            <span className="w-38 shrink-0 truncate text-xs" title={`${l.display_name} · ${CLASS_LABEL[l.availability_class]}`}>
              {l.display_name}
            </span>
            <div className="relative h-4 flex-1 rounded bg-muted/50">
              {l.segments.map((s) => {
                const a = Math.max(start, new Date(s.start).getTime());
                const b = s.end ? Math.min(end, new Date(s.end).getTime()) : end;
                if (b <= a) return null;
                return (
                  <div
                    key={`${s.start}-${s.kind}`}
                    title={`${s.label}: ${formatTime(s.start, tz)} – ${s.end ? formatTime(s.end, tz) : "end unknown"}`}
                    className={cn("absolute inset-y-0 rounded", tone[s.kind])}
                    style={{ left: pct(a), width: `calc(${pct(b)} - ${pct(a)})` }}
                  />
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DemandPanel({ r }: { r: TimeMachineReport }) {
  const [hid, setHid] = useState<string>(r.hospitals[0]?.hospital_id ?? "");
  const tz = r.hospitals.find((h) => h.hospital_id === hid)?.timezone ?? zoneOf(r);
  const rows = r.demand
    .filter((b) => b.hospital_id === hid)
    .map((b) => ({
      t: new Date(b.at).getTime(),
      band: [b.p10_trailing_hour, b.p90_trailing_hour] as [number, number],
      p50: b.p50_trailing_hour,
      threshold: b.p90_threshold,
      share: b.share_runs_above_threshold,
    }));
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="demand-h" className="text-sm font-medium">
          Hospital
        </label>
        <select
          id="demand-h"
          value={hid}
          onChange={(e) => setHid(e.target.value)}
          className="rounded-md border bg-card px-2 py-1 text-sm"
        >
          {r.hospitals.map((h) => (
            <option key={h.hospital_id} value={h.hospital_id}>
              {h.name}
            </option>
          ))}
        </select>
        <Pill tone="info">{String(r.stochastic.runs)} seeded Poisson runs</Pill>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-[var(--viz-confirmed)]/30" />p10–p90 trailing-hour arrivals</li>
        <li className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[var(--viz-confirmed)]" />Median</li>
        <li className="flex items-center gap-1.5">
          <svg width="18" height="8" aria-hidden><line x1="0" y1="4" x2="18" y2="4" stroke="var(--viz-threshold)" strokeWidth="2" strokeDasharray="4 3" /></svg>
          Spike threshold (hourly p90)
        </li>
      </ul>
      <div className="h-48 w-full" role="img" aria-label="Stochastic demand sensitivity band">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke="var(--viz-grid)" />
            <XAxis
              dataKey="t"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) => formatTime(new Date(t).toISOString(), tz).replace(/\s\S+$/, "")}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              stroke="var(--viz-grid)"
              tickLine={false}
            />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} stroke="var(--viz-grid)" tickLine={false} width={44} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const row = payload[0].payload as (typeof rows)[number];
                return (
                  <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
                    <p className="font-medium text-muted-foreground">{formatTime(new Date(row.t).toISOString(), tz)} (projected)</p>
                    <p>p10–p90: {row.band[0]}–{row.band[1]} · median {row.p50}</p>
                    <p>Threshold {row.threshold ?? "—"} · {(row.share * 100).toFixed(0)}% of runs above</p>
                  </div>
                );
              }}
            />
            <Area dataKey="band" stroke="none" fill="var(--viz-confirmed)" fillOpacity={0.25} isAnimationActive={false} />
            <Line dataKey="p50" stroke="var(--viz-confirmed)" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="threshold" stroke="var(--viz-threshold)" strokeDasharray="4 3" strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        {String(r.stochastic.model)}. Seed {String(r.stochastic.seed)}. {String(r.stochastic.label)}.
      </p>
    </div>
  );
}

function Freshness({ r }: { r: TimeMachineReport }) {
  const f = r.freshness as Record<string, number | string | null | Record<string, number>>;
  const lag = f.minutes_since_last_ingest as number | null;
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <KeyValue label="Since last ingest" value={lag === null ? "—" : fmtMin(lag)} hint="simulation minutes" />
      <KeyValue label="Pending ingestion" value={String(f.events_pending_ingestion ?? 0)} hint="events after now" />
      <KeyValue label="Late arrivals applied" value={String(f.late_arrivals_applied ?? 0)} hint="by event_time" />
      <KeyValue label="Duplicates skipped" value={String(f.duplicates_skipped ?? 0)} hint={`${String(f.conflicting_duplicates ?? 0)} conflicting`} />
    </div>
  );
}

export function TimeMachine() {
  const [rate, setRate] = useState(1);
  const res = useLiveResource((s) => neurogridApi.timeMachine(rate === 1 ? null : rate, s), String(rate));
  const [index, setIndex] = useState(0);
  const frames = res.data?.frames.length ?? 0;
  const safeIndex = Math.min(index, Math.max(0, frames - 1));
  const summary = useMemo(() => res.data?.frames[safeIndex], [res.data, safeIndex]);
  return (
    <div className="space-y-6">
      <SectionCard title="Coverage Time Machine" icon={CalendarClock} description="Scrub the next 90 minutes. Every panel follows the selected time. Only 'now' is observed.">
        <Gate resource={res} feature="the coverage time machine">
          {(r) => (
            <div className="space-y-5">
              <Scrubber r={r} index={safeIndex} setIndex={setIndex} />
              {summary ? (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <KeyValue label="Hospitals short" value={summary.hospitals_short} hint={summary.observed ? "observed" : "projected"} />
                  <KeyValue label="Physicians short (sum)" value={summary.network_deficit} hint={summary.observed ? "observed" : "projected"} />
                  <KeyValue label="Required positions" value={summary.network_required} hint="per-hospital requirements" />
                  <KeyValue label="Changes in this step" value={summary.labels.length} hint={summary.labels.slice(0, 2).join(", ") || "none"} />
                </div>
              ) : null}
              <NetworkChart r={r} index={safeIndex} />
              <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
                <div className="min-w-0">
                  <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><Gauge className="size-4 text-primary" aria-hidden />Hospital coverage over time</h3>
                  <HospitalGrid r={r} index={safeIndex} setIndex={setIndex} />
                </div>
                <div>
                  <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold"><Activity className="size-4 text-primary" aria-hidden />Hospital risk at selected time</h3>
                  <RankingAt r={r} index={safeIndex} />
                </div>
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold">Physician shift timeline</h3>
                <Lanes r={r} index={safeIndex} />
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold">Data freshness</h3>
                <Freshness r={r} />
              </div>
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                {r.notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          )}
        </Gate>
      </SectionCard>
      <SectionCard
        title="Demand sensitivity (stochastic layer)"
        icon={Waves}
        description="Seeded Poisson arrivals at each hospital's baseline mean. A labelled assumption, not a prediction of real patients."
        action={
          <label className="flex items-center gap-2 text-xs">
            Rate ×
            <select value={rate} onChange={(e) => setRate(Number(e.target.value))} className="rounded border bg-card px-1.5 py-0.5">
              {[0.5, 1, 1.5, 2, 3].map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </label>
        }
      >
        <Gate resource={res} feature="stochastic demand">
          {(r) => <DemandPanel r={r} />}
        </Gate>
      </SectionCard>
    </div>
  );
}
