import { BrainCircuit } from "lucide-react";
import Link from "next/link";

import { BackendStatusBadge } from "@/components/status/backend-status-badge";

import { OpsNav } from "./ops-nav";
import { RoleSwitcher } from "./role-switcher";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-navy text-navy-foreground shadow-sm">
      <div className="mx-auto flex max-w-screen-2xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/"
            className="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-white/70"
          >
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <BrainCircuit className="size-4.5" aria-hidden />
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold tracking-wide sm:text-base">NEUROGRID</span>
              <span className="hidden text-xs text-navy-foreground/70 md:block">
                Self-healing teleneurology operations network
              </span>
            </span>
          </Link>
          <BackendStatusBadge className="sm:hidden" />
        </div>
        <div className="flex items-center gap-3">
          <RoleSwitcher className="w-full sm:w-auto" />
          <BackendStatusBadge className="hidden sm:inline-flex" />
        </div>
      </div>
      <OpsNav />
    </header>
  );
}
