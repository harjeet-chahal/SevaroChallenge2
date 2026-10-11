import { apiRequest } from "./client";
import type {
  AlertList,
  AuditPage,
  DemoUserRole,
  ExpireResult,
  Intervention,
  InterventionCreate,
  InterventionImpact,
  InterventionPage,
  InterventionPreview,
  OfferPage,
  OfferRecipient,
  OfferResponseResult,
  PhysicianOfferView,
  ShiftOffer,
  ConsultationState,
  CoverageReport,
  DatasetImportReport,
  DatasetStatus,
  DemandReport,
  DispatchResult,
  EventIngestResult,
  EventPage,
  OperationalMetrics,
  OperationalState,
  OptimizationComparison,
  PhysicianState,
  ProposedAction,
  SampleDataset,
  SnapshotVerification,
  SimulationClock,
  StaffingResult,
  WhatIfResult,
} from "./types";

const IMPORT_TIMEOUT_MS = 60_000;

function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const datasetApi = {
  loadChallenge: () =>
    apiRequest<DatasetImportReport>("/api/datasets/challenge", {
      method: "POST",
      timeoutMs: IMPORT_TIMEOUT_MS,
    }),

  verify: () =>
    apiRequest<SnapshotVerification>("/api/datasets/verification", {
      timeoutMs: IMPORT_TIMEOUT_MS,
    }),

  status: (signal?: AbortSignal) => apiRequest<DatasetStatus>("/api/datasets/status", { signal }),

  samples: (signal?: AbortSignal) =>
    apiRequest<SampleDataset[]>("/api/datasets/samples", { signal }),

  loadSample: (name?: string) =>
    apiRequest<DatasetImportReport>(`/api/datasets/sample${query({ name })}`, {
      method: "POST",
      timeoutMs: IMPORT_TIMEOUT_MS,
    }),

  upload: (files: File[], referenceTime?: string) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    if (referenceTime) form.append("reference_time", referenceTime);
    return apiRequest<DatasetImportReport>("/api/datasets/import", {
      method: "POST",
      body: form,
      timeoutMs: IMPORT_TIMEOUT_MS,
    });
  },
};

export const simulationApi = {
  clock: (signal?: AbortSignal) => apiRequest<SimulationClock>("/api/simulation", { signal }),
  advance: (minutes: number) =>
    apiRequest<SimulationClock>("/api/simulation/advance", {
      method: "POST",
      body: { minutes },
    }),
  setTime: (time: string) =>
    apiRequest<SimulationClock>("/api/simulation/time", {
      method: "POST",
      body: { time },
    }),
  reset: () => apiRequest<SimulationClock>("/api/simulation/reset", { method: "POST" }),
};

export const stateApi = {
  state: (signal?: AbortSignal) => apiRequest<OperationalState>("/api/state", { signal }),
  physicians: (signal?: AbortSignal) => apiRequest<PhysicianState[]>("/api/physicians", { signal }),
  consultations: (signal?: AbortSignal) =>
    apiRequest<ConsultationState[]>("/api/consultations", { signal }),
};

export interface EventQuery {
  physician_id?: string;
  consult_id?: string;
  event_type?: string;
  visibility?: "all" | "visible" | "pending";
  dedupe?: "all" | "canonical" | "duplicates";
  order?: "ingested_desc" | "ingested_asc" | "event_time_desc" | "event_time_asc";
  limit?: number;
  offset?: number;
}

export const eventsApi = {
  list: (params: EventQuery, signal?: AbortSignal) =>
    apiRequest<EventPage>(`/api/events${query({ ...params })}`, { signal }),

  inject: (events: unknown) =>
    apiRequest<EventIngestResult>("/api/events", {
      method: "POST",
      body: events,
    }),

  appendCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return apiRequest<EventIngestResult>("/api/events/csv", {
      method: "POST",
      body: form,
      timeoutMs: IMPORT_TIMEOUT_MS,
    });
  },
};

export const analysisApi = {
  alerts: (signal?: AbortSignal) => apiRequest<AlertList>("/api/alerts", { signal }),
  coverage: (signal?: AbortSignal) => apiRequest<CoverageReport>("/api/coverage", { signal }),
  demand: (signal?: AbortSignal) => apiRequest<DemandReport>("/api/demand", { signal }),
  metrics: (signal?: AbortSignal) => apiRequest<OperationalMetrics>("/api/metrics", { signal }),
};

/** Phase 4 recommendations. Read-only: nothing here assigns, offers or changes staffing. */
export const optimizationApi = {
  assignments: (signal?: AbortSignal) =>
    apiRequest<DispatchResult>("/api/optimization/assignments", { signal }),
  splitShifts: (signal?: AbortSignal) =>
    apiRequest<StaffingResult>("/api/optimization/split-shifts", { signal }),
  comparison: (signal?: AbortSignal) =>
    apiRequest<OptimizationComparison>("/api/optimization/comparison", {
      signal,
    }),
  /** Projection only — the backend stores nothing. */
  simulate: (action: ProposedAction, signal?: AbortSignal) =>
    apiRequest<WhatIfResult>("/api/optimization/simulate", {
      method: "POST",
      body: { action },
      signal,
    }),
};

const WORKFLOW_TIMEOUT_MS = 30_000;

/**
 * Phase 5 workflow. Every call carries the simulated role (X-Demo-Role); the backend
 * enforces who may do what. This is a demo stand-in, not production authentication.
 */
export const workflowApi = {
  preview: (body: InterventionCreate, signal?: AbortSignal) =>
    apiRequest<InterventionPreview>("/api/interventions/preview", {
      method: "POST",
      body,
      role: "coordinator",
      signal,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  propose: (body: InterventionCreate) =>
    apiRequest<Intervention>("/api/interventions", {
      method: "POST",
      body,
      role: "coordinator",
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  list: (role: DemoUserRole, signal?: AbortSignal) =>
    apiRequest<InterventionPage>("/api/interventions", { role, signal }),
  get: (id: string, role: DemoUserRole, signal?: AbortSignal) =>
    apiRequest<Intervention>(`/api/interventions/${encodeURIComponent(id)}`, { role, signal }),
  decide: (id: string, decision: "approve" | "reject", note: string | null, version: number) =>
    apiRequest<Intervention>(`/api/interventions/${encodeURIComponent(id)}/decision`, {
      method: "POST",
      body: { decision, note: note || null, expected_version: version },
      role: "clinical_lead",
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  sendOffers: (id: string, role: DemoUserRole) =>
    apiRequest<Intervention>(`/api/interventions/${encodeURIComponent(id)}/send-offers`, {
      method: "POST",
      role,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  apply: (id: string) =>
    apiRequest<Intervention>(`/api/interventions/${encodeURIComponent(id)}/apply`, {
      method: "POST",
      role: "coordinator",
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  resolve: (id: string, role: DemoUserRole, note: string | null) =>
    apiRequest<Intervention>(`/api/interventions/${encodeURIComponent(id)}/resolve`, {
      method: "POST",
      body: { note: note || null },
      role,
    }),
  cancel: (id: string, role: DemoUserRole, reason: string | null) =>
    apiRequest<Intervention>(`/api/interventions/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      body: { reason: reason || null },
      role,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  impact: (id: string, role: DemoUserRole, signal?: AbortSignal) =>
    apiRequest<InterventionImpact>(`/api/interventions/${encodeURIComponent(id)}/impact`, {
      role,
      signal,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  audit: (
    role: DemoUserRole,
    params: { intervention_id?: string; limit?: number },
    signal?: AbortSignal,
  ) => apiRequest<AuditPage>(`/api/audit${query({ ...params })}`, { role, signal }),
};

export const offersApi = {
  list: (role: DemoUserRole, signal?: AbortSignal) =>
    apiRequest<OfferPage>("/api/offers", { role, signal }),
  /** Only the simulated physician's own offers; no patient information. */
  mine: (physicianId: string, signal?: AbortSignal) =>
    apiRequest<PhysicianOfferView[]>("/api/offers/mine", {
      role: "physician",
      actorId: physicianId,
      signal,
    }),
  recipients: (signal?: AbortSignal) =>
    apiRequest<OfferRecipient[]>("/api/offers/recipients", { signal }),
  respond: (offerId: string, physicianId: string, response: "accept" | "decline") =>
    apiRequest<OfferResponseResult>(`/api/offers/${encodeURIComponent(offerId)}/respond`, {
      method: "POST",
      body: { response },
      role: "physician",
      actorId: physicianId,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  activate: (offerId: string, role: "physician" | "coordinator", physicianId?: string) =>
    apiRequest<ShiftOffer>(`/api/offers/${encodeURIComponent(offerId)}/activate`, {
      method: "POST",
      role,
      actorId: physicianId,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  withdraw: (offerId: string, role: DemoUserRole, reason: string | null) =>
    apiRequest<ShiftOffer>(`/api/offers/${encodeURIComponent(offerId)}/withdraw`, {
      method: "POST",
      body: { reason: reason || null },
      role,
      timeoutMs: WORKFLOW_TIMEOUT_MS,
    }),
  expireDue: (role: DemoUserRole) =>
    apiRequest<ExpireResult>("/api/offers/expire-due", { method: "POST", role }),
};
