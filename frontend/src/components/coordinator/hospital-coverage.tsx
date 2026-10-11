"use client";

import { Hospital, TrendingUp } from "lucide-react";

import { CoverageChart } from "@/components/coverage/coverage-chart";
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
import { formatTime } from "@/lib/format";
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
    <div className="rounded-lg border bg-card p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-lg font-semibold tabular-nums">{value}</dd>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
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
      description={`Required vs available credentialed physicians, now and for the next ${report?.horizon_minutes ?? 90} minutes. Each hospital uses its own local time.`}
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
                    "rounded-lg border bg-card p-2.5 text-left transition-colors outline-none hover:bg-muted/40 focus-visible:ring-3 focus-visible:ring-ring/50",
                    active && "border-primary ring-1 ring-primary/40",
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

          <dl className="grid grid-cols-2 gap-2 lg:grid-cols-5">
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
              value={<span className="capitalize">{selected.metrics.confidence}</span>}
            />
          </dl>

          <DemandLine d={demandFor} tz={selected.timezone} />
          <CoverageChart coverage={selected} />

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold">Why</h3>
              <ul className="list-disc space-y-0.5 pl-4 text-sm text-muted-foreground">
                {selected.explanations.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </div>
            <div className="space-y-1">
              <h3 className="text-sm font-semibold">Physicians considered</h3>
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
            <summary className="cursor-pointer text-muted-foreground">
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
                      <TableCell className="pl-4 tabular-nums">
                        {formatTime(s.start, selected.timezone, true)}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {formatTime(s.end, selected.timezone, true)}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s.required ?? "—"} ({s.required_base ?? "—"} + {s.spike_adjustment ?? "?"})
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {s.available} ({s.available_confirmed} + {s.available_uncertain})
                      </TableCell>
                      <TableCell
                        className={cn(
                          "pr-4 text-right tabular-nums",
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
