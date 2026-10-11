/**
 * TypeScript mirrors of the backend Pydantic schemas (backend/app/schemas).
 * Keep these in sync by hand until the API surface stabilises; the backend is the
 * source of truth for field names and semantics.
 */

/** ISO-8601 timestamp that always includes a UTC offset (e.g. "2030-01-01T12:00:00Z"). */
export type IsoDateTime = string;

/** Simulated demo roles (X-Demo-Role). "system" marks automatic policy steps in the audit log. */
export type UserRole = "coordinator" | "clinical_lead" | "physician" | "system";

/** Roles a person can pick in the demo switcher. */
export type DemoUserRole = Exclude<UserRole, "system">;

export type Severity = "info" | "warning" | "critical";

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export interface ApiErrorResponse {
  error: ApiErrorBody;
}

// --- System -----------------------------------------------------------------

export interface ComponentHealth {
  status: "ok" | "error";
  detail: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  checked_at: IsoDateTime;
  database: ComponentHealth;
}

export interface ConfigResponse {
  app_name: string;
  version: string;
  environment: string;
  /** The simulation's "now". Null until configured or derived from a dataset. */
  simulation_time: IsoDateTime | null;
  simulation_time_source: "environment" | "dataset" | "manual" | "unset";
  dataset_loaded: boolean;
  /** Changes whenever the dataset, event log or derived staffing changes; refetch then. */
  data_version: number;
  /** Changes on every workflow transition (proposal, decision, offer, reply, ...). */
  workflow_version: number;
  pending_approvals: number;
  server_time: IsoDateTime | null;
}

// --- Offers (physician view) -------------------------------------------------

export interface HospitalRef {
  id: string;
  name: string;
}

export type OfferStatus =
  | "sent"
  | "accepted"
  | "active"
  | "completed"
  | "declined"
  | "expired"
  | "withdrawn"
  | "redundant"
  | "cancelled";

/** Exactly what an off-shift physician may see. No patient information. */
export interface PhysicianOfferView {
  id: string;
  status: OfferStatus;
  status_label: string;
  hospitals: HospitalRef[];
  hospital_timezone: string | null;
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  duration_minutes: number;
  minutes_to_online: number;
  expected_online_at: IsoDateTime | null;
  reason: string;
  sent_at: IsoDateTime;
  expires_at: IsoDateTime;
  responded_at: IsoDateTime | null;
  activated_at: IsoDateTime | null;
  can_accept: boolean;
  can_decline: boolean;
  can_go_online: boolean;
  message: string | null;
}

// --- Simulation clock ------------------------------------------------------------

export type ReferenceTimeSource =
  "import_option" | "environment" | "dataset_manifest" | "snapshot_filename" | "latest_ingested_at";

export interface SimulationClock {
  current_time: IsoDateTime | null;
  reference_time: IsoDateTime | null;
  reference_source: ReferenceTimeSource | null;
  /** Real wall-clock time on the server, for contrast only. */
  server_time: IsoDateTime;
  dataset_loaded: boolean;
  data_version: number;
  first_event_time: IsoDateTime | null;
  last_event_time: IsoDateTime | null;
  last_ingested_at: IsoDateTime | null;
  events_pending_ingestion: number;
}

// --- Datasets --------------------------------------------------------------------

export type IssueSeverity = "error" | "warning" | "info";

export interface ImportIssue {
  severity: IssueSeverity;
  code: string;
  message: string;
  file: string | null;
  row: number | null;
  column: string | null;
  value: string | null;
  hint: string | null;
}

export interface TableImportSummary {
  table: string;
  files: string[];
  rows_read: number;
  rows_imported: number;
  rows_rejected: number;
}

export interface ColumnMappingReport {
  file: string;
  table: string;
  mapped: Record<string, string>;
  unmapped_headers: string[];
  zone_hint: string | null;
}

export interface DatasetImportReport {
  import_id: string;
  status: "pending" | "validating" | "importing" | "completed" | "failed";
  source_name: string;
  label: string | null;
  synthetic: boolean;
  started_at: IsoDateTime;
  completed_at: IsoDateTime | null;
  tables: TableImportSummary[];
  column_mappings: ColumnMappingReport[];
  issues: ImportIssue[];
  issues_truncated: number;
  reference_time: IsoDateTime | null;
  reference_source: ReferenceTimeSource | null;
  counts: Record<string, number>;
}

export interface ActiveDataset {
  import_id: string;
  label: string | null;
  synthetic: boolean;
  source_name: string;
  imported_at: IsoDateTime;
  reference_time: IsoDateTime | null;
  reference_source: ReferenceTimeSource | null;
  counts: Record<string, number>;
  live_events: number;
  rejected_events: number;
  warnings: number;
}

export interface DatasetStatus {
  loaded: boolean;
  active: ActiveDataset | null;
  active_report: DatasetImportReport | null;
  last_attempt: DatasetImportReport | null;
}

// --- Reconstructed state -----------------------------------------------------------

export type Availability = "busy" | "available" | "unavailable" | "off_shift";

export type DerivedActivity =
  | "available"
  | "incoming_call"
  | "outgoing_call"
  | "video_consult"
  | "documentation"
  | "external_video_suspected"
  | "in_meeting"
  | "temporarily_unavailable"
  | "off_shift";

export type SelfReportedStatus = "available" | "in_meeting" | "temporarily_unavailable" | "unknown";

export interface ActiveSession {
  kind: "incoming_call" | "outgoing_call" | "video" | "ringing";
  consult_id: string | null;
  hospital_id: string | null;
  since: IsoDateTime;
  event_id: string;
}

export interface PresenceSignals {
  self_reported_status: SelfReportedStatus;
  status_since: IsoDateTime | null;
  agent_online: boolean | null;
  agent_status_since: IsoDateTime | null;
  agent_online_inferred: boolean;
  camera_active: boolean | null;
  camera_since: IsoDateTime | null;
  active_calls: ActiveSession[];
  active_videos: ActiveSession[];
  ringing: ActiveSession[];
  last_call_ended_at: IsoDateTime | null;
}

export interface SignalFlag {
  code: string;
  message: string;
  severity: Severity;
}

export interface ShiftWindow {
  start: IsoDateTime;
  end: IsoDateTime;
}

export interface PhysicianState {
  physician_id: string;
  display_name: string;
  roster: "on_shift" | "off_shift" | "unlisted";
  roster_role: string | null;
  as_of: IsoDateTime;
  scheduled_shift: ShiftWindow | null;
  shift_started_at: IsoDateTime | null;
  next_shift_starts_at: IsoDateTime | null;
  on_shift: boolean | null;
  minutes_to_shift_end: number | null;
  availability: Availability;
  activity: DerivedActivity;
  decision_rule: string;
  explanation: string[];
  signals: PresenceSignals;
  flags: SignalFlag[];
  evidence_event_ids: string[];
  consults_this_shift: number;
  calls_this_shift: number;
  open_consult_ids: string[];
  credentialed_hospital_ids: string[];
  /** Set for an approved split shift: counted and routed only at these hospitals. */
  routing_scope_hospital_ids: string[] | null;
  temporary_shift: TemporaryShift | null;
}

/** A split shift accepted through the Phase 5 workflow (a decision, not a source event). */
export interface TemporaryShift {
  intervention_id: string;
  offer_id: string;
  /** preparing = accepted, not online (never current capacity); active = online. */
  phase: "preparing" | "active";
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  expected_online_at: IsoDateTime;
  activated_at: IsoDateTime | null;
  routing_scope_hospital_ids: string[];
  seeded_consult_count: number;
}

export type ConsultStage =
  | "received"
  | "triaged"
  | "assigned"
  | "provider_contacted"
  | "imaging_pending"
  | "imaging_review"
  | "video_in_progress"
  | "note_pending"
  | "documentation"
  | "signed_off";

export interface ConsultStageTransition {
  stage: ConsultStage;
  entered_at: IsoDateTime;
  event_id: string;
  event_type: string;
  provisional: boolean;
}

export interface StateAnomaly {
  code: string;
  message: string;
  event_id: string | null;
  consult_id: string | null;
  physician_id: string | null;
}

export interface ConsultationState {
  consult_id: string;
  hospital_id: string | null;
  hospital_name: string | null;
  hospital_timezone: string | null;
  consult_type: string | null;
  priority: string | null;
  stage: ConsultStage;
  is_open: boolean;
  assigned_physician_id: string | null;
  received_at: IsoDateTime | null;
  stage_entered_at: IsoDateTime;
  closed_at: IsoDateTime | null;
  as_of: IsoDateTime;
  seconds_in_stage: number;
  seconds_since_received: number | null;
  stage_history: ConsultStageTransition[];
  assignment_history: {
    physician_id: string;
    at: IsoDateTime;
    event_id: string;
    inferred: boolean;
  }[];
  routing_failures: number;
  last_routing_failure_at: IsoDateTime | null;
  evidence_event_ids: string[];
  anomalies: StateAnomaly[];
}

export interface Hospital {
  id: string;
  name: string;
  timezone: string;
  coverage_tier: string | null;
}

export interface StateSummary {
  physicians_total: number;
  physicians_on_shift: number;
  on_shift_busy: number;
  on_shift_available: number;
  on_shift_unavailable: number;
  physicians_flagged: number;
  consults_open: number;
  consults_open_assigned: number;
  consults_open_unassigned: number;
  consults_closed: number;
  open_consults_by_stage: Record<string, number>;
}

export interface ReplayDiagnostics {
  events_total: number;
  events_applied: number;
  events_not_yet_ingested: number;
  events_future_event_time: number;
  duplicates_skipped: number;
  conflicting_duplicates: number;
  late_arrivals_applied: number;
  unknown_event_types: Record<string, number>;
  unknown_physician_ids: string[];
  unknown_hospital_ids: string[];
  anomalies: StateAnomaly[];
}

export interface OperationalState {
  as_of: IsoDateTime;
  data_version: number;
  summary: StateSummary;
  physicians: PhysicianState[];
  consultations: ConsultationState[];
  hospitals: Hospital[];
  diagnostics: ReplayDiagnostics;
}

// --- Events ------------------------------------------------------------------------

export type DedupeStatus = "canonical" | "duplicate" | "conflicting_duplicate";

export interface EventView {
  sequence: number;
  event_id: string;
  event_type: string;
  event_time: IsoDateTime;
  ingested_at: IsoDateTime;
  event_time_raw: string;
  ingested_at_raw: string;
  consult_id: string | null;
  physician_id: string | null;
  hospital_id: string | null;
  description: string | null;
  payload: Record<string, unknown>;
  raw: Record<string, unknown>;
  /** "workflow" = recorded by an applied intervention (simulated Synapse action). */
  source: "dataset_import" | "live_ingest" | "workflow";
  source_file: string | null;
  source_row: number | null;
  recognized: boolean;
  dedupe_status: DedupeStatus;
  duplicate_of_sequence: number | null;
  ingest_lag_seconds: number;
  arrived_out_of_order: boolean;
  visible: boolean;
  applied: boolean;
}

export interface EventPage {
  as_of: IsoDateTime;
  total: number;
  offset: number;
  limit: number;
  items: EventView[];
}

export interface FieldIssue {
  field: string | null;
  message: string;
}

export interface EventIngestOutcome {
  index: number;
  event_id: string | null;
  status: "accepted" | "duplicate" | "conflicting_duplicate" | "rejected";
  errors: FieldIssue[];
  warnings: string[];
  visible_now: boolean | null;
}

export interface EventIngestResult {
  received: number;
  accepted: number;
  duplicates: number;
  rejected: number;
  simulation_time: IsoDateTime | null;
  outcomes: EventIngestOutcome[];
}

// --- Phase 3: alerts ----------------------------------------------------------------

export type RecommendedAction =
  "reassign_consult" | "escalate" | "contact_physician" | "propose_split_shift" | "monitor";

export interface AlertEvidence {
  label: string;
  value: string;
  at: IsoDateTime | null;
  source_event_ids: string[];
}

export interface Alert {
  alert_id: string;
  rule_code: string;
  rule_name: string;
  rule_source: "challenge_brief" | "assumption";
  rule_reference: string;
  category: "consult_delay" | "physician_workflow" | "physician_signal" | "demand" | "coverage";
  severity: Severity;
  severity_reason: string;
  priority: number;
  priority_reasons: string[];
  rank: {
    severity_rank: number;
    category_rank: number;
    repeat_requests: number;
    urgency: number;
    coverage_risk: number;
    affected: number;
  };
  title: string;
  summary: string;
  recommended_action_type: RecommendedAction;
  recommended_action_reason: string;
  hospital_id: string | null;
  hospital_name: string | null;
  hospital_timezone: string | null;
  consult_id: string | null;
  physician_id: string | null;
  physician_name: string | null;
  as_of: IsoDateTime;
  condition_since: IsoDateTime | null;
  elapsed_seconds: number | null;
  warning_after_seconds: number | null;
  critical_after_seconds: number | null;
  impact_at: IsoDateTime | null;
  minutes_to_impact: number | null;
  evidence: AlertEvidence[];
  event_ids: string[];
  assumptions: string[];
  /** The completed intervention that handled this problem; handled alerts rank last. */
  handled_by: string | null;
}

export interface AlertList {
  as_of: IsoDateTime;
  data_version: number;
  /** Every active alert, open and handled. */
  total: number;
  /** Alerts still needing someone: priorities 1..open_total. */
  open_total: number;
  handled_total: number;
  /** Open alerts only. */
  counts_by_severity: Record<Severity, number>;
  counts_by_rule: Record<string, number>;
  alerts: Alert[];
  notes: string[];
}

// --- Phase 3: coverage ----------------------------------------------------------------

export type Certainty = "confirmed" | "uncertain";

export interface CoverageContributor {
  physician_id: string;
  display_name: string;
  /** "proposed" appears only in what-if projections, never in the live forecast.
   * "pending_activation": an accepted split shift not online yet (uncertain). */
  status: "counted" | "joins_later" | "excluded" | "proposed" | "pending_activation";
  certainty: Certainty | null;
  counts_from: IsoDateTime | null;
  counts_until: IsoDateTime | null;
  reasons: string[];
}

export interface CoverageSegment {
  start: IsoDateTime;
  end: IsoDateTime;
  required_base: number | null;
  spike_adjustment: number | null;
  required: number | null;
  available_confirmed: number;
  available_uncertain: number;
  available: number;
  deficit: number | null;
  deficit_if_uncertain_excluded: number | null;
  counted_physician_ids: string[];
  uncertain_physician_ids: string[];
}

export interface CoveragePoint {
  at: IsoDateTime;
  kind: "now" | "boundary" | "interval" | "horizon_end";
  required: number | null;
  available_confirmed: number;
  available_uncertain: number;
  deficit: number | null;
  spike_active: boolean | null;
}

export interface CoverageAnnotation {
  at: IsoDateTime;
  kind:
    | "shift_end"
    | "shift_start"
    | "requirement_change"
    | "spike_start"
    | "spike_end"
    | "dst_transition";
  label: string;
  physician_id: string | null;
}

export interface CoverageRiskMetrics {
  required_now: number | null;
  available_now: number;
  deficit_now: number | null;
  first_shortfall_at: IsoDateTime | null;
  minutes_until_shortfall: number | null;
  shortfall_minutes: number;
  worst_deficit: number;
  deficit_physician_minutes: number;
  deficit_physician_minutes_if_uncertain_excluded: number;
  confidence: "confirmed" | "uncertain" | "unknown";
  uncertainty_reasons: string[];
}

export interface HospitalCoverage {
  hospital_id: string;
  hospital_name: string;
  timezone: string;
  as_of: IsoDateTime;
  horizon_end: IsoDateTime;
  requirement_defined: boolean;
  metrics: CoverageRiskMetrics;
  segments: CoverageSegment[];
  points: CoveragePoint[];
  annotations: CoverageAnnotation[];
  contributors: CoverageContributor[];
  explanations: string[];
}

export interface CoverageReport {
  as_of: IsoDateTime;
  horizon_minutes: number;
  horizon_end: IsoDateTime;
  chart_step_minutes: number;
  data_version: number;
  method: string;
  assumptions: string[];
  hospitals: HospitalCoverage[];
}

// --- Phase 3: demand & metrics ---------------------------------------------------------

export interface DemandEvaluation {
  hospital_id: string;
  at: IsoDateTime;
  window_start: IsoDateTime;
  window_end: IsoDateTime;
  arrivals: number;
  consult_ids: string[];
  local_hour: number;
  local_hour_label: string;
  baseline_status: "ok" | "missing" | "day_type_mismatch" | "ambiguous_day_type";
  baseline_day_type: string | null;
  baseline_mean: number | null;
  baseline_p90: number | null;
  spike: boolean | null;
  requirement_adjustment: number | null;
  excess_over_p90: number | null;
  known_arrivals_only: boolean;
  comparison: string;
}

export interface HospitalDemand {
  hospital_id: string;
  hospital_name: string;
  timezone: string;
  current: DemandEvaluation;
  spike_ends_at: IsoDateTime | null;
  consults_without_received_time: number;
}

export interface DemandReport {
  as_of: IsoDateTime;
  window_minutes: number;
  requirement_increase: number;
  rule: string;
  method: string;
  hospitals: HospitalDemand[];
}

export interface OperationalMetrics {
  as_of: IsoDateTime;
  data_version: number;
  physicians: Record<string, number>;
  consults: Record<string, number>;
  open_consults_by_stage: Record<string, number>;
  longest_open_wait_seconds: number | null;
  alerts_by_severity: Record<string, number>;
  alerts_by_rule: Record<string, number>;
  coverage: Record<string, number | null>;
  earliest_projected_gap_at: IsoDateTime | null;
  earliest_projected_gap_hospital_id: string | null;
  demand: Record<string, number>;
  disclaimer: string;
}

export interface SampleDataset {
  name: string;
  label: string;
  synthetic: boolean;
  reference_time: string | null;
  default: boolean;
}

// --- Phase 4: optimization (recommendations only; nothing is executed) ----------------

export type SolverStatus =
  "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "NOT_SOLVED" | "MODEL_INVALID" | "UNKNOWN" | "FALLBACK";

export interface SolverStage {
  name: string;
  status: string;
  objective: number | null;
  wall_time_ms: number;
}

export interface SolverRun {
  optimizer: string;
  solver: string;
  status: SolverStatus;
  proven_optimal: boolean;
  fallback_used: boolean;
  wall_time_ms: number;
  objective: number | null;
  best_bound: number | null;
  time_limit_seconds: number | null;
  stages: SolverStage[];
  notes: string[];
}

export interface RuleCheck {
  code: string;
  label: string;
  passed: boolean;
  value: string | null;
  threshold: string | null;
  message: string;
  source: "brief" | "assumption" | "implementation_choice";
  missing_data: boolean;
}

export interface DispatchPhysician {
  physician_id: string;
  display_name: string;
  availability: Availability;
  activity: DerivedActivity;
  on_shift: boolean | null;
  counts_for_coverage: boolean;
  coverage_hospital_ids: string[];
  eligible_for_dispatch: boolean;
  effective_routing_capacity: number;
  routing_scope_hospital_ids: string[];
  consults_this_shift: number;
  open_consults: number;
  open_async_consults: number;
  low_volume: boolean | null;
  low_volume_threshold: number;
  minutes_since_last_call: number | null;
  minutes_to_shift_end: number | null;
  checks: RuleCheck[];
  uncertainty: string[];
}

export interface CostComponent {
  name: string;
  value: number;
  detail: string;
}

export interface WorkloadChange {
  consults_this_shift_before: number;
  consults_this_shift_after: number;
  open_consults_before: number;
  open_consults_after: number;
}

export interface Exclusion {
  physician_id: string;
  display_name: string;
  reasons: string[];
}

export interface DispatchRecommendation {
  consult_id: string;
  hospital_id: string | null;
  hospital_name: string | null;
  consult_type: string | null;
  consult_category: string | null;
  stage: ConsultStage;
  kind: "assign" | "reassign" | "confirm_ringing";
  physician_id: string;
  physician_name: string;
  current_physician_id: string | null;
  priority: number;
  urgency_tier: number;
  urgency_label: string;
  waiting_minutes: number | null;
  eligibility_evidence: string[];
  cost_breakdown: CostComponent[];
  edge_cost: number;
  workload: WorkloadChange;
  alternatives: string[];
  excluded: Exclusion[];
  uncertainty: string[];
  explanation: string[];
  executed: false;
}

export interface UnassignedConsult {
  consult_id: string;
  hospital_id: string | null;
  hospital_name: string | null;
  consult_type: string | null;
  stage: ConsultStage;
  urgency_tier: number;
  urgency_label: string;
  waiting_minutes: number | null;
  reason_code:
    | "no_credentialed_on_shift"
    | "no_eligible_physician"
    | "capacity_used_by_higher_priority"
    | "missing_hospital";
  explanation: string[];
  excluded: Exclusion[];
  competing_consult_ids: string[];
}

export interface SkippedConsult {
  consult_id: string;
  stage: ConsultStage;
  assigned_physician_id: string | null;
  reason: string;
}

export interface DispatchPlan {
  method: "min_cost_flow" | "least_loaded_baseline" | "fallback_greedy";
  recommendations: DispatchRecommendation[];
  unassigned: UnassignedConsult[];
  objective_cost: number;
}

export interface DispatchResult {
  as_of: IsoDateTime;
  data_version: number;
  policy_version: string;
  label: string;
  solver: SolverRun;
  plan: DispatchPlan;
  physicians: DispatchPhysician[];
  skipped: SkippedConsult[];
  policy: {
    rules: string[];
    assumptions: string[];
    implementation_choices: string[];
    weights: Record<string, number>;
    urgency_tiers: string[];
  };
  explanations: string[];
}

/** How voluntary availability affected a physician (a preference, never a rule). */
export type VoluntaryStatus =
  | "applied"
  | "not_eligible"
  | "no_shortage_overlap"
  | "no_offer_fits"
  | "outside_tolerance"
  | "not_needed"
  | "disabled";

export interface VoluntaryMatch {
  availability_id: string;
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  overlaps_shortage: boolean;
  overlap_minutes: number;
  shortage_start: IsoDateTime | null;
  shortage_end: IsoDateTime | null;
  offer_within_window: boolean;
  status: VoluntaryStatus;
  message: string;
}

/** Paid offer minutes × hourly rate. "simulated" = projected if accepted. */
export interface CostEstimate {
  basis: "simulated" | "confirmed";
  paid_minutes: number;
  hourly_rate: number;
  currency: string;
  amount: number;
  covered_physician_minutes: number;
  cost_per_covered_hour: number | null;
  note: string;
}

export interface CostComparison {
  label: string;
  physician_names: string[];
  cost: CostEstimate;
  deficit_after: number | null;
  /** Alternative − recommended (negative: the recommendation costs more). */
  saving: number;
  basis: "simulated" | "confirmed";
  explanation: string;
}

export interface PlanCost {
  recommended: CostEstimate;
  comparisons: CostComparison[];
  label: string;
  assumptions: string[];
}

export interface RankedOffer {
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  minutes: number;
  online_at: IsoDateTime;
  hospital_ids: string[];
}

export interface RankedCandidate {
  rank: number | null;
  rank_without_voluntary: number | null;
  /** Positive = moved up because of voluntary availability. */
  movement: number;
  physician_id: string;
  display_name: string;
  eligible: boolean;
  in_plan: boolean;
  voluntary: VoluntaryMatch | null;
  voluntary_preference_applied: boolean;
  offer: RankedOffer | null;
  coverage_physician_minutes: number;
  coverage_share_of_best: number | null;
  minutes_to_come_online: number | null;
  hours_worked_trailing_7d: number | null;
  remaining_weekly_hours: number | null;
  cost: CostEstimate | null;
  summary: string;
  reasons: string[];
}

export interface NeedRanking {
  hospital_ids: string[];
  hospital_names: string[];
  shortage_start: IsoDateTime | null;
  shortage_end: IsoDateTime | null;
  entries: RankedCandidate[];
  method: string[];
}

export interface VoluntarySummary {
  active_windows: number;
  applied: boolean;
  coverage_tolerance: number;
  reference_physicians: string[];
  explanation: string[];
}

export interface CandidateEligibility {
  physician_id: string;
  display_name: string;
  roster_role: string | null;
  eligible: boolean;
  failed_rules: string[];
  checks: RuleCheck[];
  gap_hospital_ids: string[];
  earliest_valid_start: IsoDateTime | null;
  latest_valid_end: IsoDateTime | null;
  max_offer_minutes: number | null;
  remaining_weekly_hours: number | null;
  minutes_to_come_online: number | null;
  online_time_assumed: boolean;
  proposed_start: IsoDateTime | null;
  proposed_minutes: number | null;
  missing_data: string[];
  summary: string;
  voluntary: VoluntaryMatch | null;
}

export interface HospitalEffect {
  hospital_id: string;
  hospital_name: string;
  deficit_physician_minutes_before: number;
  deficit_physician_minutes_after: number;
  reduction: number;
  horizon_minutes: number;
}

export interface TrapProtection {
  routing_scope_hospital_ids: string[];
  excluded_credentialed_hospital_ids: string[];
  seeded_consult_count: number;
  seed_policy: string;
  sync_capacity: number;
  rationale: string[];
}

export interface ShiftRecommendation {
  physician_id: string;
  display_name: string;
  offer_start: IsoDateTime;
  offer_end: IsoDateTime;
  offer_minutes: number;
  online_at: IsoDateTime;
  effective_minutes: number;
  hospital_ids: string[];
  hospital_names: string[];
  effects: HospitalEffect[];
  reduction_physician_minutes: number;
  excess_physician_minutes: number;
  protection: TrapProtection;
  explanation: string[];
  status: "proposed";
  requires_approval: true;
  voluntary: VoluntaryMatch | null;
  cost: CostEstimate | null;
}

export interface TrapRoutingOutcome {
  policy: "unrestricted_least_loaded" | "protected";
  modeled_arrivals: number;
  routed_to_joiner: number;
  routed_to_joiner_at_gap_hospitals: number;
  routed_to_joiner_elsewhere: number;
  joiner_final_consults: number;
  peer_median_consults: number | null;
  max_consults_any_physician: number;
  unrouted: number;
  by_hospital: Record<string, { arrivals: number; to_joiner: number }>;
}

export interface TrapAnalysis {
  physician_id: string;
  display_name: string;
  window_start: IsoDateTime;
  window_end: IsoDateTime;
  unrestricted: TrapRoutingOutcome;
  protected: TrapRoutingOutcome;
  conclusion: string;
  assumptions: string[];
}

export interface StaffingResult {
  as_of: IsoDateTime;
  data_version: number;
  policy_version: string;
  label: string;
  planning_horizon_end: IsoDateTime;
  solver: SolverRun;
  gap_hospital_ids: string[];
  candidates: CandidateEligibility[];
  recommendations: ShiftRecommendation[];
  totals: {
    planning_horizon_minutes: number;
    deficit_physician_minutes_before: number;
    deficit_physician_minutes_after: number;
    reduction: number;
    physicians_used: number;
    offered_minutes: number;
    excess_physician_minutes: number;
    fully_covered: boolean;
  };
  trap: TrapAnalysis | null;
  infeasibility: string[];
  rules: string[];
  assumptions: string[];
  explanations: string[];
  rankings: NeedRanking[];
  voluntary: VoluntarySummary | null;
  cost: PlanCost | null;
}

export interface SplitShiftAction {
  kind: "split_shift";
  physician_id: string;
  start?: IsoDateTime | null;
  duration_minutes: number;
  hospital_ids?: string[] | null;
}

export interface AssignConsultAction {
  kind: "assign_consult";
  consult_id: string;
  physician_id: string;
}

export type ProposedAction = SplitShiftAction | AssignConsultAction;

export interface HospitalProjection {
  hospital_id: string;
  hospital_name: string;
  before: HospitalCoverage;
  after: HospitalCoverage;
  deficit_physician_minutes_before: number;
  deficit_physician_minutes_after: number;
  reduction: number;
  deficit_now_before: number | null;
  deficit_now_after: number | null;
  first_shortfall_before: IsoDateTime | null;
  first_shortfall_after: IsoDateTime | null;
}

export interface WhatIfResult {
  as_of: IsoDateTime;
  data_version: number;
  label: string;
  action: ProposedAction;
  allowed: boolean;
  violations: RuleCheck[];
  checks: RuleCheck[];
  horizon_minutes: number;
  projections: HospitalProjection[];
  workload: WorkloadChange | null;
  effects_not_modeled: string[];
  explanations: string[];
}

export interface MetricPair {
  metric: string;
  label: string;
  baseline: number | null;
  optimized: number | null;
  better: "lower" | "higher";
  outcome: "optimized_better" | "tie" | "baseline_better" | "not_comparable";
  note: string | null;
}

export interface ComparisonSection {
  title: string;
  baseline_method: string;
  optimized_method: string;
  metrics: MetricPair[];
  summary: string;
  details: string[];
}

export interface OptimizationComparison {
  as_of: IsoDateTime;
  data_version: number;
  policy_version: string;
  dispatch: ComparisonSection;
  staffing: ComparisonSection;
  trap: ComparisonSection | null;
  solvers: SolverRun[];
  notes: string[];
}

// --- Phase 5: interventions, offers, audit -------------------------------------------

export type InterventionType = "reassign_consult" | "escalation" | "split_shift";

export type InterventionStatus =
  | "proposed"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "offer_sent"
  | "accepted"
  | "declined"
  | "expired"
  | "activated"
  | "completed"
  | "cancelled"
  | "no_longer_required";

export type InterventionAction =
  | "approve"
  | "reject"
  | "send_offers"
  | "apply"
  | "resolve"
  | "cancel";

export interface ActorRef {
  role: UserRole;
  actor_id: string | null;
}

export interface ProblemSnapshot {
  alert_id: string | null;
  rule_code: string | null;
  title: string;
  summary: string;
  severity: Severity | null;
  priority: number | null;
  hospital_ids: string[];
  hospital_names: string[];
  hospital_timezone: string | null;
  consult_id: string | null;
  consult_type: string | null;
  physician_id: string | null;
  physician_name: string | null;
  elapsed_seconds: number | null;
  warning_after_seconds: number | null;
  critical_after_seconds: number | null;
  impact_at: IsoDateTime | null;
  captured_at: IsoDateTime;
  data_version: number;
}

export interface AlternativeAction {
  type: InterventionType | "monitor";
  label: string;
  available: boolean;
  reason: string;
}

export interface InterventionRecommendation {
  summary: string;
  why: string[];
  algorithm: string;
  policy_version: string;
  solver_status: string | null;
  alternatives: AlternativeAction[];
  uncertainty: string[];
  restrictions: string[];
  approver_role: "clinical_lead" | "coordinator";
  ranking: NeedRanking | null;
  cost: PlanCost | null;
}

export interface OfferPlanItem {
  physician_id: string;
  display_name: string;
  role: "primary" | "backup";
  hospital_ids: string[];
  hospital_names: string[];
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  duration_minutes: number;
  minutes_to_online: number;
  online_time_assumed: boolean;
  expected_online_at: IsoDateTime;
  coverage_minutes: number;
  routing_scope_hospital_ids: string[];
  excluded_credentialed_hospital_ids: string[];
  seeded_consult_count: number;
  protection_rationale: string[];
  eligible: boolean;
  checks: RuleCheck[];
  projected_effects: HospitalEffect[];
  voluntary: VoluntaryMatch | null;
  cost: CostEstimate | null;
}

export interface HospitalImpact {
  hospital_id: string;
  hospital_name: string;
  deficit_before: number;
  deficit_after: number;
  shortfall_now_before: number;
  shortfall_now_after: number;
  first_shortfall_before: IsoDateTime | null;
  first_shortfall_after: IsoDateTime | null;
}

export interface CoverageImpact {
  label: string;
  horizon_minutes: number;
  hospitals: HospitalImpact[];
  total_before: number;
  total_after: number;
  computed_at: IsoDateTime;
  data_version: number;
  notes: string[];
}

export interface ReassignmentPlan {
  consult_id: string;
  hospital_id: string | null;
  hospital_name: string | null;
  consult_type: string | null;
  stage: string;
  current_physician_id: string | null;
  current_physician_name: string | null;
  target_physician_id: string;
  target_physician_name: string;
  eligible: boolean;
  checks: RuleCheck[];
  excluded: Exclusion[];
  alternatives: string[];
  workload_note: string | null;
}

export interface EscalationDetail {
  reason: string;
  requested_decision: string;
  blocking_facts: string[];
}

export interface ApprovalView {
  id: number;
  decision: "approve" | "reject";
  decided_by: ActorRef;
  decided_at: IsoDateTime;
  recorded_at: IsoDateTime;
  note: string | null;
  data_version: number;
  revalidation: string[];
}

export interface OfferResponseRecord {
  id: number;
  response: "accept" | "decline" | "activate";
  outcome: string;
  received_at: IsoDateTime;
  recorded_at: IsoDateTime;
  response_seconds: number | null;
  detail: string | null;
}

export interface ShiftOffer {
  id: string;
  intervention_id: string;
  physician_id: string;
  display_name: string;
  plan_role: "primary" | "backup";
  status: OfferStatus;
  status_reason: string | null;
  hospitals: HospitalRef[];
  routing_scope_hospital_ids: string[];
  seeded_consult_count: number;
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  duration_minutes: number;
  minutes_to_online: number;
  reason: string;
  channel: string | null;
  approved_by: ActorRef;
  sent_by: ActorRef;
  sent_at: IsoDateTime;
  expires_at: IsoDateTime;
  responded_at: IsoDateTime | null;
  accepted_at: IsoDateTime | null;
  expected_online_at: IsoDateTime | null;
  activated_at: IsoDateTime | null;
  activation_source: string | null;
  ended_at: IsoDateTime | null;
  responses: OfferResponseRecord[];
  allowed_actions: ("withdraw" | "activate" | "cancel")[];
}

export interface Intervention {
  id: string;
  type: InterventionType;
  status: InterventionStatus;
  status_reason: string | null;
  title: string;
  rationale: string | null;
  dataset_import_id: string | null;
  problem: ProblemSnapshot;
  recommendation: InterventionRecommendation;
  candidates: CandidateEligibility[];
  offer_plan: OfferPlanItem[];
  required_physicians: number;
  reassignment: ReassignmentPlan | null;
  escalation: EscalationDetail | null;
  impact: CoverageImpact | null;
  trap: TrapAnalysis | null;
  proposed_by: ActorRef;
  proposed_at: IsoDateTime;
  updated_at: IsoDateTime;
  created_data_version: number;
  version: number;
  approval: ApprovalView | null;
  offers: ShiftOffer[];
  allowed_actions: InterventionAction[];
  is_terminal: boolean;
  confirmed_cost: CostEstimate | null;
  confirmed_savings: CostComparison[];
}

export interface InterventionPage {
  total: number;
  items: Intervention[];
  counts_by_status: Record<string, number>;
}

export interface InterventionCreate {
  type: InterventionType;
  alert_id?: string | null;
  rationale?: string | null;
  expected_data_version?: number | null;
  physician_ids?: string[];
  hospital_ids?: string[];
  start_at?: IsoDateTime | null;
  duration_minutes?: number | null;
  consult_id?: string | null;
  target_physician_id?: string | null;
  hospital_id?: string | null;
  reason?: string | null;
}

export interface InterventionPreview {
  valid: boolean;
  blocking_reasons: string[];
  warnings: string[];
  data_version: number;
  intervention: Intervention | null;
}

export interface InterventionImpact {
  intervention_id: string;
  status: InterventionStatus;
  proposed: CoverageImpact | null;
  at_activation: CoverageImpact | null;
  current: CoverageImpact | null;
  trap: TrapAnalysis | null;
  routing: {
    physician_id: string;
    display_name: string;
    intended_hospital_ids: string[];
    authorized_scope_hospital_ids: string[];
    credentialed_hospital_ids: string[];
    workload_before_joining: { actual_consults: number; seeded_routing_count: number };
    consults_this_shift_now: number;
    routing_view: DispatchPhysician | null;
    current_dispatch_proposals_to_physician: string[];
    baseline: string;
    disclaimer: string;
  } | null;
  notes: string[];
}

export interface OfferResponseResult {
  offer: PhysicianOfferView;
  outcome: string;
  idempotent_replay: boolean;
  message: string;
}

export interface OfferRecipient {
  physician_id: string;
  display_name: string;
  open_offers: number;
  total_offers: number;
}

export interface OfferPage {
  total: number;
  items: ShiftOffer[];
}

export interface AuditEntry {
  id: number;
  occurred_at: IsoDateTime;
  recorded_at: IsoDateTime;
  actor: ActorRef;
  action: string;
  intervention_id: string | null;
  offer_id: string | null;
  entity_type: string;
  entity_id: string | null;
  from_status: string | null;
  to_status: string | null;
  summary: string;
  details: Record<string, unknown>;
  data_version: number;
}

export interface AuditPage {
  total: number;
  items: AuditEntry[];
}

export interface WorkflowSummary {
  workflow_version: number;
  data_version: number;
  simulation_time: IsoDateTime | null;
  pending_approvals: number;
  offers_awaiting_response: number;
  accepted_preparing: number;
  active_split_shifts: number;
  open_interventions: number;
}

export interface ExpireResult {
  simulation_time: IsoDateTime;
  expired_offer_ids: string[];
  activated_offer_ids: string[];
  completed_offer_ids: string[];
}

/** An off-shift physician's "I'm available" window. Never a shift assignment. */
export type AvailabilityStatus = "active" | "withdrawn";

export interface VolunteerAvailability {
  id: string;
  physician_id: string;
  display_name: string;
  status: AvailabilityStatus;
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  duration_minutes: number;
  timezone: string;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  withdrawn_at: IsoDateTime | null;
  version: number;
  phase: "upcoming" | "current" | "past" | "withdrawn";
  can_update: boolean;
  can_withdraw: boolean;
  message: string;
}

export interface PhysicianAvailabilityPage {
  physician_id: string;
  display_name: string;
  timezone: string;
  simulation_time: IsoDateTime;
  opted_in: boolean | null;
  min_useful_window_minutes: number;
  max_window_minutes: number;
  items: VolunteerAvailability[];
  notes: string[];
}

export interface AvailabilityPage {
  total: number;
  items: VolunteerAvailability[];
}
