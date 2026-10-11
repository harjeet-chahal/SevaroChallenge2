/**
 * NEUROGRID intelligence API: types mirror backend/app/schemas/intelligence.py.
 * Everything here is computed by the backend; the frontend only renders it.
 */
import { apiRequest } from "./client";
import type { DemoUserRole, EventIngestResult, Intervention, InterventionCreate, Severity } from "./types";

export type AvailabilityClass =
  | "OFF_SHIFT"
  | "AVAILABLE"
  | "BUSY_CALL"
  | "BUSY_VIDEO"
  | "PROBABLY_BUSY_EXTERNAL"
  | "INTERRUPTIBLE_MEETING"
  | "UNAVAILABLE"
  | "UNCERTAIN"
  | "UNKNOWN";
export type EvidenceConfidence = "CONFIRMED" | "LIKELY" | "UNCERTAIN" | "STALE";

export interface PhysicianAvailabilityView {
  physician_id: string;
  display_name: string;
  on_shift: boolean | null;
  availability_class: AvailabilityClass;
  confidence: EvidenceConfidence;
  decision_rule: string;
  auto_routable: boolean;
  coordinator_reachable: boolean;
  needs_confirmation: boolean;
  routing_exclusions: string[];
  rationale: string[];
  signal_times: Record<string, string | null>;
  evidence_event_ids: string[];
  flags: string[];
  open_consult_ids: string[];
  unfinished_note_consult_ids: string[];
}
export interface AvailabilityReport {
  as_of: string;
  data_version: number;
  physicians: PhysicianAvailabilityView[];
  counts_by_class: Record<string, number>;
  rules: string[];
}

export type RootCause =
  | "TOTAL_CAPACITY_SHORTAGE"
  | "CREDENTIALING_BOTTLENECK"
  | "SHIFT_COLLISION"
  | "ROUTING_ELIGIBILITY_FAILURE"
  | "WORKLOAD_CONCENTRATION"
  | "AVAILABILITY_UNCERTAINTY"
  | "DOCUMENTATION_HANDOFF_RISK"
  | "MULTI_FACTOR";

export interface ProblemGroup {
  fingerprint: string;
  kind: "hospital_staffing" | "consult_delay" | "physician_workload" | "physician_signal" | "demand_surge";
  tier: number;
  priority: number;
  severity: Severity;
  title: string;
  summary: string;
  hospital_id: string | null;
  physician_id: string | null;
  member_alert_ids: string[];
  critical_alert_ids: string[];
  root_cause: RootCause | null;
  recommended_action: string;
  factors: Record<string, number>;
  explanation: string;
}
export interface ProblemReport {
  as_of: string;
  data_version: number;
  groups: ProblemGroup[];
  alerts_total: number;
  tier_policy: string[];
}

export interface TimeMachineHospital {
  hospital_id: string;
  required: number | null;
  confirmed: number;
  uncertain: number;
  deficit: number | null;
  spike: boolean | null;
}
export interface TimeMachineFrame {
  at: string;
  offset_minutes: number;
  kind: "now" | "step" | "boundary" | "horizon_end";
  observed: boolean;
  network_required: number;
  network_deficit: number;
  hospitals_short: number;
  hospitals: TimeMachineHospital[];
  labels: string[];
}
export interface ShiftLaneSegment {
  start: string;
  end: string | null;
  kind: "scheduled" | "assumed" | "rescue_pending" | "rescue_active";
  label: string;
}
export interface ShiftLane {
  physician_id: string;
  display_name: string;
  availability_class: AvailabilityClass;
  credentialed_hospital_ids: string[];
  segments: ShiftLaneSegment[];
}
export interface DemandBand {
  hospital_id: string;
  at: string;
  expected_arrivals: number;
  p10_trailing_hour: number;
  p50_trailing_hour: number;
  p90_trailing_hour: number;
  p90_threshold: number | null;
  share_runs_above_threshold: number;
}
export interface TimeMachineReport {
  as_of: string;
  data_version: number;
  horizon_minutes: number;
  step_minutes: number;
  frames: TimeMachineFrame[];
  lanes: ShiftLane[];
  demand: DemandBand[];
  stochastic: Record<string, unknown>;
  freshness: Record<string, unknown>;
  hospitals: { hospital_id: string; name: string; timezone: string }[];
  notes: string[];
}

export interface LeadTime {
  approval_minutes: number;
  response_minutes_expected: number;
  response_minutes_conservative: number;
  online_minutes: number;
  expected_total_minutes: number;
  conservative_total_minutes: number;
  online_time_assumed: boolean;
}
export interface RescueTiming {
  physician_id: string;
  display_name: string;
  lead: LeadTime;
  earliest_valid_start: string | null;
  activation_expected_at: string | null;
  latest_initiation_expected: string | null;
  latest_initiation_conservative: string | null;
  covers_shortfall_start: boolean;
  eligible_at_start: boolean;
  sendable_now: boolean;
  eligibility_crossing: string | null;
  blocking: string[];
}
export type LsmPhase = "green" | "amber" | "red" | "missed" | "no_candidate";
export interface LastSafeMoment {
  shortfall_id: string;
  hospital_id: string;
  hospital_name: string;
  timezone: string;
  shortfall_at: string;
  shortfall_ends_at: string | null;
  minutes_until_shortfall: number;
  deficit_physician_minutes: number;
  worst_deficit: number;
  phase: LsmPhase;
  latest_initiation_at: string | null;
  remaining_minutes: number | null;
  best_physician_id: string | null;
  candidates: RescueTiming[];
  mitigation: string[];
  uncertainty: string[];
  explanation: string;
}
export interface LastSafeMomentReport {
  as_of: string;
  data_version: number;
  planning_horizon_minutes: number;
  items: LastSafeMoment[];
  earliest_deadline_at: string | null;
  assumptions: string[];
}

export interface GraphNode {
  id: string;
  kind: "hospital" | "physician";
  entity_id: string;
  label: string;
  status: string;
  risk: "critical" | "warning" | "ok" | "info";
  attributes: Record<string, unknown>;
}
export interface GraphEdge {
  id: string;
  physician_id: string;
  hospital_id: string;
  operational:
    | "routable_now"
    | "counted_busy"
    | "counted_unverified"
    | "joins_later"
    | "off_shift"
    | "unavailable"
    | "outside_scope";
  critical_dependency: boolean;
}
export interface HospitalImpact {
  hospital_id: string;
  hospital_name: string;
  added_deficit_physician_minutes: number;
  first_shortfall_before: string | null;
  first_shortfall_after: string | null;
  newly_uncovered: boolean;
}
export interface PhysicianCriticality {
  physician_id: string;
  display_name: string;
  on_shift: boolean | null;
  availability_class: AvailabilityClass;
  shift_end: string | null;
  credentialed_hospital_count: number;
  relevant: boolean;
  added_deficit_physician_minutes: number;
  hospitals_affected: HospitalImpact[];
  newly_uncovered_hospital_ids: string[];
  sole_coverage_hospital_ids: string[];
  criticality_score: number;
  criticality_factors: Record<string, number>;
  rank: number;
  explanation: string;
}
export interface HospitalResilience {
  hospital_id: string;
  hospital_name: string;
  timezone: string;
  credentialed_total: number;
  required_now: number | null;
  counted_now: number;
  routable_now: number;
  spare_now: number | null;
  min_spare_in_horizon: number | null;
  shortfall_minutes: number;
  fragile_minutes: number;
  deficit_physician_minutes: number;
  single_point_dependencies: string[];
  status: "short" | "fragile" | "resilient" | "no_requirement";
  explanation: string;
}
export interface AllocationCheck {
  at: string;
  label: string;
  required_total: number;
  pool_covered: number;
  exclusive_covered: number;
  exclusive_shortfall: number;
  unmatched_hospital_ids: string[];
  assignment: Record<string, string[]>;
}
export interface MultiFailureResult {
  scenario: string;
  label: string;
  removed_physician_ids: string[];
  added_deficit_physician_minutes: number;
  hospitals_newly_short: string[];
  hospitals_affected: HospitalImpact[];
  explanation: string;
}
export interface FragilityReport {
  as_of: string;
  data_version: number;
  horizon_minutes: number;
  baseline_deficit_physician_minutes: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  physicians: PhysicianCriticality[];
  hospitals: HospitalResilience[];
  allocation: AllocationCheck[];
  multi_failure: MultiFailureResult[];
  graph_metrics: Record<string, unknown>;
  score_weights: Record<string, number>;
  method: string[];
  assumptions: string[];
}

export interface GenomeFactor {
  cause: RootCause;
  weight: number;
  evidence: string[];
}
export interface GenomeDiagnosis {
  diagnosis_id: string;
  hospital_id: string;
  hospital_name: string;
  problem: "coverage_gap_now" | "coverage_gap_projected" | "unroutable_consults";
  problem_at: string;
  severity: Severity;
  primary_cause: RootCause;
  factors: GenomeFactor[];
  counts: Record<string, number>;
  excluded_by_reason: Record<string, number>;
  limiting_constraint: string;
  recommended_intervention: string;
  explanation: string;
  related_alert_ids: string[];
}
export interface StrategicSuggestion {
  kind: string;
  title: string;
  detail: string;
  basis: string[];
  label: string;
}
export interface GenomeReport {
  as_of: string;
  data_version: number;
  horizon_minutes: number;
  diagnoses: GenomeDiagnosis[];
  strategic: StrategicSuggestion[];
  method: string[];
}

export interface ScarcityHospital {
  hospital_id: string;
  hospital_name: string;
  first_shortfall_at: string | null;
  deficit_physician_minutes: number;
  urgency: "now" | "within_90" | "planning_window";
  alternative_candidate_ids: string[];
  sole_candidate: boolean;
  reduction_if_assigned: number;
}
export interface ScarcityEntry {
  physician_id: string;
  display_name: string;
  eligible: boolean;
  failed_rules: string[];
  hospitals: ScarcityHospital[];
  dependent_hospital_count: number;
  sole_candidate_hospital_count: number;
  minutes_to_come_online: number | null;
  earliest_valid_start: string | null;
  max_offer_minutes: number | null;
  scarcity_score: number;
  recommendation: "allocate" | "preserve" | "allocate_if_needed" | "not_eligible";
  opportunity_cost: string;
  explanation: string;
}
export interface ScarcityReport {
  as_of: string;
  data_version: number;
  planning_horizon_minutes: number;
  gap_hospital_ids: string[];
  entries: ScarcityEntry[];
  uncovered_hospital_ids: string[];
  no_feasible_candidate: boolean;
  escalation_recommended: boolean;
  policy: string[];
}

export interface DebtSample {
  at: string;
  required: number | null;
  counted: number;
  deficit: number | null;
  kind: "historical" | "projected";
}
export interface HospitalDebt {
  hospital_id: string;
  hospital_name: string;
  historical_debt_physician_minutes: number;
  projected_debt_physician_minutes: number;
  projected_debt_if_uncertain_excluded: number;
  fragile_minutes_projected: number;
  samples: DebtSample[];
}
export interface CoverageDebtReport {
  as_of: string;
  data_version: number;
  lookback_minutes: number;
  horizon_minutes: number;
  step_minutes: number;
  network_historical: number;
  network_projected: number;
  network_projected_if_uncertain_excluded: number;
  network_fragile_minutes: number;
  hospitals: HospitalDebt[];
  method: string[];
}

export interface HandoffConsult {
  consult_id: string;
  hospital_id: string | null;
  stage: string;
  consult_type: string | null;
  seconds_in_stage: number;
  unfinished_note: boolean;
}
export interface HandoffTransition {
  at: string;
  kind: "departing" | "arriving";
  physician_id: string;
  display_name: string;
  certainty: "scheduled" | "assumed" | "rescue_shift";
  open_consults: HandoffConsult[];
  unfinished_notes: number;
  coverage_changes: {
    hospital_id: string;
    hospital_name: string;
    counted_before: number;
    counted_after: number;
    required_after: number | null;
    deficit_after: number | null;
  }[];
  risk: "critical" | "warning" | "ok";
  notes: string[];
}
export interface HandoffReport {
  as_of: string;
  data_version: number;
  horizon_minutes: number;
  transitions: HandoffTransition[];
  pending_routing_failures: Record<string, unknown>[];
  pending_rescues: Record<string, unknown>[];
  deadlines: {
    consult_id: string;
    hospital_id: string | null;
    rule_code: string;
    stage: string;
    severity_now: Severity;
    critical_at: string | null;
    minutes_to_critical: number | null;
  }[];
  notes: string[];
}

export interface OptionOutcome {
  network_deficit_before: number;
  network_deficit_after: number;
  target_deficit_before: number;
  target_deficit_after: number;
  resolved_hospital_ids: string[];
  residual_hospital_ids: string[];
  new_shortfall_hospital_ids: string[];
  single_points_before: number;
  single_points_after: number;
  activation_at: string | null;
  activation_delay_minutes: number | null;
  per_hospital: {
    hospital_id: string;
    hospital_name: string;
    deficit_before: number;
    deficit_after: number;
    first_shortfall_before: string | null;
    first_shortfall_after: string | null;
    target: boolean;
  }[];
}
export interface RescueOption {
  option_id: string;
  kind: "do_nothing" | "escalation" | "reassignment" | "split_shift" | "shift_extension" | "combination";
  label: string;
  feasible: boolean;
  simulation_only: boolean;
  requires_approval: boolean;
  physician_ids: string[];
  hospital_ids: string[];
  start_at: string | null;
  end_at: string | null;
  blocking_reasons: string[];
  outcome: OptionOutcome | null;
  workload: Record<string, unknown> | null;
  lexicographic_key: number[];
  rank: number | null;
  recommended: boolean;
  why: string[];
  uncertainty: string[];
  proposal: Record<string, unknown> | null;
}
export interface RescueSimulation {
  as_of: string;
  data_version: number;
  horizon_minutes: number;
  target_hospital_ids: string[];
  target_label: string;
  options: RescueOption[];
  objective: string[];
  label: string;
}

export interface LoadGuardianReport {
  as_of: string;
  data_version: number;
  available: boolean;
  physician_id: string | null;
  display_name: string | null;
  unrestricted: Record<string, unknown> | null;
  protected: Record<string, unknown> | null;
  workload_limit: number | null;
  scope_hospital_ids: string[];
  excluded_hospital_ids: string[];
  forgone_coverage: Record<string, unknown>[];
  release_conditions: string[];
  conclusion: string;
  label: string;
}

export interface ChaosScenarioInfo {
  scenario_id: string;
  title: string;
  category: "state" | "workflow" | "ingestion";
  description: string;
  injects: string;
}
export interface ChaosAssertion {
  name: string;
  passed: boolean;
  expected: string;
  actual: string;
}
export interface ChaosDelta {
  metric: string;
  before: unknown;
  after: unknown;
}
export interface ChaosResult {
  run_id: string;
  scenario_id: string;
  title: string;
  branch: string;
  started_at: string;
  as_of: string;
  target: Record<string, unknown>;
  injected: string[];
  deltas: ChaosDelta[];
  alerts_new: string[];
  alerts_resolved: string[];
  assertions: ChaosAssertion[];
  passed: boolean;
  baseline_unchanged: boolean;
  duration_ms: number;
  notes: string[];
}

export interface ImportPreview {
  filename: string;
  valid: boolean;
  received: number;
  accepted: number;
  duplicates: number;
  conflicting_duplicates: number;
  rejected: number;
  unknown_event_types: Record<string, number>;
  outcomes: Record<string, unknown>[];
  errors: Record<string, unknown>[];
  clock_before: string;
  clock_after: string;
  deltas: ChaosDelta[];
  alerts_new: string[];
  alerts_resolved: string[];
  note: string;
}

export interface ContractVerification {
  intervention_id: string;
  contract_phase: string;
  verdict: "not_applicable" | "pending" | "resolved" | "partially_resolved" | "failed";
  checked_at: string;
  data_version: number;
  success_condition: string;
  target_hospital_ids: string[];
  interval_start: string | null;
  interval_end: string | null;
  target_deficit_physician_minutes: number | null;
  baseline_deficit_physician_minutes: number | null;
  new_critical_elsewhere: string[];
  findings: string[];
  next_steps: string[];
}

export interface EvaluationReport {
  as_of: string;
  data_version: number;
  rows: { metric: string; monitoring_only: unknown; reactive: unknown; neurogrid: unknown; note: string }[];
  timings_ms: Record<string, number>;
  notes: string[];
}

const LONG = 60_000;

function qs(params: Record<string, string | number | boolean | string[] | null | undefined>): string {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => s.append(k, x));
    else s.set(k, String(v));
  }
  const t = s.toString();
  return t ? `?${t}` : "";
}

export const neurogridApi = {
  availability: (signal?: AbortSignal) =>
    apiRequest<AvailabilityReport>("/api/intelligence/availability", { signal, timeoutMs: LONG }),
  problems: (signal?: AbortSignal) =>
    apiRequest<ProblemReport>("/api/intelligence/problems", { signal, timeoutMs: LONG }),
  timeMachine: (rateMultiplier: number | null, signal?: AbortSignal) =>
    apiRequest<TimeMachineReport>(
      `/api/intelligence/time-machine${qs({ rate_multiplier: rateMultiplier })}`,
      { signal, timeoutMs: LONG },
    ),
  lastSafeMoment: (signal?: AbortSignal) =>
    apiRequest<LastSafeMomentReport>("/api/intelligence/last-safe-moment", { signal, timeoutMs: LONG }),
  fragility: (signal?: AbortSignal) =>
    apiRequest<FragilityReport>("/api/intelligence/fragility", { signal, timeoutMs: LONG }),
  genome: (signal?: AbortSignal) =>
    apiRequest<GenomeReport>("/api/intelligence/genome", { signal, timeoutMs: LONG }),
  scarcity: (signal?: AbortSignal) =>
    apiRequest<ScarcityReport>("/api/intelligence/scarcity", { signal, timeoutMs: LONG }),
  coverageDebt: (signal?: AbortSignal) =>
    apiRequest<CoverageDebtReport>("/api/intelligence/coverage-debt", { signal, timeoutMs: LONG }),
  handoff: (signal?: AbortSignal) =>
    apiRequest<HandoffReport>("/api/intelligence/handoff", { signal, timeoutMs: LONG }),
  simulate: (params: { hospitalIds?: string[]; alertId?: string | null }, signal?: AbortSignal) =>
    apiRequest<RescueSimulation>(
      `/api/intelligence/simulate${qs({ hospital_id: params.hospitalIds, alert_id: params.alertId })}`,
      { signal, timeoutMs: LONG },
    ),
  loadGuardian: (signal?: AbortSignal) =>
    apiRequest<LoadGuardianReport>("/api/intelligence/load-guardian", { signal, timeoutMs: LONG }),
  evaluation: (signal?: AbortSignal) =>
    apiRequest<EvaluationReport>("/api/intelligence/evaluation", { signal, timeoutMs: LONG }),
  chaosScenarios: (signal?: AbortSignal) =>
    apiRequest<ChaosScenarioInfo[]>("/api/chaos/scenarios", { signal }),
  chaosRun: (scenarioId: string) =>
    apiRequest<ChaosResult>(`/api/chaos/run/${encodeURIComponent(scenarioId)}`, {
      method: "POST",
      role: "coordinator",
      timeoutMs: LONG,
    }),
  importPreview: (file: File, advanceClock: boolean) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return apiRequest<ImportPreview>(`/api/events/csv/preview${qs({ advance_clock: advanceClock })}`, {
      method: "POST",
      body: form,
      timeoutMs: LONG,
    });
  },
  importApply: (file: File, advanceClock: boolean) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return apiRequest<EventIngestResult & { clock_before?: string | null; clock_note?: string | null }>(
      `/api/events/csv${qs({ advance_clock: advanceClock })}`,
      { method: "POST", body: form, timeoutMs: LONG },
    );
  },
  contractPhases: (role: DemoUserRole, signal?: AbortSignal) =>
    apiRequest<Record<string, string>>("/api/rescue-contracts/phases", { role, signal }),
  verification: (id: string, role: DemoUserRole, signal?: AbortSignal) =>
    apiRequest<ContractVerification>(`/api/rescue-contracts/${encodeURIComponent(id)}/verification`, {
      role,
      signal,
      timeoutMs: LONG,
    }),
  verify: (id: string) =>
    apiRequest<ContractVerification>(`/api/rescue-contracts/${encodeURIComponent(id)}/verify`, {
      method: "POST",
      role: "coordinator",
      timeoutMs: LONG,
    }),
  propose: (body: Record<string, unknown>) =>
    apiRequest<Intervention>("/api/interventions", {
      method: "POST",
      body: body as unknown as InterventionCreate,
      role: "coordinator",
      timeoutMs: LONG,
    }),
};
