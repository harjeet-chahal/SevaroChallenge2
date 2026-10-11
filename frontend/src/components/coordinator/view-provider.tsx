"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import type { Severity } from "@/lib/api/types";

import { SECTION_IDS } from "./section-ids";

export type DetailTab = "coverage" | "consults" | "physicians" | "optimizer" | "events";
export type AlertFilter = Severity | "all";
export type ConsultFilter = "open" | "unassigned" | "all";

interface CoordinatorViewValue {
  alertFilter: AlertFilter;
  setAlertFilter: (filter: AlertFilter) => void;
  detailTab: DetailTab;
  setDetailTab: (tab: DetailTab) => void;
  consultFilter: ConsultFilter;
  setConsultFilter: (filter: ConsultFilter) => void;
  /** Jump from a headline number to the section that explains it. */
  focus: (section: keyof typeof SECTION_IDS, tab?: DetailTab) => void;
}

const CoordinatorViewContext = createContext<CoordinatorViewValue | null>(null);

export function scrollToSection(id: string) {
  requestAnimationFrame(() =>
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }),
  );
}

/**
 * A deep link like /coordinator#intervention-board scrolls once on navigation, but panels
 * above the anchor grow as their data arrives. Keep the anchor in place while the page
 * settles, and stop as soon as the user scrolls on their own.
 */
function useSettledHashAnchor() {
  useEffect(() => {
    const id = window.location.hash.slice(1);
    const ids: string[] = Object.values(SECTION_IDS);
    if (!ids.includes(id)) return;
    const target = document.getElementById(id);
    if (!target) return;
    const align = () => target.scrollIntoView({ block: "start" });
    const observer = new ResizeObserver(align);
    observer.observe(document.body);
    const stop = () => {
      observer.disconnect();
      window.removeEventListener("wheel", stop);
      window.removeEventListener("touchmove", stop);
      window.removeEventListener("keydown", stop);
    };
    window.addEventListener("wheel", stop, { passive: true });
    window.addEventListener("touchmove", stop, { passive: true });
    window.addEventListener("keydown", stop);
    const timer = window.setTimeout(stop, 4000);
    return () => {
      window.clearTimeout(timer);
      stop();
    };
  }, []);
}

/**
 * Presentation state shared across the coordinator page: filters and the active detail
 * tab, so the summary strip can drill into the section behind each number.
 */
export function CoordinatorViewProvider({ children }: { children: React.ReactNode }) {
  const [alertFilter, setAlertFilter] = useState<AlertFilter>("all");
  const [detailTab, setDetailTab] = useState<DetailTab>("coverage");
  const [consultFilter, setConsultFilter] = useState<ConsultFilter>("open");
  useSettledHashAnchor();

  const focus = useCallback((section: keyof typeof SECTION_IDS, tab?: DetailTab) => {
    if (tab) setDetailTab(tab);
    scrollToSection(SECTION_IDS[section]);
  }, []);

  return (
    <CoordinatorViewContext
      value={{
        alertFilter,
        setAlertFilter,
        detailTab,
        setDetailTab,
        consultFilter,
        setConsultFilter,
        focus,
      }}
    >
      {children}
    </CoordinatorViewContext>
  );
}

export function useCoordinatorView(): CoordinatorViewValue {
  const context = useContext(CoordinatorViewContext);
  if (!context) throw new Error("useCoordinatorView must be used inside <CoordinatorViewProvider>");
  return context;
}
