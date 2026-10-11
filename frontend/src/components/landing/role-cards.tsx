"use client";

import Link from "next/link";

import { DEMO_ROLES, type DemoRole } from "@/lib/roles";

import { useLandingMetrics } from "./live-readout";

const STEPS: Record<DemoRole["id"], string> = {
  coordinator: "01 · 02 · 03",
  clinical_lead: "04",
  physician: "05",
};

/** The spotlight follows the cursor through two CSS variables; no React state. */
function track(event: React.MouseEvent<HTMLElement>) {
  const el = event.currentTarget;
  const rect = el.getBoundingClientRect();
  el.style.setProperty("--mx", `${event.clientX - rect.left}px`);
  el.style.setProperty("--my", `${event.clientY - rect.top}px`);
}

export function RoleCards() {
  const m = useLandingMetrics();
  const meta: Record<DemoRole["id"], string> = {
    coordinator:
      m.critical === null
        ? "Alerts, forecasts, proposals"
        : `${m.critical} critical alert${m.critical === 1 ? "" : "s"} now`,
    clinical_lead:
      m.pending === null
        ? "Approves every offer"
        : `${m.pending} awaiting approval`,
    physician: "Phone-first · no patient data",
  };

  return (
    <ul className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,280px),1fr))] gap-4">
      {DEMO_ROLES.map((role) => {
        const Icon = role.icon;
        return (
          <li key={role.id}>
            <Link
              href={role.href}
              onMouseMove={track}
              style={
                {
                  "--tone": "var(--primary)",
                  background:
                    "radial-gradient(420px circle at var(--mx, 50%) var(--my, 0%), color-mix(in oklch, var(--tone) 11%, transparent), transparent 65%), var(--card)",
                } as React.CSSProperties
              }
              className="group flex h-full flex-col gap-4 rounded-3xl border border-border-subtle p-[26px] outline-none hover:-translate-y-[3px] hover:border-primary-border focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <span className="flex items-center justify-between gap-3">
                <span className="flex size-10 items-center justify-center rounded-[10px] bg-primary-soft text-primary-ink">
                  <Icon className="size-5" aria-hidden />
                </span>
                <span className="font-mono text-xs text-muted-foreground">{STEPS[role.id]}</span>
              </span>
              <span className="space-y-1.5">
                <span className="block text-xl font-semibold tracking-[-0.01em] text-foreground">
                  {role.label}
                </span>
                <span className="block text-body text-foreground-2">{role.description}</span>
              </span>
              <span className="mt-auto flex items-center justify-between gap-3 border-t border-border-subtle pt-4 text-caption">
                <span className="truncate text-muted-foreground">{meta[role.id]}</span>
                <span className="shrink-0 font-semibold text-primary-ink">
                  Open{" "}
                  <span
                    aria-hidden
                    className="inline-block transition-transform group-hover:translate-x-0.5"
                  >
                    →
                  </span>
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
