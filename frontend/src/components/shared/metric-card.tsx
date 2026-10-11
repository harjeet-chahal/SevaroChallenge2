import { cn } from "@/lib/utils";

/**
 * A summary figure. ``value`` is null whenever the backend has not supplied a real
 * number — in which case a dash is shown instead of an invented metric. ``risk``
 * marks the sub-line as describing a risk (critical ink), never colour alone.
 */
export function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  risk,
  className,
}: {
  label: string;
  value: number | string | null;
  hint?: string;
  icon?: React.ComponentType<{ className?: string }>;
  risk?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1.5 rounded-lg border bg-card-subtle p-4", className)}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-caption text-muted-foreground">{label}</p>
        {Icon ? <Icon className="size-4 text-faint-foreground" aria-hidden /> : null}
      </div>
      <p
        className={cn(
          "font-mono text-[30px] leading-none font-semibold whitespace-nowrap tabular-nums",
          value === null && "text-faint-foreground",
        )}
        aria-label={value === null ? `${label}: no data` : undefined}
      >
        {value ?? "—"}
      </p>
      {hint ? (
        <p className={cn("text-caption", risk ? "font-medium text-critical-ink" : "text-muted-foreground")}>{hint}</p>
      ) : null}
    </div>
  );
}
