# NEUROGRID specification: traceability

NEUROGRID is built on top of the existing Sevaro Pulse codebase. The architecture follows
the repository: FastAPI with `engines/` and `services/` on the backend, Next.js on the
frontend. The behaviour follows the NEUROGRID specification. This file maps each part of
the specification to the code that implements it, and states plainly where an item is
partial or missing.

Status: **Done**, **Partial** (works, with a stated limit) or **Not done**.

| Spec part | What | Where | Status |
| --- | --- | --- | --- |
| 2.1 / 6 | Load the official dataset; schema-driven CSV import; the 8 event columns | `services/dataset_import/*`, `POST /api/datasets/import` | Done (existing) |
| 2.2 / 6.3 | Dedup, event-time ordering, late arrivals, conflicting IDs, repeat calls, preserved waiting clock | `engines/event_processing`, `engines/replay` | Done (existing; tests in `test_engine_replay.py`, `test_official_scenario.py`) |
| 6.4 | Full deterministic replay after each upload, with no restart | `services/events.py`, analysis cache keyed by data version | Done |
| 6.5 | Simulation clock: monotonic clock policy for imports | `services/events.py::advance_to_latest`, `POST /api/events/csv?advance_clock=true` | Done (new; off by default to keep existing behaviour) |
| 6.6 | Reference snapshot comparison | `GET /api/datasets/verification` | Done: 0 mismatches over 174 fields (existing) |
| 6.1 | Import preview; no mutation before validation | `services/import_preview.py`, `POST /api/events/csv/preview` | Done (new; replays on an isolated branch) |
| 2.3 / 7.2 | Availability classes OFF_SHIFT … UNKNOWN, evidence, routable vs reachable vs needs-confirmation | `engines/physician_state` (precedence), `engines/intelligence/availability.py`, `GET /api/intelligence/availability` | Done |
| 2.4 / 7.1 | Consult stages and SLA thresholds | `engines/consultation_state`, `engines/rules` | Done (existing) |
| 2.5 | Routing rules 1–9 with exclusion reasons | `engines/optimization/routing` | Done (existing) |
| 2.6 / 8.3 | Coverage requirements, +1 on surge, hospital-local hours, ≥ 90 min look-ahead | `engines/demand`, `engines/coverage_prediction` | Done (existing) |
| 2.7 | Off-duty eligibility with PASS/FAIL per rule and arithmetic | `engines/optimization/split_shift/candidates.py` | Done (existing). Missing data counts as FAIL with `missing_data=true`; there is no separate UNKNOWN state |
| 2.8 | Three roles, enforced server-side | `api/deps.py` (`X-Demo-Role`), the workflow service | Done (existing) |
| 8.1–8.6 | Detectors | `engines/alert_detection` | Done (existing) |
| 8.7 / 8.8 | Lexicographic priority tiers; alert dedup by fingerprint | `engines/intelligence/operations.py::problem_report`, `GET /api/intelligence/problems` | Done (new) |
| 9 | Coverage Time Machine: deterministic frames at exact boundaries, shift lanes, freshness | `engines/intelligence/time_machine.py`, `/time-machine` | Done |
| 9.3 | Stochastic layer (seeded NumPy Poisson, sensitivity setting) | `time_machine.py::stochastic_demand` | Done. Labelled as sensitivity, not probability |
| 10 | Last Safe Moment: lead time, eligibility at the offered start, phases, missed window, mitigation | `engines/intelligence/rescue_planning.py`, `GET /api/intelligence/last-safe-moment` | Done |
| Integration | Preserve future planning features while incorporating main's shortage look-ahead and linked alert progress | `services/intelligence.py`, `engines/intelligence/simulator.py`, coordinator alert components | Done: future rescue options retain impacts as simulation-only; contracts use operational eligibility |
| 11 | Network fragility (NetworkX): bipartite graph, single-point failures, multi-failure scenarios, React Flow view | `engines/intelligence/network.py`, `/network` | Done |
| 12 | Coverage Genome: root causes, exclusive allocation, strategic suggestions | `engines/intelligence/genome.py`, `network.py::_allocation` (Hopcroft-Karp) | Done |
| 13 | Rescue Scarcity Index | `rescue_planning.py::scarcity_report` | Done |
| 14 | Rescue Impact Simulator: isolated copies, do-nothing comparator, lexicographic ranking, simulation-only labels | `engines/intelligence/simulator.py`, `/simulator` | Done. Options are ranked on exact re-evaluation, not by a new CP-SAT model. The combined plan reuses the existing Phase 4 CP-SAT staffing optimizer |
| 15 | Rescue Compiler and contract states | `engines/interventions/machine.py` (validated FSM) + `services/rescue_contracts.py` (phase mapping, verification) | Partial: contract phases are *derived* from the existing intervention statuses (mapping in RULES.md), not stored as a new table |
| 15.6 | Recovery verification | `POST /api/rescue-contracts/{id}/verify` | Done |
| 16 | Decision Freshness Lock | Existing revalidation on approval and dispatch, plus the new REVALIDATION_REQUIRED phase and clinical-lead banner | Done |
| 17 | Physician Load Guardian | `simulator.py::load_guardian_report` (builds on the existing trap protection) | Done. Labelled as a proposed policy |
| 18 | Coverage debt; fragile coverage; shift handoff | `engines/intelligence/operations.py`, `/time-machine` | Done |
| 19 | Chaos Lab: 16 scenarios on isolated branch databases, genuine assertions | `services/chaos.py`, `services/branch.py`, `/chaos` | Done |
| 20 | UI: dark control-room theme, all listed views | `frontend/src/components/neurogrid/*`, `src/app/*` | Done |
| 21 | Typed APIs | `schemas/intelligence.py`, `api/routes/intelligence.py`, `lib/api/neurogrid.ts` | Done |
| 22 | Real-time updates | Existing SSE `/api/live` + polling; every view keys on data/workflow version and the clock | Done (existing mechanism) |
| 24 | Tests | `backend/tests/test_neurogrid_*.py` (including Hypothesis), `frontend/tests`, `frontend/e2e` | Done; see TEST_REPORT.md |
| 25 | Audit | Append-only `wf_audit_log`; verification is recorded as `contract_verified` | Done |
| 29 | Evaluation versus baselines | `GET /api/intelligence/evaluation`, `/chaos` | Done (measured on the current state) |
| 3.1 | Docker Compose, `uv`, Python 3.12, Node 24 | `docker-compose.yml`, Dockerfiles, `Makefile` | Partial: files written but **not run** here (no Docker or `uv` on the build machine). Developed on Python 3.14 and Node 20 |
| 5 | Alembic migrations, scenario table, derived-state tables | — | Not done: the existing schema-version rebuild is kept (see TRADEOFFS.md). Branches are temporary database copies, not rows in a scenario table |
