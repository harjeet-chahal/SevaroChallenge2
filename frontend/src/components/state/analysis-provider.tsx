"use client";

import { createContext, useContext, useState } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource, type KeyedResource } from "@/hooks/use-keyed-resource";
import { analysisApi } from "@/lib/api/endpoints";
import type {
  Alert,
  AlertList,
  CoverageReport,
  DemandReport,
  OperationalMetrics,
} from "@/lib/api/types";

interface AnalysisContextValue {
  alerts: KeyedResource<AlertList>;
  coverage: KeyedResource<CoverageReport>;
  demand: KeyedResource<DemandReport>;
  metrics: KeyedResource<OperationalMetrics>;
  /** The alert shown in the details panel: the user's pick, else the top-priority alert. */
  selectedAlert: Alert | null;
  selectAlert: (alertId: string) => void;
  selectedHospitalId: string | null;
  selectHospital: (hospitalId: string) => void;
}

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

/**
 * Backend-computed alerts, coverage forecasts, demand and metrics. Refetched whenever
 * the dataset version or the simulation time changes — the same mechanism as state.
 */
export function AnalysisProvider({ children }: { children: React.ReactNode }) {
  const { config } = useSystemStatus();
  const key = config?.dataset_loaded ? `${config.data_version}|${config.simulation_time}` : null;
  const alerts = useKeyedResource(key, (signal) => analysisApi.alerts(signal));
  const coverage = useKeyedResource(key, (signal) => analysisApi.coverage(signal));
  const demand = useKeyedResource(key, (signal) => analysisApi.demand(signal));
  const metrics = useKeyedResource(key, (signal) => analysisApi.metrics(signal));
  const [pickedAlert, selectAlert] = useState<string | null>(null);
  const [pickedHospital, selectHospital] = useState<string | null>(null);

  const list = alerts.data?.alerts ?? [];
  // A picked alert that has since resolved falls back to the current top alert.
  const selectedAlert = list.find((a) => a.alert_id === pickedAlert) ?? list[0] ?? null;

  const hospitals = coverage.data?.hospitals ?? [];
  const firstAtRisk = [...hospitals]
    .filter((h) => h.metrics.first_shortfall_at)
    .sort((a, b) => a.metrics.first_shortfall_at!.localeCompare(b.metrics.first_shortfall_at!))[0];
  const selectedHospitalId =
    hospitals.find((h) => h.hospital_id === pickedHospital)?.hospital_id ??
    firstAtRisk?.hospital_id ??
    hospitals[0]?.hospital_id ??
    null;

  return (
    <AnalysisContext
      value={{
        alerts,
        coverage,
        demand,
        metrics,
        selectedAlert,
        selectAlert,
        selectedHospitalId,
        selectHospital,
      }}
    >
      {children}
    </AnalysisContext>
  );
}

export function useAnalysis(): AnalysisContextValue {
  const context = useContext(AnalysisContext);
  if (!context) throw new Error("useAnalysis must be used inside <AnalysisProvider>");
  return context;
}
