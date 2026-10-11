"use client";

import { Loader2, RotateCcw } from "lucide-react";

import { Feedback } from "@/components/workflow/feedback";
import { useAction } from "@/components/workflow/use-action";
import { simulationApi } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

import { useSystemStatus } from "./system-status-provider";

/** +1 stays: the official scenario's demo needs 18:31, one minute past a five-minute step. */
const STEPS = [1, 5, 15, 60];

/**
 * Demo clock controls. ``monitor`` is the segmented control inside the dark monitor card;
 * ``toolbar`` is the light version shown on narrow screens, where the sidebar is hidden.
 */
export function TimeControls({
  variant = "monitor",
  className,
}: {
  variant?: "monitor" | "toolbar";
  className?: string;
}) {
  const { config, connection } = useSystemStatus();
  const { pending, feedback, run } = useAction();
  const disabled = connection !== "online" || !config?.dataset_loaded || pending !== null;
  const monitor = variant === "monitor";

  const button = cn(
    "inline-flex items-center justify-center gap-1 font-mono text-xs tabular-nums disabled:cursor-not-allowed disabled:opacity-45",
    monitor
      ? "h-7 rounded-[7px] text-clock-fg/85 enabled:hover:bg-clock-fg/14 enabled:hover:text-clock-fg"
      : "h-8 rounded-[7px] px-2.5 text-foreground-2 enabled:hover:bg-hover enabled:hover:text-foreground",
  );

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div
        role="group"
        aria-label="Advance simulation time"
        className={cn(
          "grid grid-cols-5 gap-0.5 rounded-[9px] p-0.5",
          monitor ? "bg-clock-fg/8" : "border border-border bg-card-subtle",
        )}
      >
        {STEPS.map((minutes) => (
          <button
            key={minutes}
            type="button"
            className={button}
            disabled={disabled}
            aria-label={`Advance ${minutes} minute${minutes === 1 ? "" : "s"}`}
            title={`Advance ${minutes} min`}
            onClick={() =>
              run(`adv${minutes}`, () => simulationApi.advance(minutes).then(() => undefined))
            }
          >
            {pending === `adv${minutes}` ? (
              <Loader2 className="size-3 animate-spin" aria-hidden />
            ) : (
              `+${minutes}`
            )}
          </button>
        ))}
        <button
          type="button"
          className={button}
          disabled={disabled}
          aria-label="Reset to the dataset reference time"
          title="Reset to the dataset reference time"
          onClick={() => run("reset", () => simulationApi.reset().then(() => undefined))}
        >
          {pending === "reset" ? (
            <Loader2 className="size-3 animate-spin" aria-hidden />
          ) : monitor ? (
            "reset"
          ) : (
            <RotateCcw className="size-3.5" aria-hidden />
          )}
        </button>
      </div>
      {feedback?.tone === "error" ? (
        monitor ? (
          <p role="alert" className="text-label text-[oklch(0.82_0.1_25)]">
            {feedback.message}
          </p>
        ) : (
          <Feedback feedback={feedback} />
        )
      ) : null}
    </div>
  );
}
