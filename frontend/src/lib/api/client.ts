import type { ApiErrorBody, UserRole } from "./types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

/** An empty base URL means same-origin: a reverse proxy serves /api next to the UI (Docker). */
export const API_BASE_LABEL = API_BASE_URL || "this site's /api";

const DEFAULT_TIMEOUT_MS = 5000;

/** The backend answered with a non-success status and a standard error envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }
}

/** The backend could not be reached at all (down, wrong URL, CORS, or timed out). */
export class NetworkError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "NetworkError";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON-serialisable value, or FormData for file uploads. */
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Sent as X-Demo-Role so the backend can enforce role permissions server-side. */
  role?: UserRole;
  /** Sent as X-Demo-Actor-Id: the simulated person (a physician's ID for the phone view). */
  actorId?: string;
  /** Non-2xx statuses whose body should still be returned as data (e.g. 503 health). */
  acceptStatuses?: number[];
}

function isErrorEnvelope(value: unknown): value is { error: ApiErrorBody } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return typeof error === "object" && error !== null && "code" in error && "message" in error;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal, timeoutMs = DEFAULT_TIMEOUT_MS, role, actorId } = options;

  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (role) headers["X-Demo-Role"] = role;
  if (actorId) headers["X-Demo-Actor-Id"] = actorId;

  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const combinedSignal = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal: combinedSignal,
      cache: "no-store",
    });
  } catch (cause) {
    // Caller-initiated cancellation is not a connectivity problem; let it propagate.
    if (signal?.aborted) throw cause;
    const reason = timeoutSignal.aborted ? `timed out after ${timeoutMs} ms` : "network error";
    throw new NetworkError(`Could not reach API at ${API_BASE_LABEL} (${reason})`, { cause });
  }

  const payload: unknown = await response.json().catch(() => null);

  if (response.ok || options.acceptStatuses?.includes(response.status)) {
    return payload as T;
  }
  if (isErrorEnvelope(payload)) {
    throw new ApiError(response.status, payload.error);
  }
  throw new ApiError(response.status, {
    code: "http_error",
    message: `Request failed with status ${response.status}`,
  });
}
