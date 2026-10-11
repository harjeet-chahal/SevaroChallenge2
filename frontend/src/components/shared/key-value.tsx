import { cn } from "@/lib/utils";

/** A small inset tile: muted label over a mono value. Null shows a dash, never a guess. */
export function KeyValue({
  label,
  value,
  hint,
  tone,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode | null;
  hint?: React.ReactNode;
  tone?: "critical" | "warning" | "success" | "primary";
  className?: string;
}) {
  return (
    <div className={cn("min-w-0 rounded-[10px] bg-inset px-3 py-2.5", className)}>
      <dt className="truncate text-xs text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "truncate font-mono text-lg font-semibold tabular-nums",
          value === null && "text-faint-foreground",
          tone === "critical" && "text-critical-ink",
          tone === "warning" && "text-warning-ink",
          tone === "success" && "text-success-ink",
          tone === "primary" && "text-primary-ink",
        )}
      >
        {value ?? "—"}
      </dd>
      {hint ? <dd className="mt-0.5 text-micro text-muted-foreground uppercase">{hint}</dd> : null}
    </div>
  );
}
