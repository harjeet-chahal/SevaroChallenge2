"use client";

import { useSystemStatus } from "@/components/status/system-status-provider";

import { useKeyedResource, type KeyedResource } from "./use-keyed-resource";

/**
 * Fetch a backend resource and refetch whenever the dataset version, the workflow version
 * or the simulation time changes (the same counters the live SSE stream pushes). ``extra``
 * adds caller parameters to the key. Returns no data while no dataset is loaded.
 */
export function useLiveResource<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  extra = "",
): KeyedResource<T> {
  const { config } = useSystemStatus();
  const key = config?.dataset_loaded
    ? `${config.data_version}|${config.workflow_version}|${config.simulation_time}|${extra}`
    : null;
  return useKeyedResource(key, fetcher);
}
