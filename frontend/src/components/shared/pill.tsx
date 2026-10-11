import { cn } from "@/lib/utils";

export type PillTone = "critical" | "serious" | "warning" | "success" | "info" | "primary" | "muted";

/** Text on tinted fills always uses the *-ink shade (>= 4.5:1 on its *-soft fill). */
export const PILL_TONES: Record<PillTone, string> = {
  critical: "border-critical-border bg-critical-soft text-critical-ink",
  serious: "border-serious-border bg-serious-soft text-serious-ink",
  warning: "border-warning-border bg-warning-soft text-warning-ink",
  success: "border-success-border bg-success-soft text-success-ink",
  info: "border-info-border bg-info-soft text-info-ink",
  primary: "border-primary-border bg-primary-soft text-primary-ink",
  muted: "border-border-strong bg-raised text-foreground-2",
};

/**
 * The one status badge. Severity pills carry an icon; availability-style pills carry a dot.
 * Either way the state is in words, never colour alone.
 */
export function Pill({
  tone = "muted",
  icon: Icon,
  dot = false,
  title,
  className,
  children,
}: {
  tone?: PillTone;
  icon?: React.ComponentType<{ className?: string }>;
  dot?: boolean;
  title?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-label font-medium whitespace-nowrap",
        PILL_TONES[tone],
        className,
      )}
    >
      {dot ? <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-current" /> : null}
      {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden /> : null}
      {children}
    </span>
  );
}
