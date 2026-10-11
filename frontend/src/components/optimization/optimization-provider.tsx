"use client";

import { createContext, useContext, useState } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource, type KeyedResource } from "@/hooks/use-keyed-resource";
import { optimizationApi } from "@/lib/api/endpoints";
import type {
  DispatchResult,
  OptimizationComparison,
  SplitShiftAction,
  StaffingResult,
} from "@/lib/api/types";

export type RecommendationTab = "routing" | "staffing" | "comparison" | "whatif";

interface OptimizationContextValue {
  dispatch: KeyedResource<DispatchResult>;
  staffing: KeyedResource<StaffingResult>;
  comparison: KeyedResource<OptimizationComparison>;
  tab: RecommendationTab;
  setTab: (tab: RecommendationTab) => void;
  /** The split shift to preview in the What-if tab (user's pick, else the top proposal). */
  previewAction: SplitShiftAction | null;
  preview: (action: SplitShiftAction) => void;
}

const OptimizationContext = createContext<OptimizationContextValue | null>(null);

/**
 * Backend optimizer recommendations, refetched whenever the dataset version, the workflow
 * version (offers sent, declined, accepted change who can be asked) or the simulation time
 * changes. Read-only: nothing here assigns, offers or changes staffing.
 */
export function OptimizationProvider({ children }: { children: React.ReactNode }) {
  const { config } = useSystemStatus();
  const key = config?.dataset_loaded
    ? `${config.workflow_version}|${config.data_version}|${config.simulation_time}`
    : null;
  const dispatch = useKeyedResource(key, (signal) => optimizationApi.assignments(signal));
  const staffing = useKeyedResource(key, (signal) => optimizationApi.splitShifts(signal));
  const comparison = useKeyedResource(key, (signal) => optimizationApi.comparison(signal));
  const [tab, setTab] = useState<RecommendationTab>("routing");
  const [picked, setPicked] = useState<{
    key: string | null;
    action: SplitShiftAction;
  } | null>(null);

  const top = staffing.data?.recommendations[0];
  const fallback: SplitShiftAction | null = top
    ? {
        kind: "split_shift",
        physician_id: top.physician_id,
        start: top.offer_start,
        duration_minutes: top.offer_minutes,
      }
    : null;
  // A pick made at an earlier data version / time is dropped: it may no longer be valid.
  const previewAction = picked && picked.key === key ? picked.action : fallback;

  return (
    <OptimizationContext
      value={{
        dispatch,
        staffing,
        comparison,
        tab,
        setTab,
        previewAction,
        preview: (action) => {
          setPicked({ key, action });
          setTab("whatif");
        },
      }}
    >
      {children}
    </OptimizationContext>
  );
}

/** The optimizer results when rendered inside the coordinator view, else null. */
export function useOptionalOptimization(): OptimizationContextValue | null {
  return useContext(OptimizationContext);
}

export function useOptimization(): OptimizationContextValue {
  const context = useContext(OptimizationContext);
  if (!context) throw new Error("useOptimization must be used inside <OptimizationProvider>");
  return context;
}
