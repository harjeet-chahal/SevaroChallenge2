import { cn } from "@/lib/utils";

/** One quiet heartbeat every few hundred units: P wave, QRS spike, T wave. */
const LIFELINE_PATH =
  "M0 11 H300 l8 -2 l8 2 h10 l4 3 l6 -12 l6 15 l5 -6 h14 q12 -5 24 0 H760 l8 -2 l8 2 h10 l4 3 l6 -12 l6 15 l5 -6 h14 q12 -5 24 0 H1200";

const TRACE_PATH =
  "M0 70 H40 l6 -4 l6 4 h8 l4 6 l6 -40 l7 52 l5 -18 h12 q10 -10 20 0 H140 l6 -4 l6 4 h8 l4 6 l6 -40 l7 52 l5 -18 h12 q10 -10 20 0 H260";

/**
 * The full-width ECG baseline under the top bar. It doubles as the bar's bottom border;
 * a short primary dash sweeps along it. Decorative only.
 */
export function Lifeline({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 1200 18"
      preserveAspectRatio="none"
      className={cn("block h-[18px] w-full", className)}
    >
      <path
        d={LIFELINE_PATH}
        pathLength={1200}
        fill="none"
        stroke="var(--border)"
        strokeWidth={1.25}
        vectorEffect="non-scaling-stroke"
      />
      <path
        d={LIFELINE_PATH}
        pathLength={1200}
        fill="none"
        stroke="var(--primary)"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeDasharray="140 1060"
        vectorEffect="non-scaling-stroke"
        className="animate-ng-trace"
      />
    </svg>
  );
}

/** The faint trace behind the dark monitor card, with a short dash sweeping over it. */
export function MonitorTrace({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 260 120"
      preserveAspectRatio="none"
      className={cn("pointer-events-none absolute inset-0 size-full", className)}
    >
      <path
        d={TRACE_PATH}
        pathLength={1200}
        fill="none"
        stroke="var(--clock-line)"
        strokeWidth={1.25}
        vectorEffect="non-scaling-stroke"
      />
      <path
        d={TRACE_PATH}
        pathLength={1200}
        fill="none"
        stroke="var(--primary)"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeDasharray="120 1080"
        vectorEffect="non-scaling-stroke"
        className="animate-[ng-trace_4s_linear_infinite] opacity-70"
      />
    </svg>
  );
}

/** The wordmark glyph: a stroked pulse. */
export function PulseGlyph({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--primary)"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("size-[22px] shrink-0", className)}
    >
      <path d="M2 12h4l2.5-6 4 13 3-9 1.5 2H22" />
    </svg>
  );
}
