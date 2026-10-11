import Link from "next/link";

import { cn } from "@/lib/utils";

import { PulseGlyph } from "./ecg";

export function Wordmark({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <Link
      href="/"
      aria-label="Sevaro Pulse — role overview"
      className={cn("inline-flex shrink-0 items-center gap-2 rounded-[9px]", className)}
    >
      <PulseGlyph className={compact ? "size-5" : undefined} />
      <span
        className={cn(
          "font-serif leading-none tracking-[-0.01em] whitespace-nowrap text-foreground",
          compact ? "text-[22px]" : "text-[26px]",
        )}
      >
        Sevaro Pulse
      </span>
    </Link>
  );
}
