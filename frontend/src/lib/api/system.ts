import { apiRequest } from "./client";
import type { ConfigResponse, HealthResponse } from "./types";

export const systemApi = {
  /** Returns the body for both 200 (ok) and 503 (degraded) responses. */
  health: (signal?: AbortSignal) =>
    apiRequest<HealthResponse>("/api/health", {
      signal,
      acceptStatuses: [503],
    }),

  config: (signal?: AbortSignal) => apiRequest<ConfigResponse>("/api/config", { signal }),
};
