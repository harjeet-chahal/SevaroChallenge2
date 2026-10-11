"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { useLiveResource } from "@/hooks/use-live-resource";
import { analysisApi, datasetApi } from "@/lib/api/endpoints";
import { DEMO_ROLES } from "@/lib/roles";
import { datasetName } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { BackendStatusBadge } from "@/components/status/backend-status-badge";

import { ClockCard, ClockPill, MobileClockControls } from "./clock-card";
import { Lifeline, Wordmark } from "./heartbeat";
import { LOOP_NAV, TOOL_NAV, isActive, isOpsPath, type NavItem } from "./nav";
import { ThemeToggle } from "./theme-toggle";

function useBadges(): Record<NonNullable<NavItem["badge"]>, number> {
  const { config } = useSystemStatus();
  const alerts = useLiveResource((s) => analysisApi.alerts(s));
  return {
    "critical-alerts": alerts.data?.counts_by_severity.critical ?? 0,
    "pending-approvals": config?.pending_approvals ?? 0,
  };
}

function CountBadge({ n, tone }: { n: number; tone: NavItem["badge"] }) {
  return (
    <span
      className={cn(
        "grid h-[18px] min-w-[18px] place-items-center rounded-full px-1.5 font-mono text-micro font-semibold tabular-nums",
        tone === "critical-alerts" ? "bg-critical text-critical-foreground" : "bg-warning text-warning-foreground",
      )}
    >
      {n}
    </span>
  );
}

function DatasetChip() {
  const { config } = useSystemStatus();
  const status = useLiveResource((s) => datasetApi.status(s));
  const active = status.data?.active;
  if (!config?.dataset_loaded) {
    return (
      <Link href="/import" className="flex items-center gap-2 rounded-[10px] bg-card-subtle p-2.5 text-label text-muted-foreground hover:text-foreground">
        <span aria-hidden className="size-1.5 rounded-full bg-warning" />
        No dataset loaded · open Data import
      </Link>
    );
  }
  return (
    <div className="flex items-center gap-2 rounded-[10px] bg-card-subtle p-2.5 text-label text-muted-foreground">
      <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-success" />
      <span className="truncate">
        {active ? datasetName(active) : "dataset loaded"} · {active?.synthetic === false ? "dataset" : "synthetic only"}
      </span>
    </div>
  );
}

function Sidebar() {
  const pathname = usePathname();
  const badges = useBadges();
  return (
    <aside className="sticky top-0 hidden h-dvh w-[260px] shrink-0 flex-col gap-5 border-r border-border-subtle bg-background px-3.5 pt-5 pb-3.5 min-[900px]:flex">
      <Wordmark className="px-2" />
      <ClockCard />
      <nav aria-label="Rescue loop" className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
        <span className="px-2.5 pb-2 text-label text-muted-foreground">Rescue loop</span>
        <div className="relative flex flex-col gap-0.5">
          <span aria-hidden className="absolute top-[18px] bottom-[18px] left-[15px] w-px bg-border" />
          {LOOP_NAV.map((item) => {
            const on = isActive(pathname, item.href);
            const n = item.badge ? badges[item.badge] : 0;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={on ? "page" : undefined}
                className={cn(
                  "flex h-[38px] items-center gap-2.5 rounded-[9px] px-2.5 text-left transition-colors hover:bg-card",
                  on && "bg-card ring-1 ring-border-subtle ring-inset",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "relative z-10 size-[11px] shrink-0 rounded-full border-[1.5px]",
                    on ? "border-primary bg-primary ring-4 ring-primary/20" : "border-border-strong bg-background",
                  )}
                />
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate text-sm",
                    on ? "font-semibold text-foreground" : "text-foreground-2",
                  )}
                >
                  {item.label}
                </span>
                {n > 0 ? <CountBadge n={n} tone={item.badge} /> : null}
                <span className="font-mono text-micro whitespace-nowrap text-muted-foreground">{item.stage}</span>
              </Link>
            );
          })}
        </div>
        <span className="px-2.5 pt-[18px] pb-2 text-label text-muted-foreground">Tools</span>
        {TOOL_NAV.map((item) => {
          const on = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={on ? "page" : undefined}
              className={cn(
                "flex h-9 items-center rounded-[9px] pr-2.5 pl-[33px] text-sm transition-colors hover:bg-card",
                on ? "bg-card font-semibold text-foreground" : "text-foreground-2",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
      <DatasetChip />
    </aside>
  );
}

function RoleTabs() {
  const pathname = usePathname();
  const pending = useSystemStatus().config?.pending_approvals ?? 0;
  const active =
    DEMO_ROLES.find((r) => isActive(pathname, r.href))?.id ?? (isOpsPath(pathname) ? "coordinator" : null);
  const short = { coordinator: "Ops", clinical_lead: "Lead", physician: "MD" } as const;
  const full = { coordinator: "Coordinator", clinical_lead: "Clinical lead", physician: "Physician" } as const;
  return (
    <nav aria-label="Demo role" className="flex gap-1">
      {DEMO_ROLES.map((role) => {
        const on = active === role.id;
        return (
          <Link
            key={role.id}
            href={role.href}
            aria-current={on ? "page" : undefined}
            title={`${role.label} view (demo role — no login; the backend enforces permissions)`}
            className={cn(
              "flex h-[34px] items-center gap-1.5 rounded-full border px-3.5 text-[13.5px] whitespace-nowrap transition-colors",
              on
                ? "border-foreground bg-foreground font-semibold text-background"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <span className="min-[1180px]:hidden">{short[role.id]}</span>
            <span className="hidden min-[1180px]:inline">{full[role.id]}</span>
            {role.id === "clinical_lead" && pending > 0 ? (
              <span
                aria-label={`${pending} pending approval${pending > 1 ? "s" : ""}`}
                className="grid h-[18px] min-w-[18px] place-items-center rounded-full bg-warning px-1.5 font-mono text-[11px] font-semibold text-warning-foreground"
              >
                {pending}
              </span>
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}

function TopBar({ ops }: { ops: boolean }) {
  return (
    <header className="sticky top-0 z-30 bg-background/90 backdrop-blur-md">
      <div className="flex min-h-[60px] flex-wrap items-center gap-3.5 px-4 py-3 min-[900px]:px-8">
        <div className={cn("flex items-center gap-3", ops && "min-[900px]:hidden")}>
          <Wordmark />
          <ClockPill />
        </div>
        <div className="flex-1" />
        <RoleTabs />
        <span aria-hidden className="h-[22px] w-px bg-border" />
        <ThemeToggle />
        <BackendStatusBadge />
      </div>
      <Lifeline />
    </header>
  );
}

function BottomNav() {
  const pathname = usePathname();
  const items = [...LOOP_NAV.filter((i) => i.href !== "/clinical-lead"), ...TOOL_NAV];
  return (
    <nav
      aria-label="Rescue loop"
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-7 bg-clock-bg px-1.5 pt-2 pb-[calc(8px+env(safe-area-inset-bottom))] min-[900px]:hidden"
    >
      {items.map((item) => {
        const on = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-label={item.label}
            aria-current={on ? "page" : undefined}
            className={cn(
              "flex min-h-[46px] flex-col items-center justify-center gap-1.5 rounded-lg text-[10px] tracking-[-0.01em]",
              on ? "font-semibold text-clock-fg" : "text-clock-fg/65",
            )}
          >
            <span
              aria-hidden
              className={cn("size-2 rounded-full border-[1.5px]", on ? "border-primary bg-primary" : "border-clock-fg/50")}
            />
            <span className="w-full truncate px-0.5 text-center">{item.short}</span>
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * Operations pages get the rescue-loop sidebar (desktop) or bottom bar (mobile); Home
 * and the physician phone view use the top bar only.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const ops = isOpsPath(pathname);
  const bottomNav = ops && !isActive(pathname, "/clinical-lead");
  return (
    <div className="flex min-h-dvh">
      {ops ? <Sidebar /> : null}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar ops={ops} />
        <main
          className={cn(
            "min-w-0 flex-1 px-4 pt-4 pb-12 min-[900px]:px-8 min-[900px]:pt-7",
            bottomNav && "pb-28 min-[900px]:pb-12",
          )}
        >
          <div className="mx-auto w-full max-w-[1440px]">
            {ops ? <MobileClockControls className="mb-4 min-[900px]:hidden" /> : null}
            {children}
          </div>
        </main>
      </div>
      {bottomNav ? <BottomNav /> : null}
    </div>
  );
}
