# Engines

Pure domain logic. Engines take schemas in and return schemas out. They do not import
FastAPI or SQLAlchemy; services load data via repositories and hand it to engines.

| Package               | Status  | Owns                                                          | Output                    |
| --------------------- | ------- | ------------------------------------------------------------- | ------------------------- |
| `event_processing`    | Phase 2 | Validation, identity/dedupe, ordering, visibility              | `NormalizedEvent`, `AnnotatedEvent` |
| `consultation_state`  | Phase 2 | Lifecycle transitions (`transitions.py`), time in stage       | `ConsultationState`       |
| `physician_state`     | Phase 2 | Raw signals + availability precedence (`availability.py`)     | `PhysicianState`          |
| `replay`              | Phase 2 | `reconstruct_state(events, as_of, reference)`                  | `OperationalState`        |
| `rules`               | Phase 3 | Every threshold/severity/policy, tagged brief vs assumption   | `RiskConfig`              |
| `demand`              | Phase 3 | Trailing-60-min arrivals vs local-hour p90                    | `DemandReport`            |
| `coverage_prediction` | Phase 3 | Exact piecewise R(t) vs A(t) forecast, deficit integral       | `CoverageReport`          |
| `alert_detection`     | Phase 3 | Rule detectors + deterministic ranking with reasons           | `AlertList`               |
| `analysis`            | Phase 3 | `analyze(events, reference, as_of, config)` orchestration     | `OperationalAnalysis`     |
| `optimization_input`  | Phase 3 | Optimizer-ready snapshot + Phase 4 solver Protocols           | `OptimizationInput`       |
| `timeline`            | Phase 3 | DST-safe local-time boundary helpers                          | —                         |
| `optimization`        | Phase 4 | Dispatch (min-cost flow), split-shift eligibility + CP-SAT, trap policy, what-if, baselines | `DispatchResult`, `StaffingResult`, `WhatIfResult` |
| `eligibility`         | Phase 5 | Protocol for the approval workflow (rules implemented in `optimization/split_shift`) | `CandidateEvaluation` |
| `interventions`       | Phase 5 | Propose / approve / offer / respond / expire, audit logging   | `Intervention`, `ShiftOffer` |

Conventions:

- All datetimes are timezone-aware. Compare in UTC; convert to the hospital's zone only
  for display or for rules defined in local time (coverage blocks, baseline hours).
- Engines never read the wall clock. They receive `as_of` (the simulation "now").
- Later engines consume `OperationalState` + `ReferenceData`; they must not re-derive
  physician or consult state themselves.
- Every decision is explainable: return the rule ID and evidence (see `decision_rule`
  and `explanation` on `PhysicianState`, `stage_history` on `ConsultationState`).
- See `docs/event-processing.md` (Phase 2), `docs/risk-and-coverage.md` (Phase 3) and
  `docs/optimization.md` (Phase 4).
