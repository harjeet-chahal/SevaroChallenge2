"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LOOP_NAV, NETWORK_NAV } from "@/lib/nav";
import { cn } from "@/lib/utils";

import { navigateInPage, useActiveNav, useNavCounts } from "./use-nav";

const ITEMS = [LOOP_NAV[0], LOOP_NAV[1], NETWORK_NAV, LOOP_NAV[2], LOOP_NAV[3]];

/** Phones: the rescue loop as a dark bottom bar (the sidebar is hidden below 900px). */
export function BottomNav() {
  const pathname = usePathname();
  const activeId = useActiveNav();
  const counts = useNavCounts();

  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 bg-clock-bg pb-[env(safe-area-inset-bottom)] text-clock-fg min-[900px]:hidden"
    >
      {ITEMS.map((item) => {
        const active = activeId === item.id;
        const count = counts[item.id];
        return (
          <Link
            key={item.id}
            href={item.href}
            aria-current={active ? "page" : undefined}
            onClick={(e) => navigateInPage(e, pathname, item)}
            className={cn(
              "flex min-w-0 flex-col items-center gap-1.5 px-1 pt-3 pb-2.5 text-[10px]",
              active ? "font-semibold text-clock-fg" : "text-clock-fg/65",
            )}
          >
            <span className="relative flex h-2 items-center">
              <span
                aria-hidden
                className={cn(
                  "size-2 rounded-full",
                  active ? "bg-primary ring-3 ring-primary/25" : "bg-clock-fg/30",
                )}
              />
              {count ? (
                <span
                  className={cn(
                    "absolute -top-1.5 left-2.5 rounded-full px-1 font-mono text-[9px] leading-[13px] font-semibold",
                    count.tone === "critical"
                      ? "bg-critical text-critical-foreground"
                      : "bg-warning text-warning-foreground",
                  )}
                >
                  {count.count}
                  <span className="sr-only"> — {count.label}</span>
                </span>
              ) : null}
            </span>
            <span className="max-w-full truncate">{item.short}</span>
          </Link>
        );
      })}
    </nav>
  );
}
