import Link from "next/link";

import { cn } from "@/lib/utils";

const COMPLEX = "l8 -2 6 4 6 -12 7 20 6 -14 5 4";
const LIFELINE = `M0 14 H420 ${COMPLEX} H760 ${COMPLEX} H1200`;
const CLOCK_LINE = "M0 22 H70 l5 -1 4 3 4 -16 5 26 4 -16 4 4 H160 l5 -1 4 3 4 -16 5 26 4 -16 4 4 H240";

export function Wordmark({ className }: { className?: string }) {
  return (
    <Link
      href="/"
      aria-label="Neurogrid home"
      className={cn("flex items-center gap-2.5 rounded-md text-foreground", className)}
    >
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden className="shrink-0">
        <path
          d="M2 12h4l2.5-6 4 13 3-9 1.5 2H22"
          stroke="var(--primary)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="font-serif text-[26px] leading-none tracking-[-0.01em]">Neurogrid</span>
    </Link>
  );
}

/** Full-width ECG baseline under the top bar, with a slow sweeping trace. */
export function Lifeline() {
  return (
    <svg aria-hidden viewBox="0 0 1200 24" preserveAspectRatio="none" className="block h-[18px] w-full">
      <path d={LIFELINE} fill="none" stroke="var(--border)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <path
        d={LIFELINE}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="1.5"
        strokeDasharray="140 1060"
        vectorEffect="non-scaling-stroke"
        className="animate-ng-trace"
      />
    </svg>
  );
}

/** Faint monitor trace drawn behind the simulation clock. */
export function ClockTrace() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 240 40"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-x-0 top-11 h-10 w-full"
    >
      <path d={CLOCK_LINE} fill="none" stroke="var(--clock-line)" strokeWidth="1" />
      <path
        d={CLOCK_LINE}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="1.5"
        strokeDasharray="60 400"
        className="animate-ng-trace [animation-duration:4s]"
      />
    </svg>
  );
}
