"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import {
  DataControlsSheet,
  datasetLabel,
  useActiveDataset,
} from "@/components/dataset/data-controls-sheet";
import { MonitorCard } from "@/components/status/monitor-card";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { LOOP_NAV, NETWORK_NAV, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";

import { type NavCount, navigateInPage, useActiveNav, useNavCounts } from "./use-nav";
import { Wordmark } from "./wordmark";

export function CountBadge({ count, className }: { count: NavCount; className?: string }) {
  return (
    <span
      title={count.label}
      className={cn(
        "inline-flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full px-1 font-mono text-micro font-semibold tabular-nums",
        count.tone === "critical"
          ? "bg-critical text-critical-foreground"
          : "bg-warning text-warning-foreground",
        className,
      )}
    >
      {count.count}
      <span className="sr-only"> — {count.label}</span>
    </span>
  );
}

function LoopLink({
  item,
  active,
  count,
}: {
  item: NavItem;
  active: boolean;
  count?: NavCount;
}) {
  const pathname = usePathname();
  return (
    <li>
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        onClick={(e) => navigateInPage(e, pathname, item)}
        className={cn(
          "relative flex h-[38px] items-center gap-2.5 rounded-[9px] px-2.5 hover:bg-card",
          active && "bg-card ring-1 ring-border-subtle ring-inset",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "relative z-10 size-[11px] shrink-0 rounded-full",
            active
              ? "bg-primary ring-4 ring-primary/20"
              : "border-[1.5px] border-border-strong bg-background",
          )}
        />
        <span
          className={cn(
            "min-w-0 flex-1 truncate text-sm",
            active ? "font-semibold text-foreground" : "text-foreground-2",
          )}
        >
          {item.label}
        </span>
        {count ? <CountBadge count={count} /> : null}
        {item.step ? (
          <span className="font-mono text-micro text-muted-foreground">{item.step}</span>
        ) : null}
      </Link>
    </li>
  );
}

const toolItem =
  "flex h-9 w-full items-center truncate rounded-[9px] pr-2.5 pl-[31px] text-left text-sm text-foreground-2 hover:bg-card hover:text-foreground";

/** One line about the data behind every number; opens the data drawer. */
function StatusChip({ onOpen }: { onOpen: () => void }) {
  const { config, connection } = useSystemStatus();
  const active = useActiveDataset();
  const unreachable = connection === "offline" || connection === "degraded";
  const loaded = Boolean(config?.dataset_loaded);
  const text = unreachable
    ? "Backend unreachable"
    : connection === "checking"
      ? "Connecting…"
      : !loaded
        ? "No dataset loaded"
        : active
          ? datasetLabel(active)
          : "Dataset loaded";

  return (
    <button
      type="button"
      onClick={onOpen}
      title="Dataset & simulation controls"
      className="flex w-full items-center gap-2 rounded-[10px] bg-card-subtle p-2.5 text-left text-label text-foreground-2 ring-1 ring-border-subtle ring-inset hover:bg-card"
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 shrink-0 rounded-full",
          unreachable ? "bg-critical" : loaded ? "bg-success" : "bg-warning",
        )}
      />
      <span className="min-w-0 flex-1 truncate">{text}</span>
      {active?.synthetic ? (
        <span className="shrink-0 font-mono text-micro text-warning-ink">synthetic</span>
      ) : null}
    </button>
  );
}

/** Desktop navigation: wordmark, the monitor card, the rescue loop and quiet tools. */
export function Sidebar() {
  const pathname = usePathname();
  const activeId = useActiveNav();
  const counts = useNavCounts();
  const [dataOpen, setDataOpen] = useState(false);

  return (
    <aside
      aria-label="Sidebar"
      className="sticky top-0 hidden h-dvh w-[260px] shrink-0 flex-col gap-5 overflow-y-auto border-r border-border-subtle bg-background px-3.5 pt-5 pb-3.5 min-[900px]:flex"
    >
      <Wordmark className="px-1.5" />
      <MonitorCard />

      <nav aria-labelledby="nav-loop" className="flex flex-col gap-1.5">
        <p id="nav-loop" className="px-2.5 text-label text-muted-foreground">
          Rescue loop
        </p>
        <ol className="relative flex flex-col gap-1">
          <span
            aria-hidden
            className="absolute top-[19px] bottom-[19px] left-[15px] w-px bg-border"
          />
          {LOOP_NAV.map((item) => (
            <LoopLink
              key={item.id}
              item={item}
              active={activeId === item.id}
              count={counts[item.id]}
            />
          ))}
        </ol>
      </nav>

      <nav aria-labelledby="nav-tools" className="flex flex-col gap-1.5">
        <p id="nav-tools" className="px-2.5 text-label text-muted-foreground">
          Tools
        </p>
        <ul className="flex flex-col">
          <li>
            <Link
              href={NETWORK_NAV.href}
              aria-current={activeId === "network" ? "page" : undefined}
              onClick={(e) => navigateInPage(e, pathname, NETWORK_NAV)}
              className={cn(
                toolItem,
                activeId === "network" && "font-semibold text-foreground",
              )}
            >
              {NETWORK_NAV.label}
            </Link>
          </li>
          <li>
            <button type="button" className={toolItem} onClick={() => setDataOpen(true)}>
              Data &amp; simulation
            </button>
          </li>
          <li>
            <Link href="/" className={toolItem}>
              Role overview
            </Link>
          </li>
        </ul>
      </nav>

      <div className="mt-auto">
        <StatusChip onOpen={() => setDataOpen(true)} />
      </div>
      <DataControlsSheet open={dataOpen} onOpenChange={setDataOpen} />
    </aside>
  );
}
