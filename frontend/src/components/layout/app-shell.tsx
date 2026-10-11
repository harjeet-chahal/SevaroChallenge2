"use client";

import { usePathname } from "next/navigation";

import { BackendStatusBadge } from "@/components/status/backend-status-badge";
import { ClockPill } from "@/components/status/monitor-card";
import { cn } from "@/lib/utils";

import { BottomNav } from "./bottom-nav";
import { Lifeline } from "./ecg";
import { RoleSwitcher } from "./role-switcher";
import { Sidebar } from "./sidebar";
import { ThemeToggle } from "./theme-toggle";
import { Wordmark } from "./wordmark";

function TopBar({ withSidebar }: { withSidebar: boolean }) {
  return (
    <header className="sticky top-0 z-40 bg-background/90 backdrop-blur-md">
      <div className="flex min-h-[60px] items-center gap-3 px-4 py-3 min-[900px]:px-8">
        <div
          className={cn(
            "flex min-w-0 items-center gap-3",
            withSidebar && "min-[900px]:hidden",
          )}
        >
          <Wordmark compact className="max-[359px]:[&>span]:hidden" />
          <ClockPill />
        </div>
        <div className="ml-auto flex items-center gap-2.5">
          <RoleSwitcher className="max-[899px]:hidden" />
          <span aria-hidden className="h-6 w-px bg-border max-[899px]:hidden" />
          <ThemeToggle />
          <BackendStatusBadge className="pl-1" />
        </div>
      </div>
      <Lifeline className="-mt-[9px]" />
    </header>
  );
}

/**
 * App pages get the sidebar (wordmark, monitor card, rescue loop) on desktop and a dark
 * bottom bar on phones. The role overview at "/" uses the top bar only.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const withSidebar = pathname !== "/";

  return (
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-[9px] bg-foreground px-3 py-2 text-sm font-semibold text-background focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      {withSidebar ? <Sidebar /> : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar withSidebar={withSidebar} />
        <main
          id="main"
          className="flex-1 px-4 pt-4 pb-28 min-[900px]:px-8 min-[900px]:pt-7 min-[900px]:pb-12"
        >
          <div className="mx-auto w-full max-w-[1440px]">{children}</div>
        </main>
      </div>
      <BottomNav />
    </div>
  );
}
