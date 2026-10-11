"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import { API_BASE_LABEL, API_BASE_URL, ApiError, NetworkError } from "@/lib/api/client";
import { systemApi } from "@/lib/api/system";
import type { ConfigResponse, HealthResponse, WorkflowSummary } from "@/lib/api/types";

export type Connection = "checking" | "online" | "degraded" | "offline";

/**
 * What a data section can honestly show right now. Derived only from real backend
 * responses; the frontend never assumes data exists.
 */
export type DataAvailability =
  | "checking"
  | "offline"
  | "degraded"
  | "no-dataset"
  | "awaiting-feature";

interface StatusSnapshot {
  connection: Connection;
  health: HealthResponse | null;
  config: ConfigResponse | null;
  error: string | null;
  lastCheckedAt: Date | null;
}

export interface SystemStatus extends StatusSnapshot {
  apiBaseUrl: string;
  availability: DataAvailability;
  /** Server-Sent Events stream (/api/live) state; polling remains the fallback. */
  live: "connecting" | "connected" | "unavailable";
  refresh: () => void;
}

const DEFAULT_POLL_MS = Number(process.env.NEXT_PUBLIC_STATUS_POLL_MS) || 15000;

const SystemStatusContext = createContext<SystemStatus | null>(null);

function describeError(error: unknown): string {
  if (error instanceof NetworkError || error instanceof ApiError) return error.message;
  return "Unexpected error while contacting the API";
}

function deriveAvailability(snapshot: StatusSnapshot): DataAvailability {
  if (snapshot.connection === "checking") return "checking";
  if (snapshot.connection === "offline") return "offline";
  if (snapshot.connection === "degraded" || !snapshot.config) return "degraded";
  // Phase 1 has no operational data endpoints yet, so even with a dataset loaded
  // the sections have nothing real to render.
  return snapshot.config.dataset_loaded ? "awaiting-feature" : "no-dataset";
}

async function fetchStatus(signal: AbortSignal): Promise<StatusSnapshot> {
  let health: HealthResponse;
  try {
    health = await systemApi.health(signal);
  } catch (error) {
    if (signal.aborted) throw error;
    return {
      connection: error instanceof NetworkError ? "offline" : "degraded",
      health: null,
      config: null,
      error: describeError(error),
      lastCheckedAt: new Date(),
    };
  }

  try {
    const config = await systemApi.config(signal);
    return {
      connection: health.status === "ok" ? "online" : "degraded",
      health,
      config,
      error: health.database.detail,
      lastCheckedAt: new Date(),
    };
  } catch (error) {
    if (signal.aborted) throw error;
    return {
      connection: "degraded",
      health,
      config: null,
      error: describeError(error),
      lastCheckedAt: new Date(),
    };
  }
}

export function SystemStatusProvider({
  children,
  pollIntervalMs = DEFAULT_POLL_MS,
}: {
  children: React.ReactNode;
  pollIntervalMs?: number;
}) {
  const [snapshot, setSnapshot] = useState<StatusSnapshot>({
    connection: "checking",
    health: null,
    config: null,
    error: null,
    lastCheckedAt: null,
  });
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    const check = async () => {
      try {
        const next = await fetchStatus(controller.signal);
        if (!controller.signal.aborted) setSnapshot(next);
      } catch {
        // Aborted on unmount or refresh; a newer check replaces this one.
      }
    };

    void check();
    const interval = setInterval(check, pollIntervalMs);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, [pollIntervalMs, refreshToken]);

  const refresh = useCallback(() => setRefreshToken((token) => token + 1), []);

  // Live updates: the backend pushes its version counters whenever data, workflow state or
  // the simulation clock change, and every view refetches through its keyed resources. A
  // change seen here triggers an immediate config refresh (no waiting for the poll).
  const [live, setLive] = useState<SystemStatus["live"]>("connecting");
  const lastVersions = useRef<string | null>(null);
  useEffect(() => {
    if (typeof EventSource === "undefined") return; // polling still keeps views fresh
    const source = new EventSource(`${API_BASE_URL}/api/live`);
    // The server ends each stream after ~20 s on purpose and the browser reconnects on its
    // own (readyState CONNECTING), firing `error` first: that is normal. Live updates are
    // only unavailable once the stream is closed for good, or after repeated failures
    // without a single message in between.
    let failures = 0;
    source.onopen = () => setLive("connected");
    source.onerror = () => {
      failures += 1;
      if (source.readyState === EventSource.CLOSED || failures >= 3) setLive("unavailable");
    };
    source.addEventListener("versions", (event) => {
      failures = 0;
      setLive("connected");
      const data = JSON.parse((event as MessageEvent<string>).data) as WorkflowSummary;
      const signature = [
        data.data_version,
        data.workflow_version,
        data.simulation_time,
        data.pending_approvals,
      ].join("|");
      if (lastVersions.current !== null && lastVersions.current !== signature) {
        setRefreshToken((token) => token + 1);
      }
      lastVersions.current = signature;
    });
    return () => source.close();
  }, []);

  const value: SystemStatus = {
    ...snapshot,
    apiBaseUrl: API_BASE_LABEL,
    availability: deriveAvailability(snapshot),
    live,
    refresh,
  };

  return <SystemStatusContext value={value}>{children}</SystemStatusContext>;
}

export function useSystemStatus(): SystemStatus {
  const context = useContext(SystemStatusContext);
  if (!context) {
    throw new Error("useSystemStatus must be used inside <SystemStatusProvider>");
  }
  return context;
}
