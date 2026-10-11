"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * The scripted rescue story replayed on the Home page. It illustrates the loop on the
 * official scenario; it is not live data (the live figures are in the operations views).
 */
export const STAGES = [
  {
    name: "Detect",
    sentence: "Northfield is projected to fall below its required coverage at 20:00 EDT.",
    status: "Projected coverage gap",
  },
  {
    name: "Diagnose",
    sentence:
      "Several interacting causes: availability uncertainty, a credentialing bottleneck and a shift collision — as the Coverage Genome reports for Northfield in the official scenario.",
    status: "Multi-factor root cause",
  },
  {
    name: "Forecast",
    sentence: "Short at 20:00 EDT. The last safe moment to start a rescue is 19:30.",
    status: "Start rescue by 19:30",
  },
  {
    name: "Decide",
    sentence: "Off-shift physicians are checked against every rule. Only one can cover Northfield.",
    status: "Candidates checked",
  },
  {
    name: "Simulate",
    sentence:
      "Every option is replayed on a copy of the network. Once the gap is inside the staffing action window, a split shift with Dr. Okafor ranks first.",
    status: "Options simulated",
  },
  { name: "Approve", sentence: "A clinical lead approves. Nothing moves without this step.", status: "Awaiting clinical lead" },
  {
    name: "Act",
    sentence: "The offer is accepted — accepted is not yet online. Dr. Okafor then signs in before the shortfall.",
    status: "Rescue activating",
  },
  {
    name: "Verify",
    sentence: "In the story, the gap is re-measured at 0 phys-min and the recovery is recorded.",
    status: "Recovered · gap 0",
  },
] as const;

/** Stage 8 is the stable rhythm between replays. */
export const IDLE = 8;
export const STAGE_MS = 2600;
const IDLE_MS = 5200;

function subscribeReduced(onChange: () => void) {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReduced,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}

export interface RescueLoop {
  stage: number;
  playing: boolean;
  reduced: boolean;
  /** performance.now() when the current stage began (read by the canvases each frame). */
  stageStart: React.RefObject<number>;
  jump: (stage: number) => void;
  inject: () => void;
  togglePlay: () => void;
}

/** Shared replay state for the monitor and the network canvases. */
export function useRescueLoop(): RescueLoop {
  const reduced = usePrefersReducedMotion();
  const [stage, setStage] = useState(IDLE);
  const [playing, setPlaying] = useState(true);
  const stageStart = useRef(0);

  const jump = useCallback((s: number) => {
    stageStart.current = performance.now();
    setStage(s);
  }, []);

  useEffect(() => {
    stageStart.current = performance.now();
  }, []);

  useEffect(() => {
    if (!playing || reduced) return;
    const id = setTimeout(() => jump(stage === IDLE ? 0 : stage + 1), stage === IDLE ? IDLE_MS : STAGE_MS);
    return () => clearTimeout(id);
  }, [stage, playing, reduced, jump]);

  const inject = useCallback(() => {
    if (stage === 7 || stage === IDLE) {
      jump(0);
      setPlaying(true);
    }
  }, [stage, jump]);

  const togglePlay = useCallback(() => {
    stageStart.current = performance.now();
    setPlaying((p) => !p);
  }, []);

  return { stage, playing: playing && !reduced, reduced, stageStart, jump, inject, togglePlay };
}
