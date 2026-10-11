"use client";

import { useEffect, useRef } from "react";

import { IDLE, STAGES, STAGE_MS, type RescueLoop } from "./rescue-loop";

interface Pt {
  x: number;
  y: number;
}
interface Hospital extends Pt {
  name: string;
}
interface Physician extends Pt {
  off: boolean;
}
interface Pulse {
  edge?: { p: number; h: number };
  back?: boolean;
  rescue?: boolean;
  t: number;
  v: number;
}

const HOSPITALS: Hospital[] = (
  [
    ["Northfield", 0.5, 0.4],
    ["Redwood", 0.17, 0.22],
    ["Cedar Ridge", 0.82, 0.18],
    ["Suncrest", 0.2, 0.58],
    ["Lakeview", 0.8, 0.52],
    ["Mercy Bay", 0.52, 0.66],
    ["Harbor", 0.93, 0.36],
    ["Pinecrest", 0.07, 0.4],
    ["Oakmont", 0.38, 0.14],
    ["Riverside", 0.64, 0.24],
  ] as const
).map(([name, x, y]) => ({ name, x, y }));

/** Deterministic illustrative layout (mulberry32, seed 11): 18 physicians and their credentials. */
function buildNetwork() {
  let a = 11;
  const rand = () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const phys: Physician[] = [];
  for (let guard = 0; phys.length < 18 && guard < 4000; guard++) {
    const x = 0.05 + rand() * 0.9;
    const y = 0.08 + rand() * 0.62;
    if (HOSPITALS.some((h) => Math.hypot(h.x - x, (h.y - y) * 0.8) < 0.085)) continue;
    if (phys.some((p) => Math.hypot(p.x - x, p.y - y) < 0.075)) continue;
    phys.push({ x, y, off: rand() < 0.3 });
  }
  const target = HOSPITALS[0];
  const byDistance = phys
    .map((p, i) => [i, Math.hypot(p.x - target.x, p.y - target.y)] as const)
    .sort((u, v) => u[1] - v[1]);
  const rescuer = (byDistance.find(([i]) => phys[i].off) ?? byDistance[0])[0];
  phys[rescuer].off = true;
  const candidates = [rescuer, ...byDistance.filter(([i]) => i !== rescuer).slice(0, 3).map(([i]) => i)];
  const edges: { p: number; h: number }[] = [];
  phys.forEach((p, i) => {
    const near = HOSPITALS.map((h, j) => [j, Math.hypot(h.x - p.x, h.y - p.y)] as const).sort((u, v) => u[1] - v[1]);
    const k = 2 + (rand() < 0.4 ? 1 : 0);
    near.slice(0, k).forEach(([j]) => {
      if (!(i === rescuer && j === 0)) edges.push({ p: i, h: j });
    });
  });
  return { phys, rescuer, candidates, edges };
}

function readColors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (name: string) => cs.getPropertyValue(name).trim();
  return {
    prim: v("--primary"),
    crit: v("--critical"),
    warn: v("--warning"),
    ok: v("--success"),
    ink: v("--foreground"),
    sub: v("--foreground-2"),
    muted: v("--faint-foreground"),
    line: v("--border-strong"),
    grid: v("--border-subtle"),
    bg: v("--card-subtle"),
  };
}

export function NetworkReplay({ loop }: { loop: RescueLoop }) {
  const { stage, reduced, stageStart } = loop;
  const canvas = useRef<HTMLCanvasElement>(null);
  const mouse = useRef<Pt>({ x: -999, y: -999 });
  const stageRef = useRef(stage);
  useEffect(() => {
    stageRef.current = stage;
  }, [stage]);

  useEffect(() => {
    const cv = canvas.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const { phys, rescuer, candidates, edges } = buildNetwork();
    let pulses: Pulse[] = [];
    let colors = readColors();
    let frame = 0;
    let raf = 0;

    const draw = (now: number) => {
      if (frame++ % 30 === 0) colors = readColors();
      const C = colors;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const W = cv.clientWidth;
      const H = cv.clientHeight;
      if (cv.width !== W * dpr || cv.height !== H * dpr) {
        cv.width = W * dpr;
        cv.height = H * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const s = stageRef.current;
      const st = reduced ? 1 : Math.min(1, (now - stageStart.current) / STAGE_MS);
      const X = (n: Pt) => 24 + n.x * (W - 48);
      const Y = (n: Pt) => 50 + (n.y * (H - 150)) / 0.8;
      const m = mouse.current;

      ctx.fillStyle = C.grid;
      ctx.globalAlpha = 0.55;
      for (let x = 14; x < W; x += 26) for (let y = 14; y < H; y += 26) ctx.fillRect(x, y, 1.2, 1.2);
      ctx.globalAlpha = 1;

      let hovered: Pt | null = null;
      let best = 34;
      for (const n of [...HOSPITALS, ...phys]) {
        const d = Math.hypot(X(n) - m.x, Y(n) - m.y);
        if (d < best) {
          best = d;
          hovered = n;
        }
      }
      const T = HOSPITALS[0];
      const broken = s >= 1 && s <= 6;

      for (const e of edges) {
        const p = phys[e.p];
        const h = HOSPITALS[e.h];
        const toTarget = e.h === 0;
        const lit = hovered === p || hovered === h;
        const near = Math.hypot((X(p) + X(h)) / 2 - m.x, (Y(p) + Y(h)) / 2 - m.y) < 140;
        ctx.beginPath();
        ctx.moveTo(X(p), Y(p));
        ctx.lineTo(X(h), Y(h));
        ctx.setLineDash(toTarget && broken ? [3, 5] : []);
        ctx.strokeStyle = toTarget && broken ? C.crit : lit ? C.prim : C.line;
        ctx.globalAlpha = toTarget && broken ? 0.55 : lit ? 0.95 : near ? 0.75 : 0.45;
        ctx.lineWidth = lit ? 1.6 : 1;
        ctx.stroke();
      }
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;

      const R = phys[rescuer];
      if (!reduced) {
        if (frame % 7 === 0 && pulses.length < 40) {
          const e = edges[Math.floor(Math.random() * edges.length)];
          if (!(e.h === 0 && broken)) pulses.push({ edge: e, t: 0, v: 0.006 + Math.random() * 0.008, back: Math.random() < 0.5 });
        }
        if (s >= 6 && s < IDLE && frame % 10 === 0) pulses.push({ rescue: true, t: 0, v: 0.012 });
        pulses = pulses.filter((pu) => {
          pu.t += pu.v;
          if (pu.t > 1) return false;
          let a: Pt;
          let b: Pt;
          if (pu.rescue || !pu.edge) {
            a = R;
            b = T;
          } else {
            if (pu.edge.h === 0 && broken) return false;
            a = phys[pu.edge.p];
            b = HOSPITALS[pu.edge.h];
            if (pu.back) [a, b] = [b, a];
          }
          ctx.beginPath();
          ctx.arc(X(a) + (X(b) - X(a)) * pu.t, Y(a) + (Y(b) - Y(a)) * pu.t, pu.rescue ? 2.6 : 1.8, 0, Math.PI * 2);
          ctx.fillStyle = C.prim;
          ctx.globalAlpha = Math.sin(pu.t * Math.PI) * 0.9;
          ctx.fill();
          return true;
        });
        ctx.globalAlpha = 1;
      }

      if (s >= 4 && s < IDLE) {
        const frac = s === 4 ? st : 1;
        ctx.beginPath();
        ctx.moveTo(X(R), Y(R));
        ctx.lineTo(X(R) + (X(T) - X(R)) * frac, Y(R) + (Y(T) - Y(R)) * frac);
        ctx.setLineDash(s < 6 ? [6, 5] : []);
        ctx.lineDashOffset = reduced ? 0 : -now / 40;
        ctx.strokeStyle = s === 5 ? C.warn : C.prim;
        ctx.lineWidth = s >= 6 ? 2.4 : 1.8;
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.lineDashOffset = 0;
      }

      phys.forEach((p, i) => {
        const x = X(p);
        const y = Y(p);
        const isR = i === rescuer;
        const lit = hovered === p;
        ctx.beginPath();
        ctx.arc(x, y, lit ? 6 : isR && s >= 3 && s < IDLE ? 5.5 : 4.2, 0, Math.PI * 2);
        if (p.off && !(isR && s >= 6 && s < IDLE)) {
          ctx.fillStyle = C.bg;
          ctx.fill();
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = isR && s >= 3 && s < IDLE ? C.prim : C.muted;
          ctx.stroke();
        } else {
          ctx.fillStyle = isR || lit ? C.prim : C.sub;
          ctx.fill();
        }
        if (s === 3 && candidates.includes(i) && st > candidates.indexOf(i) * 0.2) {
          ctx.beginPath();
          ctx.arc(x, y, 11, 0, Math.PI * 2);
          ctx.strokeStyle = isR ? C.ok : C.crit;
          ctx.globalAlpha = 0.9;
          ctx.lineWidth = 1.4;
          ctx.stroke();
          ctx.globalAlpha = 1;
          ctx.font = "600 11px Geist, sans-serif";
          ctx.fillStyle = isR ? C.ok : C.crit;
          ctx.fillText(isR ? "✓ eligible" : "✕", x + 14, y + 4);
        }
        if (isR && s >= 4 && s < IDLE) {
          ctx.font = "600 11.5px Geist, sans-serif";
          ctx.fillStyle = C.ink;
          ctx.fillText("Dr. Okafor", x + 10, y - 9);
        }
      });

      HOSPITALS.forEach((h, j) => {
        const x = X(h);
        const y = Y(h);
        const isT = j === 0;
        const lit = hovered === h;
        const col = isT ? (s === IDLE ? C.ink : s === 7 ? C.ok : C.crit) : lit ? C.prim : C.ink;
        if (isT && !reduced && (s === 0 || s === 7)) {
          const ph = (now % 1400) / 1400;
          ctx.beginPath();
          ctx.arc(x, y, 10 + ph * 34, 0, Math.PI * 2);
          ctx.strokeStyle = col;
          ctx.globalAlpha = 1 - ph;
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.globalAlpha = 1;
        }
        if (isT && s === 2) {
          ctx.beginPath();
          ctx.arc(x, y, 22, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - st));
          ctx.strokeStyle = C.warn;
          ctx.lineWidth = 3;
          ctx.lineCap = "round";
          ctx.stroke();
          ctx.lineCap = "butt";
        }
        if (isT && s === 5) {
          ctx.beginPath();
          ctx.arc(x, y, 22, 0, Math.PI * 2);
          ctx.strokeStyle = C.warn;
          ctx.setLineDash([2, 4]);
          ctx.lineWidth = 1.5;
          ctx.stroke();
          ctx.setLineDash([]);
        }
        const size = isT ? 15 : lit ? 12 : 10;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x - size / 2, y - size / 2, size, size, 3);
        else ctx.rect(x - size / 2, y - size / 2, size, size);
        ctx.fillStyle = col;
        ctx.fill();
        if (isT || lit || Math.hypot(x - m.x, y - m.y) < 160) {
          ctx.font = `${isT ? "600 13px" : "500 11.5px"} Geist, sans-serif`;
          ctx.fillStyle = isT ? C.ink : C.sub;
          ctx.fillText(h.name, x + size / 2 + 7, y + 4);
          if (isT && s < IDLE) {
            ctx.font = '500 11.5px "Geist Mono", monospace';
            ctx.fillStyle = s === 7 ? C.ok : s >= 5 ? C.sub : C.crit;
            ctx.fillText(STAGES[s].status, x + size / 2 + 7, y + 20);
          }
        }
      });

      if (hovered && !HOSPITALS.includes(hovered as Hospital)) {
        ctx.font = "500 11.5px Geist, sans-serif";
        ctx.fillStyle = C.ink;
        ctx.fillText((hovered as Physician).off ? "Off-shift physician" : "On-shift physician", X(hovered) + 10, Y(hovered) - 10);
      }
    };

    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      draw(now);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reduced, stageStart]);

  return (
    <div
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        mouse.current = { x: e.clientX - r.left, y: e.clientY - r.top };
      }}
      onMouseLeave={() => {
        mouse.current = { x: -999, y: -999 };
      }}
      className="relative h-[440px] overflow-hidden rounded-[28px] border border-border-subtle bg-card-subtle min-[700px]:h-[540px] min-[1200px]:h-[640px]"
    >
      <canvas
        ref={canvas}
        role="img"
        aria-label="Animated network replaying the rescue loop at Northfield"
        className="absolute inset-0 size-full"
      />
      <div className="pointer-events-none absolute inset-x-5 top-[18px] flex flex-wrap items-center justify-between gap-2.5 text-label text-muted-foreground">
        <span className="font-mono">10 HOSPITALS · 18 PHYSICIANS · ILLUSTRATIVE</span>
        <span className="flex gap-3">
          <span className="flex items-center gap-1.5">
            <span className="size-2 rounded-[2px] bg-faint-foreground" />
            hospital
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-[7px] rounded-full bg-faint-foreground" />
            on shift
          </span>
          <span className="flex items-center gap-1.5">
            <span className="size-[7px] rounded-full border-[1.5px] border-faint-foreground" />
            off shift
          </span>
        </span>
      </div>
    </div>
  );
}
