"use client";

import { createContext, useContext } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource, type KeyedResource } from "@/hooks/use-keyed-resource";
import { stateApi } from "@/lib/api/endpoints";
import type { OperationalState } from "@/lib/api/types";

const OperationalStateContext = createContext<KeyedResource<OperationalState> | null>(null);

/**
 * One fetch of the backend's reconstructed state, shared by every coordinator section.
 * Refetches when the dataset version or the simulation time changes (both come from
 * /api/config, which the status provider polls), so injected events show up without
 * reloading the page.
 */
export function OperationalStateProvider({ children }: { children: React.ReactNode }) {
  const { config } = useSystemStatus();
  const key = config?.dataset_loaded ? `${config.data_version}|${config.simulation_time}` : null;
  const resource = useKeyedResource(key, (signal) => stateApi.state(signal));

  return <OperationalStateContext value={resource}>{children}</OperationalStateContext>;
}

export function useOperationalState(): KeyedResource<OperationalState> {
  const context = useContext(OperationalStateContext);
  if (!context) {
    throw new Error("useOperationalState must be used inside <OperationalStateProvider>");
  }
  return context;
}
