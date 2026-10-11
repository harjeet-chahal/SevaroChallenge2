"use client";

import { FlaskConical, Pause, Play } from "lucide-react";
import Link from "next/link";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { formatHm, zoneAbbr } from "@/lib/format";
import { cn } from "@/lib/utils";

import { NetworkReplay } from "./network-replay";
import { STAGES, useRescueLoop } from "./rescue-loop";
import { RhythmMonitor } from "./rhythm-monitor";
import { RoleCards } from "./role-cards";

const ET = "America/New_York";

/** Home: the network as a patient on a monitor, the same rescue as a graph, then the roles. */
export function HomeExperience() {
  const loop = useRescueLoop();
  const { config } = useSystemStatus();
  const t = config?.simulation_time;
  const simLabel = t ? `${formatHm(t, ET)} ${zoneAbbr(t, ET)}` : "clock not set";

  return (
    <div className="flex flex-col gap-[72px] pt-1 min-[1200px]:pt-3">
      <div className="flex flex-col gap-3">
        <div
          role="note"
          aria-label="Illustrative demo — not live operational data"
          className="flex flex-wrap items-start gap-x-3 gap-y-1.5 rounded-xl border border-warning-border bg-warning-soft px-4 py-3"
        >
          <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-warning-ink">
            <FlaskConical className="size-4" aria-hidden />
            Illustrative demo — not live operational data
          </span>
          <span className="text-caption leading-snug text-foreground-2">
            A scripted replay of one rescue on the official scenario. Its coverage numbers, the offer acceptance and the
            “recovered · verified” status belong to the story, not to the current state. The replay runs on its own
            timeline; the live simulation clock stays at <span className="font-mono">{simLabel}</span>. Live figures are
            in the <Link href="/coordinator" className="text-primary-ink underline-offset-2 hover:underline">Command Center</Link>.
          </span>
        </div>
        <RhythmMonitor loop={loop} />
      </div>

      <section className="grid grid-cols-1 items-center gap-7 min-[1200px]:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] min-[1200px]:gap-12">
        <NetworkReplay loop={loop} />
        <div className="flex min-w-0 flex-col gap-[22px]">
          <h2 className="font-serif text-[clamp(40px,4vw,56px)] leading-none font-normal tracking-[-0.02em]">
            Watch a human-approved rescue <span className="text-primary italic">restore coverage.</span>
          </h2>
          <p className="max-w-[480px] text-[15.5px] leading-relaxed text-foreground-2">
            The same scripted disruption, seen as a graph: nothing reaches a physician until a clinical lead approves
            the rescue. Hover nodes to trace credentials; click a step to jump the replay.
          </p>
          <ol className="flex flex-col gap-0.5">
            {STAGES.map((st, i) => {
              const on = i === loop.stage;
              return (
                <li key={st.name}>
                  <button
                    type="button"
                    aria-current={on ? "step" : undefined}
                    onClick={() => loop.jump(i)}
                    className={cn(
                      "flex w-full items-start gap-3.5 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-card",
                      on && "bg-card ring-1 ring-border-subtle ring-inset",
                    )}
                  >
                    <span className={cn("pt-0.5 font-mono text-xs font-semibold", on ? "text-primary" : "text-muted-foreground")}>
                      0{i + 1}
                    </span>
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className={cn("text-[15px]", on ? "font-semibold text-foreground" : "text-foreground-2")}>
                        {st.name}
                      </span>
                      {on ? (
                        <span className="animate-[ng-rise_.4s_ease-out] text-[13.5px] leading-snug text-foreground-2">
                          {st.sentence}
                        </span>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
          {!loop.reduced ? (
            <button
              type="button"
              onClick={loop.togglePlay}
              className="flex h-11 items-center gap-2 self-start rounded-full border px-[18px] text-sm transition-colors hover:border-primary"
            >
              {loop.playing ? <Pause className="size-4" aria-hidden /> : <Play className="size-4" aria-hidden />}
              {loop.playing ? "Pause replay" : "Play replay"}
            </button>
          ) : null}
        </div>
      </section>

      <RoleCards />
    </div>
  );
}
