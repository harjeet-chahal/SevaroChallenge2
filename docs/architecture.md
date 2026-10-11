# Architecture

## Principles

1. **The backend is the source of truth.** The frontend renders what the API returns. It
   never computes staffing, eligibility, breaches or forecasts itself.
2. **The event log is the source of operational state.** Physician activity, consult
   stages, alerts and forecasts are derived by replaying events up to `as_of`.
   Interventions, offers and the audit log are persisted workflow state.
3. **Dataset-independent.** IDs are opaque strings. No physician, hospital or consult
   identifiers, counts or outcomes appear in code.
4. **Time-zone correct.** Datetimes are aware everywhere. Storage is UTC, and display or
   local rules use each hospital's IANA zone.
5. **Explainable.** Every alert and eligibility decision carries the rule ID and evidence.
6. **Approval is enforced server-side.** No offer reaches an off-shift physician without
   a clinical lead's approval, and every step is audited.
7. **Synthetic data only.** No patient identifiers. Messaging is simulated.

## Backend layers

```
HTTP  ─▶ api/routes/*        thin: parse request, call a service, return a schema
          api/deps.py        DB session, settings, demo actor (X-Demo-Role)
       ─▶ services/*         orchestration: load via repositories → run engines → persist
       ─▶ engines/*          pure domain logic, schema in → schema out (no SQL, no HTTP)
       ─▶ repositories/*     SQLAlchemy queries only, no business rules
       ─▶ db/models/*        ORM tables
schemas/*                    Pydantic v2 contracts shared by all layers and the frontend
core/*                       settings, error envelope, time utilities
```

Errors: raise `AppError` subclasses (`NotFoundError`, `ConflictError`,
`PermissionDeniedError`, `NotImplementedYetError`, `DatasetValidationError`). Every
error response looks like this:

```json
{ "error": { "code": "not_found", "message": "…", "details": null } }
```

## Data model (tables)

| Table                     | Purpose                                                          |
| ------------------------- | ---------------------------------------------------------------- |
| `app_meta`                | Schema version (a mismatching DB is rebuilt on startup)          |
| `simulation_state`        | Single row: simulation clock, reference time, active import, `data_version` |
| `dataset_imports`         | Every import attempt with its full report                        |
| `events`                  | Append-only event log: normalized + raw record, duplicates kept  |
| `event_rejections`        | Records that failed validation (import or live)                  |
| `hospitals`               | ID, name, IANA zone, tier, extra attributes                      |
| `physicians`              | Profile + roster/schedule fields, roster kind, extra attributes  |
| `physician_credentials`   | Physician ↔ hospital                                             |
| `coverage_requirements`   | Min physicians per hospital per local time block (Phase 3)       |
| `baseline_volume`         | Mean/p90 consults per hospital per local hour (Phase 3)          |
| `reference_snapshot_rows` | Snapshot rows, kept verbatim for verification only               |
| `wf_interventions`, `wf_approvals`, `wf_offers`, `wf_offer_responses`, `wf_audit_log` | Phase 5 workflow persistence (see [workflow.md](workflow.md)). The Phase 1 placeholder tables `interventions`, `offers`, `audit_log` are no longer used |
| `wf_availability` | Voluntary availability shared by off-shift physicians (see [voluntary-availability.md](voluntary-availability.md)) |

No migrations in the hackathon: `create_all` runs on startup, and a schema-version
mismatch rebuilds the database (re-import the dataset afterwards).

## Frontend structure

```
src/app/                    routes: / (role picker), /coordinator, /clinical-lead, /physician
src/components/ui/          shadcn/ui primitives (generated; don't hand-edit)
src/components/layout/      header, demo role switcher
src/components/status/      SystemStatusProvider (polls /api/health + /api/config), badges
src/components/state/       OperationalStateProvider (one /api/state fetch per data_version+time)
src/components/dataset/     dataset & simulation controls, import report view
src/components/shared/      SectionCard, EmptyState, DataEmptyState, MetricCard, badges, …
src/components/<role>/      role-specific sections
src/hooks/                  useKeyedResource (refetch when a key such as data_version changes)
src/lib/api/                typed client, endpoint functions, types mirroring backend schemas
```

`DataEmptyState` decides why a placeholder section is empty (connecting, unreachable,
degraded, no dataset, feature not built yet). State-backed sections use `StateFallback`,
which adds "replaying…" and error states. The frontend computes no operational values:
counts, time-in-stage and availability all come from the backend.

## Parallel work: suggested ownership

| Stream | Backend | Frontend |
| --- | --- | --- |
| A. Ingestion (done) | `services/dataset_import`, `engines/event_processing`, `routes/datasets.py`, `routes/events.py` | dataset panel, event history |
| B. State + detection (done) | `engines/replay`, `physician_state`, `consultation_state`, `alert_detection`, `rules` | alert queue, alert details |
| C. Forecast + optimization (done) | `engines/demand`, `coverage_prediction`, `optimization_input`, `optimization` | coverage chart, recommendations panel |
| D. Workflow (done) | `engines/interventions`, `services/workflow.py`, `routes/interventions.py`, `routes/offers.py`, `routes/live.py` | coordinator composer & board, clinical lead approvals, physician offers |

Contracts between streams: schemas in `backend/app/schemas` (`OperationalState`,
`ReferenceData`, `AlertList`, `CoverageReport`, `OptimizationInput`, `Intervention`,
`ShiftOffer`, `PhysicianOfferView`, …) and the Protocol in
`engines/optimization_input/interface.py`. Change them
deliberately and tell the team.

## API

Implemented: Phase 2 endpoints in [event-processing.md §5](event-processing.md#5-api-phase-2),
Phase 3 endpoints in [risk-and-coverage.md §7](risk-and-coverage.md#7-api), Phase 4
endpoints in [optimization.md §5](optimization.md#5-api-read-only).

Phase 5 endpoints (interventions, offers, audit, live updates) are in
[workflow.md §11](workflow.md#11-api).
