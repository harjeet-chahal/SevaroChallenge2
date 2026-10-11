import { cn } from "@/lib/utils";

export type MetricTone = "critical" | "warning" | "success" | "neutral";

const TONE_HINT: Record<MetricTone, string> = {
  critical: "font-medium text-critical-ink",
  warning: "font-medium text-warning-ink",
  success: "text-success-ink",
  neutral: "text-muted-foreground",
};

const TONE_ICON: Record<MetricTone, string> = {
  critical: "text-critical-ink",
  warning: "text-warning-ink",
  success: "text-success-ink",
  neutral: "text-faint-foreground",
};

/**
 * A summary figure. ``value`` is null whenever the backend has not supplied a real
 * number — in which case a dash is shown instead of an invented metric. ``tone`` is set
 * only when the figure needs attention: the hint line then says why, in its ink colour.
 */
export function MetricCard({
  label,
  value,
  suffix,
  hint,
  icon: Icon,
  tone = "neutral",
  onClick,
  actionLabel,
  className,
}: {
  label: string;
  value: number | string | null;
  /** Small trailing context for the value, e.g. "/ 6". */
  suffix?: string;
  hint?: string;
  icon?: React.ComponentType<{ className?: string }>;
  tone?: MetricTone;
  /** Makes the tile a shortcut to the detail behind the number. */
  onClick?: () => void;
  /** Accessible description of what clicking does, e.g. "Show critical alerts". */
  actionLabel?: string;
  className?: string;
}) {
  const body = (
    <>
      <span className="flex items-start justify-between gap-2">
        <span className="text-caption text-muted-foreground">{label}</span>
        {Icon ? <Icon className={cn("size-4 shrink-0", TONE_ICON[tone])} aria-hidden /> : null}
      </span>
      <span
        className={cn(
          "flex items-baseline gap-1.5 font-mono text-[30px] leading-none font-semibold tracking-[-0.02em] tabular-nums",
          value === null ? "text-faint-foreground" : "text-foreground",
        )}
        aria-label={value === null ? `${label}: no data` : undefined}
      >
        {value ?? "—"}
        {suffix && value !== null ? (
          <span className="font-sans text-sm font-medium tracking-normal text-muted-foreground">
            {suffix}
          </span>
        ) : null}
      </span>
      {hint ? (
        <span className={cn("line-clamp-2 text-caption", TONE_HINT[tone])} title={hint}>
          {hint}
        </span>
      ) : null}
    </>
  );

  const base = cn(
    "flex min-w-0 flex-col gap-1.5 rounded-lg border border-border bg-card-subtle p-4 text-left",
    className,
  );

  if (!onClick) return <div className={base}>{body}</div>;
  return (
    <button
      type="button"
      onClick={onClick}
      title={actionLabel}
      className={cn(base, "outline-none hover:border-border-strong hover:bg-card focus-visible:ring-3 focus-visible:ring-ring/50")}
    >
      {body}
      {actionLabel ? <span className="sr-only">. {actionLabel}</span> : null}
    </button>
  );
}

/** Auto-fit KPI grid: as many 170px+ columns as fit. */
export const METRIC_GRID = "grid grid-cols-[repeat(auto-fit,minmax(min(100%,150px),1fr))] gap-3";
