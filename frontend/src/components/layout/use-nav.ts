"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { analysisApi } from "@/lib/api/endpoints";
import { COORDINATOR_SECTIONS, type NavItem } from "@/lib/nav";

/** The coordinator section whose top has passed the upper third of the viewport. */
function useActiveSection(enabled: boolean): string | null {
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const line = window.innerHeight * 0.35;
      let current: string | null = null;
      for (const id of COORDINATOR_SECTIONS) {
        const top = document.getElementById(id)?.getBoundingClientRect().top;
        if (top !== undefined && top <= line) current = id;
      }
      setActive(current);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [enabled]);

  return enabled ? active : null;
}

/** Which nav item is current: by page, and on the coordinator page by section in view. */
export function useActiveNav(): NavItem["id"] | null {
  const pathname = usePathname();
  const onCoordinator = pathname === "/coordinator";
  const section = useActiveSection(onCoordinator);
  if (onCoordinator) {
    if (section === "network-detail") return "network";
    if (section === "intervention-board") return "interventions";
    return "command";
  }
  if (pathname.startsWith("/clinical-lead")) return "approvals";
  if (pathname.startsWith("/physician")) return "offers";
  return null;
}

export interface NavCount {
  count: number;
  tone: "critical" | "warning";
  label: string;
}

/**
 * Counts that need someone's attention, in the nav: critical (else warning) alerts on the
 * command center, pending approvals for the clinical lead. Read from the backend's metrics;
 * nothing is shown until it answers.
 */
export function useNavCounts(): Partial<Record<NavItem["id"], NavCount>> {
  const { config } = useSystemStatus();
  const key = config?.dataset_loaded
    ? `${config.data_version}|${config.simulation_time}|${config.workflow_version}`
    : null;
  const metrics = useKeyedResource(key, (signal) => analysisApi.metrics(signal));
  const severity = metrics.data?.alerts_by_severity;
  const critical = severity?.critical ?? 0;
  const warning = severity?.warning ?? 0;
  const pending = config?.pending_approvals ?? 0;

  const counts: Partial<Record<NavItem["id"], NavCount>> = {};
  if (critical) {
    counts.command = {
      count: critical,
      tone: "critical",
      label: `${critical} critical alert${critical === 1 ? "" : "s"}`,
    };
  } else if (warning) {
    counts.command = {
      count: warning,
      tone: "warning",
      label: `${warning} warning alert${warning === 1 ? "" : "s"}`,
    };
  }
  if (pending) {
    counts.approvals = {
      count: pending,
      tone: "warning",
      label: `${pending} pending approval${pending === 1 ? "" : "s"}`,
    };
  }
  return counts;
}

/**
 * Section anchors on the coordinator page scroll smoothly in place; from another page the
 * router navigates and scrolls to the hash itself.
 */
export function navigateInPage(
  event: React.MouseEvent<HTMLAnchorElement>,
  pathname: string,
  item: NavItem,
) {
  if (pathname !== "/coordinator" || !item.href.startsWith("/coordinator")) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
  event.preventDefault();
  if (item.section) {
    document.getElementById(item.section)?.scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  window.history.replaceState(null, "", item.href);
}
