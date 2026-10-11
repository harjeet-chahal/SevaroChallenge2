"use client";

import { useSystemStatus } from "@/components/status/system-status-provider";

import { DatasetPanel } from "./dataset-panel";

/**
 * Until a dataset is loaded, loading one is the only useful thing to do, so the controls
 * sit inline. Afterwards they live in the toolbar's data drawer.
 */
export function DatasetGate() {
  const { config, connection } = useSystemStatus();
  if (connection === "checking" || config?.dataset_loaded) return null;
  return <DatasetPanel />;
}
