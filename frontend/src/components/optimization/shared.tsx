"use client";

import { CircleCheck, CircleHelp, CircleX, Cpu } from "lucide-react";

import { TagBadge } from "@/components/shared/status-badges";
import type { RuleCheck, SolverRun } from "@/lib/api/types";
import { cn } from "@/lib/utils";

const SOLVER_NAMES: Record<string, string> = {
  "ortools.SimpleMinCostFlow": "OR-Tools min-cost flow",
  "ortools.CpSolver": "OR-Tools CP-SAT",
  fallback_greedy: "Fallback heuristic (OR-Tools unavailable)",
};

/** Which solver ran and what it can honestly claim about the answer. */
export function SolverLine({ run }: { run: SolverRun }) {
  const tone =
    run.status === "OPTIMAL"
      ? "success"
      : run.status === "FEASIBLE" || run.status === "FALLBACK"
        ? "warning"
        : "critical";
  const claim = run.proven_optimal
    ? "proven optimal"
    : run.status === "FEASIBLE"
      ? "best found within the time limit"
      : run.status === "FALLBACK"
        ? "heuristic — optimality not claimed"
        : run.status === "INFEASIBLE"
          ? "no plan satisfies every constraint"
          : "no solution";
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <Cpu className="size-3.5" aria-hidden />
      <span className="font-medium text-foreground">{SOLVER_NAMES[run.solver] ?? run.solver}</span>
      <TagBadge tone={tone}>{run.status}</TagBadge>
      <span>
        {claim} · {run.wall_time_ms.toFixed(1)} ms
      </span>
    </p>
  );
}

/** Pass / fail / missing for one rule. Icon + word, never colour alone. */
export function CheckMark({ check, showLabel = false }: { check: RuleCheck; showLabel?: boolean }) {
  const missing = !check.passed && check.missing_data;
  const Icon = check.passed ? CircleCheck : missing ? CircleHelp : CircleX;
  const word = check.passed ? "Pass" : missing ? "Missing" : "Fail";
  return (
    <span
      title={`${check.label}: ${check.message}${check.value ? ` (${check.value})` : ""}`}
      className={cn(
        "inline-flex items-center gap-1 text-xs font-medium",
        check.passed ? "text-success" : missing ? "text-warning" : "text-critical",
      )}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      {showLabel ? check.label : <span className="sr-only sm:not-sr-only">{word}</span>}
      {showLabel ? null : <span className="sr-only">: {check.message}</span>}
    </span>
  );
}

export function urgencyTone(tier: number): "critical" | "warning" | "neutral" {
  if (tier >= 4) return "critical";
  if (tier >= 2) return "warning";
  return "neutral";
}

export function ProposedNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-info-border bg-info-soft px-3 py-2 text-xs text-info">
      {children}
    </p>
  );
}

export function Bullets({ items, className }: { items: string[]; className?: string }) {
  if (!items.length) return null;
  return (
    <ul className={cn("list-disc space-y-0.5 pl-4 text-sm text-muted-foreground", className)}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export function Disclosure({ summary, children }: { summary: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-md border bg-muted/30 px-3 py-2 text-sm">
      <summary className="cursor-pointer font-medium text-foreground outline-none select-none focus-visible:ring-3 focus-visible:ring-ring/50">
        {summary}
      </summary>
      <div className="mt-2 space-y-2">{children}</div>
    </details>
  );
}
