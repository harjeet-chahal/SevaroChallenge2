"use client";

import { TagBadge } from "@/components/shared/status-badges";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ComparisonSection, MetricPair, OptimizationComparison } from "@/lib/api/types";

import { Bullets, SolverLine } from "./shared";

const OUTCOME: Record<
  MetricPair["outcome"],
  { label: string; tone: "success" | "neutral" | "warning" }
> = {
  optimized_better: { label: "Optimized better", tone: "success" },
  tie: { label: "Tie", tone: "neutral" },
  baseline_better: { label: "Baseline better", tone: "warning" },
  not_comparable: { label: "Not comparable", tone: "neutral" },
};

function value(v: number | null): string {
  if (v === null) return "—";
  return Number.isInteger(v)
    ? v.toLocaleString()
    : v.toLocaleString(undefined, {
        maximumFractionDigits: 2,
      });
}

function Section({ section }: { section: ComparisonSection }) {
  return (
    <section className="space-y-2" aria-label={section.title}>
      <h3 className="text-sm font-semibold">{section.title}</h3>
      <p className="text-sm">{section.summary}</p>
      <dl className="grid gap-1 text-xs text-muted-foreground sm:grid-cols-2">
        <div>
          <dt className="inline font-medium text-foreground">Baseline: </dt>
          <dd className="inline">{section.baseline_method}</dd>
        </div>
        <div>
          <dt className="inline font-medium text-foreground">Optimized: </dt>
          <dd className="inline">{section.optimized_method}</dd>
        </div>
      </dl>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Metric</TableHead>
              <TableHead className="text-right">Baseline</TableHead>
              <TableHead className="text-right">Optimized</TableHead>
              <TableHead>Outcome</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {section.metrics.map((m) => (
              <TableRow key={m.metric}>
                <TableCell className="whitespace-normal">
                  {m.label}
                  <span className="block text-xs text-muted-foreground">
                    {m.better} is better{m.note ? ` · ${m.note}` : ""}
                  </span>
                </TableCell>
                <TableCell className="text-right font-mono tabular-nums">{value(m.baseline)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{value(m.optimized)}</TableCell>
                <TableCell>
                  <TagBadge tone={OUTCOME[m.outcome].tone}>{OUTCOME[m.outcome].label}</TagBadge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Bullets items={section.details} className="text-xs" />
    </section>
  );
}

export function ComparisonView({ data }: { data: OptimizationComparison }) {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        {data.solvers.map((run) => (
          <SolverLine key={run.optimizer} run={run} />
        ))}
      </div>
      <Bullets items={data.notes} className="text-xs" />
      <Section section={data.dispatch} />
      <Section section={data.staffing} />
      {data.trap ? <Section section={data.trap} /> : null}
    </div>
  );
}
