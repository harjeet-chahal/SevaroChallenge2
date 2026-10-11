"use client";

import { Hospital, TrendingUp } from "lucide-react";

import { CoverageChart } from "@/components/coverage/coverage-chart";
import { EYEBROW } from "@/components/shared/page-header";
import { SectionCard } from "@/components/shared/section-card";
import { TagBadge } from "@/components/shared/status-badges";
import { useAnalysis } from "@/components/state/analysis-provider";
import { StateFallback } from "@/components/state/state-fallback";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { HospitalCoverage as HospitalCoverageData, HospitalDemand } from "@/lib/api/types";
import { formatDuration, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

function status(h: HospitalCoverageData): {
  label: string;
  tone: "critical" | "warning" | "success" | "neutral";
} {
  const m = h.metrics;
  if (!h.requirement_defined) return { label: "No requirement", tone: "neutral" };
  if (m.deficit_now) return { label: `Gap now (−${m.deficit_now})`, tone: "critical" };
  if (m.first_shortfall_at)
    return { label: `Gap at ${formatTime(m.first_shortfall_at, h.timezone)}`, tone: "warning" };
  return { label: "Covered", tone: "success" };
}

function Metric({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 rounded-[10px] bg-inset px-3 py-2.5">
      <dt className="truncate text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-mono text-lg font-semibold tabular-nums">{value}</dd>
      {hint ? <p className="text-caption text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

/**
 * Now → end of the forecast as one bar: time left before the first shortfall in primary,
 * every forecast segment with a deficit hatched in critical. Straight from the segments.
 */
function ShortfallWindow({ h }: { h: HospitalCoverageData }) {
  const start = Date.parse(h.as_of);
  const end = Date.parse(h.horizon_end);
  const span = end - start;
  if (!(span > 0) || !h.requirement_defined) return null;
  const pct = (iso: string) =>
    Math.min(100, Math.max(0, ((Date.parse(iso) - start) / span) * 100));
  const first = h.metrics.first_shortfall_at;
  const firstPct = first ? pct(first) : 100;
  const until = h.metrics.minutes_until_shortfall;
  const gaps = h.segments.filter((seg) => seg.deficit);
  const summary = !first
    ? `Covered to ${formatTime(h.horizon_end, h.timezone)}`
    : until === 0
      ? "Short now"
      : `Shortfall in ${formatDuration(Math.round(until ?? 0))}`;

  return (
    <div
      role="img"
      aria-label={`${summary}. Forecast to ${formatTime(h.horizon_end, h.timezone)}.`}
    >
      <div className="flex items-baseline justify-between gap-2 text-caption">
        <span className={EYEBROW}>Coverage window</span>
        <span
          className={cn(
            "font-mono font-medium tabular-nums",
            !first ? "text-success-ink" : until === 0 ? "text-critical-ink" : "text-warning-ink",
          )}
        >
          {summary}
        </span>
      </div>
      <div className="relative mt-2.5 h-2 rounded-full bg-border">
        <div
          className={cn(
            "absolute inset-y-0 left-0 origin-left animate-ng-fill rounded-full",
            first ? "bg-primary" : "bg-success",
          )}
          style={{ width: `${firstPct}%` }}
        />
        {gaps.map((seg) => (
          <div
            key={seg.start}
            className="absolute inset-y-0 rounded-[2px] bg-critical-soft hatch-critical"
            style={{ left: `${pct(seg.start)}%`, width: `${pct(seg.end) - pct(seg.start)}%` }}
          />
        ))}
        <span aria-hidden className="absolute -inset-y-1.5 left-0 w-0.5 rounded-full bg-foreground" />
        {first ? (
          <span
            aria-hidden
            className="absolute -inset-y-1.5 w-0.5 rounded-full bg-critical"
            style={{ left: `${firstPct}%` }}
          />
        ) : null}
      </div>
      <div aria-hidden className="relative mt-1.5 h-4 text-micro text-muted-foreground uppercase">
        <span className="absolute left-0">Now</span>
        {first && firstPct > 14 && firstPct < 80 ? (
          <span
            className="absolute -translate-x-1/2 whitespace-nowrap text-critical-ink"
            style={{ left: `${firstPct}%` }}
          >
            Short {formatTime(first, h.timezone)}
          </span>
        ) : null}
        <span className="absolute right-0">{formatTime(h.horizon_end, h.timezone)}</span>
      </div>
    </div>
  );
}

function DemandLine({ d, tz }: { d: HospitalDemand | undefined; tz: string }) {
  if (!d) return null;
  const c = d.current;
  if (c.spike === null) {
    return (
      <p className="text-sm text-muted-foreground">
        Demand: {c.arrivals} consult(s) in the last 60 min; no usable p90 baseline for{" "}
        {c.local_hour_label} ({c.baseline_status.replaceAll("_", " ")}), so the spike rule cannot be
        evaluated.
      </p>
    );
  }
  return (
    <p
      className={cn(
        "flex flex-wrap items-center gap-1.5 text-sm",
        c.spike ? "text-foreground" : "text-muted-foreground",
      )}
    >
      {c.spike ? (
        <TagBadge tone="warning">
          <TrendingUp className="size-3" aria-hidden />
          Demand spike +1
        </TagBadge>
      ) : null}
      <span>
        {c.arrivals} consult(s) in the last 60 min vs p90 {c.baseline_p90} for {c.local_hour_label}
        {c.spike && d.spike_ends_at
          ? `; spike ends ${formatTime(d.spike_ends_at, tz)} if no new arrivals`
          : ""}
        .
      </span>
    </p>
  );
}

export function HospitalCoverage({ className }: { className?: string }) {
  const { coverage, demand, selectedHospitalId, selectHospital } = useAnalysis();
  const report = coverage.data;
  const selected = report?.hospitals.find((h) => h.hospital_id === selectedHospitalId);
  const demandFor = demand.data?.hospitals.find((d) => d.hospital_id === selectedHospitalId);

  return (
    <SectionCard
      className={className}
      title="Hospital coverage"
      icon={Hospital}
      info={`Required vs available credentialed physicians, now and for the next ${report?.horizon_minutes ?? 90} minutes. Each hospital uses its own local time.`}
    >
      {report && selected ? (
        <div className={cn("space-y-4", coverage.loading && "opacity-60 transition-opacity")}>
          <div
            className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5"
            role="group"
            aria-label="Choose hospital"
          >
            {report.hospitals.map((h) => {
              const s = status(h);
              const spiking = demand.data?.hospitals.find((d) => d.hospital_id === h.hospital_id)
                ?.current.spike;
              const active = h.hospital_id === selected.hospital_id;
              return (
                <button
                  key={h.hospital_id}
                  type="button"
                  aria-pressed={active}
                  onClick={() => selectHospital(h.hospital_id)}
                  className={cn(
                    "rounded-[10px] border border-border bg-card p-2.5 text-left outline-none hover:border-border-strong focus-visible:ring-3 focus-visible:ring-ring/50",
                    active && "border-primary-border bg-primary-soft hover:border-primary-border",
                  )}
                >
                  <span className="block truncate text-sm font-semibold text-foreground">
                    {h.hospital_name}
                  </span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    <TagBadge tone={s.tone}>{s.label}</TagBadge>
                    {spiking ? <TagBadge tone="warning">Spike</TagBadge> : null}
                  </span>
                </button>
              );
            })}
          </div>

          <ShortfallWindow h={selected} />

          <dl className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,150px),1fr))] gap-2">
            <Metric label="Required now" value={selected.metrics.required_now ?? "—"} />
            <Metric
              label="Available now"
              value={selected.metrics.available_now}
              hint={`${selected.segments[0].available_confirmed} confirmed · ${selected.segments[0].available_uncertain} uncertain`}
            />
            <Metric
              label="First shortfall"
              value={
                selected.metrics.first_shortfall_at
                  ? formatTime(selected.metrics.first_shortfall_at, selected.timezone)
                  : "None"
              }
              hint={
                selected.metrics.minutes_until_shortfall !== null
                  ? selected.metrics.minutes_until_shortfall === 0
                    ? "now"
                    : `in ${Math.round(selected.metrics.minutes_until_shortfall)} min, for ${selected.metrics.shortfall_minutes} min`
                  : undefined
              }
            />
            <Metric
              label="Deficit (physician-min)"
              value={selected.metrics.deficit_physician_minutes}
              hint={`${selected.metrics.deficit_physician_minutes_if_uncertain_excluded} if uncertain coverage is excluded`}
            />
            <Metric
              label="Confidence"
              value={<span className="font-sans capitalize">{selected.metrics.confidence}</span>}
            />
          </dl>

          <DemandLine d={demandFor} tz={selected.timezone} />
          <CoverageChart coverage={selected} />

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-1">
              <h3 className={EYEBROW}>Why</h3>
              <ul className="list-disc space-y-0.5 pl-4 text-sm text-muted-foreground">
                {selected.explanations.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
            <div className="space-y-1">
              <h3 className={EYEBROW}>Physicians considered</h3>
              <ul className="space-y-1 text-sm">
                {selected.contributors.map((c) => (
                  <li key={c.physician_id} className="flex flex-wrap items-baseline gap-1.5">
                    <span className="font-medium">{c.display_name}</span>
                    <TagBadge
                      tone={
                        c.status === "excluded"
                          ? "neutral"
                          : c.certainty === "uncertain"
                            ? "info"
                            : "success"
                      }
                    >
                      {c.status === "joins_later"
                        ? "joins later"
                        : c.status === "pending_activation"
                          ? "accepted · pending activation"
                          : c.status}
                      {c.certainty ? ` · ${c.certainty}` : ""}
                    </TagBadge>
                    <span className="text-xs text-muted-foreground">
                      {c.counts_from && c.status !== "excluded"
                        ? `${formatTime(c.counts_from, selected.timezone)}–${c.counts_until ? formatTime(c.counts_until, selected.timezone) : "end unknown"} · `
                        : ""}
                      {c.reasons.join("; ")}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              Table view: exact forecast segments
            </summary>
            <div className="-mx-4 mt-2 overflow-x-auto">
              <Table className="min-w-[560px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-4">From</TableHead>
                    <TableHead>To</TableHead>
                    <TableHead className="text-right">Required (base + spike)</TableHead>
                    <TableHead className="text-right">Available (confirmed + uncertain)</TableHead>
                    <TableHead className="pr-4 text-right">Shortfall</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selected.segments.map((s) => (
                    <TableRow key={s.start}>
                      <TableCell className="pl-4 font-mono tabular-nums">
                        {formatTime(s.start, selected.timezone, true)}
                      </TableCell>
                      <TableCell className="font-mono tabular-nums">
                        {formatTime(s.end, selected.timezone, true)}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {s.required ?? "—"} ({s.required_base ?? "—"} + {s.spike_adjustment ?? "?"})
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {s.available} ({s.available_confirmed} + {s.available_uncertain})
                      </TableCell>
                      <TableCell
                        className={cn(
                          "pr-4 text-right font-mono tabular-nums",
                          s.deficit ? "font-semibold text-critical-ink" : "",
                        )}
                      >
                        {s.deficit ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </details>
        </div>
      ) : (
        <StateFallback
          resource={coverage}
          feature="coverage forecast"
          whenNoDataset="Coverage per hospital appears once hospitals, credentials, shifts and coverage requirements are loaded."
        />
      )}
    </SectionCard>
  );
}
