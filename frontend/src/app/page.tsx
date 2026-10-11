import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { DEMO_ROLES } from "@/lib/roles";

const LOOP = ["Detect", "Diagnose", "Forecast", "Decide", "Simulate", "Approve", "Act", "Verify"];

const ROLE_CARD = {
  coordinator: {
    monogram: "OC",
    description: "Watch the network, find problems, forecast the last safe moment and propose rescues.",
    meta: "Desktop · 7 operations views",
  },
  clinical_lead: {
    monogram: "CL",
    description: "Approve or reject proposed rescues. Nothing reaches a physician without this approval.",
    meta: "Desktop · re-validated on approval",
  },
  physician: {
    monogram: "PH",
    description: "Receive shift offers on your phone and accept or decline them.",
    meta: "Mobile · no patient information",
  },
} as const;

export default function Home() {
  return (
    <div className="flex flex-col gap-10 py-2 sm:py-10">
      <div className="flex max-w-[860px] flex-col gap-[18px]">
        <span className="text-[11px] font-semibold tracking-[0.14em] text-primary uppercase">
          Rutgers Health Hack · Sevaro challenge · Synthetic data
        </span>
        <h1 className="font-serif text-[38px] leading-[1.04] font-normal tracking-[-0.015em] text-balance sm:text-[64px]">
          Detect the disruption. Find the last safe opportunity. Engineer the rescue. Verify the recovery.
        </h1>
        <p className="max-w-[640px] text-base leading-relaxed text-foreground-2">
          A real-time control room for a teleneurology network. Rule-based detection, deadline forecasting and
          simulated rescues, with every action approved by a clinical lead. There is no login in this demo: pick a
          role.
        </p>
      </div>
      <ol
        aria-label="The rescue loop"
        className="grid grid-cols-2 overflow-hidden rounded-xl border bg-card-subtle sm:grid-cols-4 lg:grid-cols-8"
      >
        {LOOP.map((label, i) => (
          <li key={label} className="flex flex-col gap-1 border-r border-b px-4 py-3.5 lg:border-b-0">
            <span className="font-mono text-[11px] text-primary">0{i + 1}</span>
            <span className="text-[13px] font-semibold tracking-[0.08em] uppercase">{label}</span>
          </li>
        ))}
      </ol>
      <ul className="grid gap-4 md:grid-cols-3">
        {DEMO_ROLES.map((role) => {
          const card = ROLE_CARD[role.id];
          return (
            <li key={role.id}>
              <Link
                href={role.href}
                className="group flex h-full flex-col gap-3.5 rounded-2xl border bg-card p-6 transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/70"
              >
                <span className="grid size-10 place-items-center rounded-[10px] bg-primary-soft font-mono font-semibold text-primary">
                  {card.monogram}
                </span>
                <span className="text-[19px] font-semibold">{role.label}</span>
                <span className="flex-1 text-sm leading-relaxed text-foreground-2">{card.description}</span>
                <span className="text-[13px] text-muted-foreground">{card.meta}</span>
                <span className="inline-flex items-center gap-1 text-sm font-semibold text-primary-ink">
                  Open view
                  <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
