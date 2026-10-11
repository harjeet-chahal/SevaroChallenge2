import { Activity } from "lucide-react";
import Link from "next/link";

import { BackendStatusBadge } from "@/components/status/backend-status-badge";
import { SimClock } from "@/components/status/sim-clock";

import { RoleSwitcher } from "./role-switcher";

export function AppHeader() {
  return (
    <header className="sticky top-0 z-40 bg-navy text-navy-foreground shadow-sm">
      <div className="mx-auto flex max-w-screen-2xl flex-col gap-2 px-4 py-2.5 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/"
            className="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-white/70"
          >
            <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Activity className="size-4.5" aria-hidden />
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold sm:text-base">Sevaro Pulse</span>
              <span className="hidden text-xs text-navy-foreground/70 xl:block">
                Tele-Neurology Operations Command Center
              </span>
            </span>
          </Link>
          <div className="flex items-center gap-2 lg:hidden">
            <SimClock />
            <BackendStatusBadge className="max-sm:hidden" />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <SimClock className="max-lg:hidden" />
          <RoleSwitcher className="w-full lg:w-auto" />
          <BackendStatusBadge className="max-lg:hidden" />
        </div>
      </div>
    </header>
  );
}
