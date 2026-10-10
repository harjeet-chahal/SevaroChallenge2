import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { SimulationStatus } from "@/components/status/simulation-status";
import { DEMO_ROLES } from "@/lib/roles";

export default function Home() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Demo"
        title="Choose a role"
        description="Sevaro Pulse turns tele-neurology coverage risk into approved, tracked interventions. Pick a view to explore — there is no login in this demo."
      />
      <SimulationStatus />
      <ul className="grid gap-4 md:grid-cols-3">
        {DEMO_ROLES.map((role) => {
          const Icon = role.icon;
          return (
            <li key={role.id}>
              <Link
                href={role.href}
                className="group flex h-full flex-col gap-3 rounded-xl border bg-card p-5 shadow-xs transition-colors outline-none hover:border-primary/40 hover:bg-accent/40 focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <span className="flex size-10 items-center justify-center rounded-lg bg-secondary text-primary">
                  <Icon className="size-5" aria-hidden />
                </span>
                <span className="text-base font-semibold text-navy">{role.label}</span>
                <span className="flex-1 text-sm text-muted-foreground">{role.description}</span>
                <span className="inline-flex items-center gap-1 text-sm font-medium text-primary">
                  Open view
                  <ArrowRight
                    className="size-4 transition-transform group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
