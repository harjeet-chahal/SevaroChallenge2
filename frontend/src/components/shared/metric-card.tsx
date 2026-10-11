import { cn } from "@/lib/utils";

export type MetricTone = "critical" | "warning" | "success" | "neutral";

const TONE_TEXT: Record<MetricTone, string> = {
  critical: "text-critical",
  warning: "text-warning",
  success: "text-success",
  neutral: "text-foreground",
};

const TONE_RAIL: Record<MetricTone, string> = {
  critical: "bg-critical",
  warning: "bg-warning",
  success: "bg-success",
  neutral: "bg-transparent",
};

/**
 * A summary figure. ``value`` is null whenever the backend has not supplied a real
 * number — in which case a dash is shown instead of an invented metric. ``tone`` is set
 * only when the figure needs attention, so colour stays meaningful.
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
      <span
        aria-hidden
        className={cn("absolute inset-y-3 left-0 w-1 rounded-r-full", TONE_RAIL[tone])}
      />
      <span className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        {Icon ? <Icon className="size-4 text-muted-foreground/70" aria-hidden /> : null}
      </span>
      <span
        className={cn(
          "mt-1 block text-2xl leading-tight font-semibold tabular-nums",
          value === null ? "text-muted-foreground/60" : TONE_TEXT[tone],
        )}
        aria-label={value === null ? `${label}: no data` : undefined}
      >
        {value ?? "—"}
        {suffix && value !== null ? (
          <span className="ml-1 text-sm font-medium text-muted-foreground">{suffix}</span>
        ) : null}
      </span>
      {hint ? (
        <span className="mt-0.5 line-clamp-2 text-xs text-muted-foreground" title={hint}>
          {hint}
        </span>
      ) : null}
    </>
  );

  const base = cn(
    "relative block min-w-0 overflow-hidden rounded-xl border bg-card px-4 py-3 text-left shadow-xs",
    className,
  );

  if (!onClick) return <div className={base}>{body}</div>;
  return (
    <button
      type="button"
      onClick={onClick}
      title={actionLabel}
      className={cn(
        base,
        "transition-colors outline-none hover:border-primary/40 hover:bg-accent/30 focus-visible:ring-3 focus-visible:ring-ring/50",
      )}
    >
      {body}
      {actionLabel ? <span className="sr-only">. {actionLabel}</span> : null}
    </button>
  );
}
