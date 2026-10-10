import { cn } from "@/lib/utils";

/**
 * A summary figure. ``value`` is null whenever the backend has not supplied a real
 * number — in which case a dash is shown instead of an invented metric.
 */
export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  className,
}: {
  label: string;
  value: number | string | null;
  hint?: string;
  icon?: React.ComponentType<{ className?: string }>;
  className?: string;
}) {
  return (
    <div className={cn("rounded-xl border bg-card p-4 shadow-xs", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-muted-foreground">{label}</p>
        {Icon ? <Icon className="size-4 text-muted-foreground" aria-hidden /> : null}
      </div>
      <p
        className={cn(
          "mt-2 text-2xl font-semibold tabular-nums",
          value === null && "text-muted-foreground/60",
        )}
        aria-label={value === null ? `${label}: no data` : undefined}
      >
        {value ?? "—"}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
