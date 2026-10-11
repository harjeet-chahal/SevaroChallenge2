"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

const STEPS = [
  {
    title: "Detect",
    who: "Coordinator",
    text: "Events replay into live state at the simulation clock. Rules raise ranked alerts for stage-time breaches, unrouted consults, demand spikes and coverage gaps.",
  },
  {
    title: "Decide",
    who: "Coordinator",
    text: "The optimizers rank reassignments and split shifts against every eligibility rule. The coordinator picks one and proposes it, checked against the current data.",
  },
  {
    title: "Propose",
    who: "Coordinator",
    text: "A proposal records the alert, the evidence and the ranked physicians to ask. Nobody is contacted yet.",
  },
  {
    title: "Approve",
    who: "Clinical lead",
    text: "A clinical lead approves or rejects. Approval re-validates eligibility, offer limits and the remaining need before any offer is sent.",
  },
  {
    title: "Accept",
    who: "Off-shift physician",
    text: "The physician sees hospitals, hours and a reply deadline, never patient data, and accepts or declines from a phone. Coverage, alerts and routing are then recalculated and every step is audited.",
  },
];

/** The rescue loop, one step at a time; the active step reveals its sentence. */
export function LoopStepper() {
  const [active, setActive] = useState(0);
  return (
    <ol className="flex flex-col gap-1" aria-label="The rescue loop">
      {STEPS.map((step, i) => {
        const on = i === active;
        return (
          <li key={step.title}>
            <button
              type="button"
              aria-current={on ? "step" : undefined}
              aria-expanded={on}
              onClick={() => setActive(i)}
              className={cn(
                "flex w-full items-start gap-4 rounded-xl px-4 py-3 text-left outline-none hover:bg-card focus-visible:ring-3 focus-visible:ring-ring/50",
                on && "bg-card ring-1 ring-border-subtle ring-inset",
              )}
            >
              <span
                className={cn(
                  "pt-0.5 font-mono text-xs tabular-nums",
                  on ? "text-primary" : "text-muted-foreground",
                )}
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span
                    className={cn(
                      "text-[17px]",
                      on ? "font-semibold text-foreground" : "text-foreground-2",
                    )}
                  >
                    {step.title}
                  </span>
                  <span className="text-caption text-muted-foreground">{step.who}</span>
                </span>
                {on ? (
                  <span className="mt-1 block animate-ng-rise text-body text-foreground-2">
                    {step.text}
                  </span>
                ) : null}
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
