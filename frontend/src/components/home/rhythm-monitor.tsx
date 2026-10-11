"use client";

import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

import { IDLE, STAGES, STAGE_MS, type RescueLoop } from "./rescue-loop";

/* The monitor is always dark, so its palette is fixed rather than themed. */
const MINT = "oklch(0.86 0.13 168)";
const RED = "oklch(0.72 0.19 25)";
const AMBER = "oklch(0.86 0.14 82)";
const FG = "oklch(0.97 0.008 170)";
const TRACE = { m: MINT, r: RED, a: AMBER } as const;
type TraceKey = keyof typeof TRACE;

const g = (x: number, m: number, w: number) => Math.exp(-((x - m) * (x - m)) / (2 * w * w));
/** One PQRST complex over the beat phase p in [0, 1). */
const ecg = (p: number) =>
  0.12 * g(p, 0.18, 0.025) - 0.18 * g(p, 0.36, 0.008) + 1 * g(p, 0.39, 0.011) - 0.3 * g(p, 0.42, 0.01) + 0.28 * g(p, 0.62, 0.045);

type Mode = "ok" | "onset" | "flat" | "shock";
const modeOf = (s: number): Mode => (s === IDLE || s === 7 ? "ok" : s === 0 ? "onset" : s === 6 ? "shock" : "flat");

type Tone = "ok" | "rec" | "act" | "alarm";
const toneOf = (s: number): Tone => (s === IDLE ? "ok" : s === 7 ? "rec" : s === 6 ? "act" : "alarm");
const TONE_COLOR: Record<Tone, string> = { ok: MINT, rec: MINT, act: AMBER, alarm: RED };
const STATUS: Record<Tone, string> = {
  ok: "Rhythm stable",
  rec: "Recovered · verified",
  act: "Rescue in progress",
  alarm: "ALARM · Northfield coverage",
};

interface Vital {
  label: string;
  value: string;
  sub: string;
  color: string;
  blink?: boolean;
}

function vitals(s: number): Vital[] {
  const healed = s === IDLE || s === 7;
  const stateColor = healed ? MINT : s === 6 ? AMBER : RED;
  return [
    {
      label: "COVERAGE · NORTHFIELD",
      value: healed ? "2/2" : "1/2",
      sub: s === IDLE ? "required / available" : s === 7 ? "restored" : "below required",
      color: stateColor,
      blink: s <= 1,
    },
    {
      label: "GAP · PHYS-MIN",
      value: healed ? "0" : s === 6 ? "60" : "120",
      sub: s === 7 ? "vs 120 without rescue" : "projected next 4 h",
      color: stateColor,
    },
    {
      label: "LAST SAFE MOMENT",
      value: s === IDLE ? "—" : s <= 1 ? "…" : s >= 6 ? "met" : "19:30",
      sub: s === IDLE ? "no shortfall" : s <= 1 ? "computing" : s >= 6 ? "rescue started in time" : "start rescue by · EDT",
      color: s >= 2 && s <= 5 ? AMBER : FG,
    },
    {
      label: "RESCUE",
      value: ["—", "—", "—", "checked", "ranked", "approval", "Okafor", "verified", "—"][s],
      sub: ["", "", "", "every eligibility rule", "split shift ranks 1st", "clinical lead", "signing in", "recorded", "standing by"][s],
      color: s >= 6 && s < IDLE ? MINT : FG,
      blink: s === 5,
    },
  ];
}

const HEADLINE = ["Detect the disruption.", "Find the last safe opportunity.", "Engineer the rescue.", "Verify the recovery."];
const GROUPS = [[0, 1], [2, 3], [4, 5, 6], [7]];
const HEADLINE_COLOR = [RED, AMBER, FG, MINT];

function tickColor(i: number, s: number) {
  if (s === IDLE || i > s) return "transparent";
  if (s === 7 || i === 0) return MINT;
  if (i === 6) return AMBER;
  return RED;
}

export function RhythmMonitor({ loop, simLabel }: { loop: RescueLoop; simLabel: string }) {
  const { stage, playing, reduced, stageStart, jump, inject } = loop;
  const canvas = useRef<HTMLCanvasElement>(null);
  const chip = useRef<HTMLSpanElement>(null);
  const pointer = useRef<{ x: number | null; y: number | null }>({ x: null, y: null });
  const stageRef = useRef(stage);
  useEffect(() => {
    stageRef.current = stage;
  }, [stage]);

  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let buf = new Float32Array(0);
    let keys: TraceKey[] = [];
    let sx = 0;
    let beat = 0;
    let last = 0;
    let staticFor = -1;

    const fillStatic = (W: number, s: number, base: number, amp: number) => {
      const mode = modeOf(s);
      for (let x = 0; x < W; x++) {
        const p = x / Math.max(220, W / 5.5);
        let v = 0;
        let k: TraceKey = "m";
        if (mode === "ok") v = ecg((p * 1.2) % 1);
        else if (mode === "shock") {
          v = ecg((p * 1.3) % 1);
          k = "a";
        } else {
          v = mode === "onset" ? ecg((p * 1.6) % 1) * 0.5 : Math.sin(x / 9) * 0.015;
          k = "r";
        }
        buf[x] = base - v * amp;
        keys[x] = k;
      }
    };

    const draw = (now: number) => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const W = Math.max(1, Math.floor(cv.clientWidth));
      const H = cv.clientHeight;
      if (cv.width !== W * dpr || cv.height !== H * dpr || buf.length !== W) {
        cv.width = W * dpr;
        cv.height = H * dpr;
        buf = new Float32Array(W).fill(NaN);
        keys = new Array<TraceKey>(W).fill("m");
        sx = 0;
        beat = 0;
        staticFor = -1;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const s = stageRef.current;
      const base = H * 0.36;
      const yPtr = pointer.current.y;
      const amp = H * 0.2 * (yPtr !== null ? 0.6 + (1 - yPtr) * 0.9 : 1);
      let head = -1;

      if (reduced) {
        if (staticFor !== s) {
          fillStatic(W, s, base, H * 0.2);
          staticFor = s;
        }
      } else {
        const dt = Math.min(50, now - (last || now));
        last = now;
        const sp = Math.max(220, W / 5.5);
        const t = (now - stageStart.current) / STAGE_MS;
        const mode = modeOf(s);
        const nx = sx + (sp * dt) / 1000;
        for (let x = Math.floor(sx); x < Math.floor(nx); x++) {
          const xi = ((x % W) + W) % W;
          let v = 0;
          let k: TraceKey = "m";
          if (mode === "ok") {
            beat += (s === 7 ? 1.45 : 1.2) / sp;
            v = ecg(beat % 1);
          } else if (mode === "onset") {
            beat += (1.2 + Math.random() * 1.6) / sp;
            v = ecg(beat % 1) * (1 - Math.min(1, t) * 0.8) + (Math.random() - 0.5) * 0.08;
            k = "r";
          } else if (mode === "flat") {
            beat += 1 / sp;
            v = (Math.random() - 0.5) * 0.035 + Math.sin(beat * 9) * 0.015;
            k = "r";
          } else if (t < 0.1) {
            v = (Math.floor(x / 3) % 2 ? 1.5 : -1.1) * Math.sin((t / 0.1) * Math.PI);
            k = "a";
          } else {
            beat += 1.3 / sp;
            v = ecg(beat % 1) * Math.min(1, (t - 0.1) * 2.5);
            k = t < 0.5 ? "a" : "m";
          }
          buf[xi] = base - v * amp;
          keys[xi] = k;
        }
        sx = nx >= W ? nx - W : nx;
        head = Math.floor(sx) % W;
        for (let k = 1; k <= 46; k++) buf[(head + k) % W] = NaN;
      }

      ctx.lineWidth = 1;
      for (let x = 0; x < W; x += 24) {
        ctx.strokeStyle = x % 120 === 0 ? "oklch(0.86 0.13 168 / .09)" : "oklch(0.86 0.13 168 / .04)";
        ctx.beginPath();
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, H);
        ctx.stroke();
      }
      for (let y = 0; y < H; y += 24) {
        ctx.strokeStyle = y % 120 === 0 ? "oklch(0.86 0.13 168 / .09)" : "oklch(0.86 0.13 168 / .04)";
        ctx.beginPath();
        ctx.moveTo(0, y + 0.5);
        ctx.lineTo(W, y + 0.5);
        ctx.stroke();
      }

      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      for (const pass of [0, 1]) {
        ctx.lineWidth = pass === 0 ? 7 : 2.2;
        ctx.globalAlpha = pass === 0 ? 0.13 : 1;
        ctx.shadowBlur = pass === 0 || reduced ? 0 : 14;
        let cur: TraceKey | null = null;
        ctx.beginPath();
        for (let x = 0; x < W; x++) {
          const y = buf[x];
          const k = keys[x];
          if (Number.isNaN(y)) {
            if (cur) {
              ctx.stroke();
              ctx.beginPath();
              cur = null;
            }
            continue;
          }
          if (k !== cur) {
            if (cur) {
              ctx.lineTo(x, y);
              ctx.stroke();
              ctx.beginPath();
            }
            ctx.strokeStyle = TRACE[k];
            ctx.shadowColor = TRACE[k];
            cur = k;
            ctx.moveTo(x, y);
          } else ctx.lineTo(x, y);
        }
        if (cur) ctx.stroke();
      }
      ctx.shadowBlur = 0;
      ctx.globalAlpha = 1;

      if (head >= 0) {
        const hi = (head - 1 + W) % W;
        const hy = buf[hi];
        if (!Number.isNaN(hy)) {
          const hc = TRACE[keys[hi]];
          ctx.beginPath();
          ctx.arc(head, hy, 4.5, 0, Math.PI * 2);
          ctx.fillStyle = hc;
          ctx.shadowColor = hc;
          ctx.shadowBlur = 22;
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      }
      const xPtr = pointer.current.x;
      if (xPtr !== null) {
        ctx.strokeStyle = "oklch(0.97 0.008 170 / .25)";
        ctx.setLineDash([3, 4]);
        ctx.beginPath();
        ctx.moveTo(xPtr + 0.5, 0);
        ctx.lineTo(xPtr + 0.5, H);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    };

    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      draw(now);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reduced, stageStart]);

  const tone = toneOf(stage);
  const color = TONE_COLOR[tone];
  const step = stage === IDLE ? null : STAGES[stage];

  return (
    <section
      aria-label="Network rhythm monitor"
      role="button"
      tabIndex={0}
      onClick={inject}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          inject();
        }
      }}
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        pointer.current = { x: e.clientX - r.left, y: (e.clientY - r.top) / r.height };
        if (chip.current) {
          chip.current.style.transform = `translate(${e.clientX - r.left + 16}px, ${e.clientY - r.top + 16}px)`;
        }
      }}
      onMouseLeave={() => {
        pointer.current = { x: null, y: null };
        if (chip.current) chip.current.style.transform = "translate(-999px, -999px)";
      }}
      className="relative h-[620px] cursor-crosshair overflow-hidden rounded-[32px] bg-[oklch(0.17_0.02_200)] text-[oklch(0.97_0.008_170)] shadow-[0_30px_80px_-40px_oklch(0.2_0.05_200/.7)] outline-offset-4 min-[700px]:h-[clamp(600px,82vh,860px)]"
    >
      <canvas ref={canvas} aria-hidden className="absolute inset-0 size-full" />
      <p aria-live="polite" className="sr-only">
        {step ? `Stage 0${stage + 1} ${step.name}: ${step.sentence}` : "Rhythm stable. Activate to inject a disruption."}
      </p>

      <div className="pointer-events-none absolute inset-x-7 top-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3.5 font-mono text-xs tracking-[0.06em] opacity-55">
          <span className="hidden sm:inline">NEUROGRID · NETWORK RHYTHM · LEAD II</span>
          <span>SIM {simLabel}</span>
        </div>
        <span
          key={tone}
          className="inline-flex animate-[ng-rise_.4s_ease-out] items-center gap-2 rounded-full border px-[13px] py-[7px] text-caption font-semibold"
          style={{
            color,
            background: `color-mix(in oklch, ${color} 14%, transparent)`,
            borderColor: `color-mix(in oklch, ${color} 45%, transparent)`,
          }}
        >
          <span
            aria-hidden
            className={cn("size-[7px] rounded-full", tone === "alarm" ? "animate-[ng-blink_.8s_infinite]" : "animate-ng-pulse [animation-duration:2s]")}
            style={{ background: color }}
          />
          {STATUS[tone]}
        </span>
      </div>

      <div className="pointer-events-none absolute top-[76px] right-7 hidden w-[230px] flex-col gap-2.5 min-[900px]:flex">
        {vitals(stage).map((v) => (
          <div key={v.label} className="flex flex-col gap-0.5 rounded-[14px] border border-[oklch(0.97_0.008_170/.1)] bg-[oklch(0.97_0.008_170/.05)] px-3.5 py-3">
            <span className="font-mono text-micro tracking-[0.1em] opacity-60">{v.label}</span>
            <span
              className={cn("font-mono text-[38px] leading-[1.05] font-medium tracking-[-0.03em] tabular-nums", v.blink && "animate-[ng-blink_1s_infinite]")}
              style={{ color: v.color }}
            >
              {v.value}
            </span>
            <span className="min-h-[1lh] text-label opacity-60">{v.sub}</span>
          </div>
        ))}
      </div>

      <h1 className="pointer-events-none absolute right-7 bottom-[86px] left-7 flex flex-col font-serif text-[40px] leading-[0.98] font-normal tracking-[-0.025em] min-[700px]:text-[clamp(52px,6.4vw,104px)] min-[900px]:right-[290px]">
        {HEADLINE.map((text, i) => {
          const on = GROUPS[i].includes(stage);
          return (
            <span
              key={text}
              className="transition-[color,opacity,transform] duration-500"
              style={{
                fontStyle: on ? "italic" : "normal",
                color: on ? HEADLINE_COLOR[i] : FG,
                opacity: on ? 1 : stage === IDLE ? 0.92 : 0.38,
                transform: on ? "translateX(10px)" : "none",
              }}
            >
              {text}
            </span>
          );
        })}
      </h1>

      <div className="absolute inset-x-7 bottom-6 grid grid-cols-8 gap-1.5">
        {STAGES.map((st, i) => {
          const current = i === stage;
          return (
            <button
              key={st.name}
              type="button"
              aria-label={`Jump to ${st.name}`}
              aria-current={current ? "step" : undefined}
              onClick={(e) => {
                e.stopPropagation();
                jump(i);
              }}
              className="flex flex-col gap-[7px] py-1 text-left"
            >
              <span className="relative block h-[3px] overflow-hidden rounded-sm bg-[oklch(0.97_0.008_170/.14)]">
                <span
                  key={current ? `on-${stage}-${playing}` : `off-${i}`}
                  className={cn(
                    "absolute inset-0 origin-left",
                    current && playing && "animate-[ng-fill_2600ms_linear_forwards]",
                    current && !playing && "scale-x-100",
                    !current && i < stage && stage !== IDLE && "scale-x-100",
                    !current && (i > stage || stage === IDLE) && "scale-x-0",
                  )}
                  style={{ background: tickColor(i, stage) }}
                />
              </span>
              <span
                className={cn(
                  "truncate font-mono text-[11px] tracking-[0.06em] uppercase",
                  current ? "font-semibold opacity-100" : "hidden opacity-50 min-[700px]:block",
                )}
              >
                0{i + 1} {st.name}
              </span>
            </button>
          );
        })}
      </div>

      {stage === IDLE ? (
        <span
          ref={chip}
          aria-hidden
          className="pointer-events-none absolute top-0 left-0 translate-x-[-999px] rounded-full bg-[oklch(0.86_0.13_168)] px-3 py-[7px] text-caption font-medium whitespace-nowrap text-[oklch(0.18_0.03_170)] shadow-[0_8px_24px_-8px_oklch(0.86_0.13_168)]"
          style={{ transform: "translate(-999px, -999px)" }}
        >
          Click anywhere to inject a disruption
        </span>
      ) : null}
    </section>
  );
}
