"use client";

import { BadgeDollarSign } from "lucide-react";

import { TagBadge } from "@/components/shared/status-badges";
import type { CostComparison, CostEstimate, PlanCost } from "@/lib/api/types";
import { formatDuration, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Bullets, Disclosure } from "./shared";

/** Simulated (projected if accepted) vs confirmed (from a completed shift), in words. */
export function BasisBadge({ basis }: { basis: "simulated" | "confirmed" }) {
  return basis === "confirmed" ? (
    <TagBadge tone="success">Confirmed</TagBadge>
  ) : (
    <TagBadge tone="info" title="Projected if the offer is accepted — not confirmed">
      Simulated
    </TagBadge>
  );
}

function Saving({ c }: { c: CostComparison }) {
  const money = formatMoney(Math.abs(c.saving), c.cost.currency);
  return (
    <span
      className={cn(
        "font-semibold tabular-nums",
        c.saving > 0 ? "text-success" : c.saving < 0 ? "text-warning" : "text-muted-foreground",
      )}
    >
      {c.saving > 0 ? `saves ${money}` : c.saving < 0 ? `costs ${money} more` : "same cost"}
    </span>
  );
}

function Headline({ cost, label }: { cost: CostEstimate; label: string }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tabular-nums">
        {formatMoney(cost.amount, cost.currency)}
      </span>
      <BasisBadge basis={cost.basis} />
      <span className="text-xs text-muted-foreground tabular-nums">
        {formatDuration(cost.paid_minutes)} paid
        {cost.cost_per_covered_hour !== null
          ? ` · ${formatMoney(cost.cost_per_covered_hour, cost.currency)} per physician-hour of gap covered`
          : ""}
      </span>
    </div>
  );
}

/**
 * Estimated staffing cost of the recommendation and what the same cost model says about
 * the alternatives. Every figure the backend marks as simulated is labelled so; a confirmed
 * cost appears only once a shift has been completed.
 */
export function CostSummary({
  cost,
  confirmed,
  confirmedSavings = [],
  label = "Estimated cost",
}: {
  cost: PlanCost | null;
  confirmed?: CostEstimate | null;
  confirmedSavings?: CostComparison[];
  label?: string;
}) {
  if (!cost && !confirmed) return null;
  return (
    <div className="space-y-2 rounded-lg border bg-card p-3">
      <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        <BadgeDollarSign className="size-3.5" aria-hidden />
        Cost and savings
      </p>
      {cost ? <Headline cost={cost.recommended} label={label} /> : null}
      {cost?.comparisons.length ? (
        <ul className="space-y-1 text-xs">
          {cost.comparisons.map((c) => (
            <li key={c.label} className="flex flex-wrap items-baseline gap-x-1.5">
              <span>vs {c.label}</span>
              <span className="text-muted-foreground">
                (
                {c.physician_names.some((n) => !c.label.includes(n))
                  ? `${c.physician_names.join(", ")}, `
                  : ""}
                {formatMoney(c.cost.amount, c.cost.currency)})
              </span>
              <span aria-hidden>→</span>
              <Saving c={c} />
              <BasisBadge basis={c.basis} />
            </li>
          ))}
        </ul>
      ) : null}
      {confirmed ? (
        <div className="space-y-1 border-t pt-2">
          <Headline cost={confirmed} label="Confirmed cost" />
          {confirmedSavings.length ? (
            <ul className="space-y-0.5 text-xs">
              {confirmedSavings.map((c) => (
                <li key={c.label}>
                  {c.explanation} <BasisBadge basis={c.basis} />
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : cost ? (
        <p className="text-xs text-muted-foreground">{cost.label}</p>
      ) : null}
      {cost ? (
        <Disclosure summary="How cost is estimated">
          <Bullets
            items={[...cost.assumptions, ...cost.comparisons.map((c) => c.explanation)]}
            className="text-xs"
          />
        </Disclosure>
      ) : null}
    </div>
  );
}
