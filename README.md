# NEUROGRID — the self-healing teleneurology operations network

**Detect the disruption. Find the last safe opportunity. Engineer the rescue. Verify the recovery.**

A Rutgers Health Hack build (Sevaro Challenge 2). NEUROGRID extends the existing Sevaro
Pulse command center into one connected control loop:
**detect → diagnose → forecast → decide → simulate → approve → act → verify → reassess**.

| Layer | What it does | Where |
| --- | --- | --- |
| Detect | Deterministic event replay (dedupe, late events, repeat calls); consult stages and SLAs; inferred physician availability; surge, coverage and routing alerts | existing Phases 2–3 |
| Diagnose | Ranked problems (alert fingerprints, lexicographic tiers); **Coverage Genome** root causes; **Network Fragility Scanner** (NetworkX) | `engines/intelligence`, `/coordinator`, `/network` |
| Forecast | **Coverage Time Machine** (exact 90-min frames, shift lanes, seeded Poisson demand band); **Last Safe Moment**; coverage debt; shift handoff | `/time-machine` |
| Decide / simulate | **Rescue Impact Simulator** (isolated copies, do-nothing comparator, lexicographic objective); **Rescue Scarcity Index**; **Physician Load Guardian** | `/simulator`, `/network` |
| Approve / act | Rescue contracts on the existing validated workflow: clinical-lead approval with re-validation (**Decision Freshness Lock**), simulated offers, expiry, conflicting acceptances | `/contracts`, `/clinical-lead`, `/physician` |
| Verify | Recovery verification against current state, recorded in the audit log | `/contracts` |
| Prove it | **Chaos Lab**: 16 fault scenarios on throw-away branch databases with real assertions; measured evaluation against monitoring-only and reactive baselines | `/chaos` |
| Ingest | Unseen event CSVs: validate and preview on a branch, then apply without restart (optional monotonic clock advance) | `/import` |

Start with [docs/DEMO.md](docs/DEMO.md) (the judging script with real numbers),
[docs/NEUROGRID_SPEC.md](docs/NEUROGRID_SPEC.md) (requirement → code → status),
[docs/RULES.md](docs/RULES.md), [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md),
[docs/TEST_REPORT.md](docs/TEST_REPORT.md) and [docs/TRADEOFFS.md](docs/TRADEOFFS.md).
NEUROGRID is decision support on synthetic data. It does not diagnose, does not control
Sevaro's production routing, and never bypasses credentialing, rest, working-hour or
approval rules.

<details><summary>Earlier phase notes (Sevaro Pulse)</summary>

> **Phase 5 (human-in-the-loop intervention workflow).** On top of detection
> (Phase 3) and the OR-Tools optimizers (Phase 4), the full Detect → Decide → Act loop
> runs end to end. See [docs/workflow.md](docs/workflow.md).

</details>

All data is synthetic. No patient information is stored or displayed, and no real SMS,
email or hospital integration exists.

## Repository layout

```
backend/    FastAPI + Pydantic v2 + SQLAlchemy (SQLite)
  app/
    api/routes/      HTTP routes (health, config)
    core/            settings, standard error envelope, time-zone utilities
    schemas/         Pydantic contracts: hospital, physician, consultation, event, alert,
                     coverage, intervention, offer, audit, dataset, system
    db/              engine/session, UTC-enforcing column type, ORM models
    repositories/    DB access only
    services/        orchestration; dataset_import/ interface + placeholder
    engines/         pure logic: event_processing, physician_state, consultation_state,
                     replay, rules, demand, coverage_prediction, alert_detection,
                     analysis, optimization_input, optimization (Phase 4),
                     interventions (Phase 5: state machines, policy, overlay, privacy),
                     intelligence (NEUROGRID: availability classes, time machine, last safe
                     moment, fragility, genome, scarcity, simulator, debt, handoff, problems)
    services/        … + workflow.py (Phase 5 orchestration, transactions, audit)
  data/raw/          drop dataset CSVs / ZIP here (git-ignored)
  sample_data/       SYNTHETIC SAMPLE DATA fixtures: synthetic_dev, synthetic_surge,
                     synthetic_staffing, synthetic_workflow (Phase 5 demo)
  scripts/           fixture generators (deterministic)
  tests/
frontend/   Next.js 16 App Router + TypeScript + Tailwind v4 + shadcn/ui + Lucide + Recharts + React Flow
  src/app/           /, /coordinator, /time-machine, /network, /simulator, /contracts,
                     /chaos, /import, /clinical-lead, /physician
  src/components/    ui/ (shadcn), layout/, status/, shared/, coordinator/, coverage/,
                     optimization/, workflow/, clinical-lead/, physician/
  src/lib/api/       typed API client + types
docs/
  architecture.md          layers, data model, team ownership split
  event-processing.md      replay rules, lifecycle transitions, availability precedence, API
  risk-and-coverage.md     alert rules & thresholds, ranking, demand spikes, coverage forecast
  optimization.md          dispatch (min-cost flow), split shifts (CP-SAT), trap, what-if
  dataset-import-plan.md   ZIP/CSV import: mapping, validation, atomic replacement
  workflow.md              Phase 5: state machine, approvals, offers, conflicts, activation
```

## Prerequisites

- Python **3.11+** (developed on 3.12; NEUROGRID verified on 3.14)
- Node.js **20.9+** and npm

## Run it

**Backend** (terminal 1):

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

The API serves at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

**Frontend** (terminal 2):

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000. Use the **Demo role** switcher in the header to move
between Coordinator, Clinical Lead and Physician views. There is no login.

## Checks

On a fresh checkout, run `npm run build` in `frontend` before standalone `tsc` so Next.js
generates its route types.

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .
cd frontend && npx tsc --noEmit && npm run lint && npm test && npm run build
cd frontend && npx playwright install chromium && npx playwright test   # e2e; starts its own backend on a fresh DB
```

`make install | backend | frontend | demo-data | test | e2e` wrap the same commands.
`docker-compose.yml` is provided but was not exercised on the build machine.

If development servers already occupy the default ports, run the isolated browser suite
with `E2E_API_PORT=18000 E2E_FRONTEND_PORT=13000 npx playwright test` from `frontend`.

## Staffing forecasts and actionable rescues

NEUROGRID retains the 240-minute planning views, rescue deadlines, scarcity analysis and
simulated impacts. Actual split-shift contracts follow the operational shortage look-ahead
(90 minutes by default). On the official 18:20 snapshot, future rescue options are visible
as simulation-only; at 18:31, Okafor becomes actionable for Northfield. Approval and
dispatch revalidate eligibility. Alerts also show linked intervention progress and disable
another same-type proposal while one remains open. See [docs/DEMO.md](docs/DEMO.md).

## NEUROGRID API

```bash
curl localhost:8000/api/intelligence/problems          # grouped, tiered problems
curl localhost:8000/api/intelligence/last-safe-moment  # rescue deadlines
curl localhost:8000/api/intelligence/time-machine      # projected frames + lanes + demand band
curl localhost:8000/api/intelligence/fragility         # graph, single points, allocation
curl localhost:8000/api/intelligence/genome            # root causes
curl localhost:8000/api/intelligence/scarcity          # off-shift backup scarcity
curl "localhost:8000/api/intelligence/simulate?hospital_id=SYN-008"
curl -X POST localhost:8000/api/chaos/run/surge_single -H 'X-Demo-Role: coordinator'
curl -X POST "localhost:8000/api/events/csv/preview?advance_clock=true" -F file=@judge.csv
curl -X POST "localhost:8000/api/events/csv?advance_clock=true" -F file=@judge.csv
curl -X POST localhost:8000/api/rescue-contracts/INT-0001/verify -H 'X-Demo-Role: coordinator'
```

## Demo

Phase 5 (load **workflow sample**; details in [docs/workflow.md §12](docs/workflow.md#12-demo)):

1. **Detect**: alert *Ridge Sample Clinic: coverage gap now (0/1)*.
2. **Decide**: **Propose split shift** opens a server-validated proposal. It shows every
   off-shift physician against every rule, the projected impact (90 → 20
   physician-minutes), alternatives and restrictions. Optionally add Dr. Yara Surge as a
   backup, then **Submit for clinical-lead approval** (nobody is contacted).
3. **Clinical Lead** (the tab shows a live pending badge): **Approve** (re-validated), then
   **Send approved offer (simulated)**.
4. **Physician**: Dr. Vale Surge sees hours, hospitals, time to come online, reason and
   deadline (no patient data), and taps **Accept**. Dr. Yara Surge's backup offer is
   withdrawn automatically.
5. **Act**: advance the clock 20 min. Vale is activated at the expected online time.
   Ridge goes from 90 to 0, the alert clears, routing sends SRG-C220 to Vale (scope
   SRG-H3 only), and the audit trail shows every step.

UI: open http://localhost:3000/coordinator → **Dataset & simulation controls** →
**Load staffing sample** (Phase 4 scenario), **Load surge sample** (Phase 3 scenario) or
**Load dev sample** (Phase 2 replay scenario), or upload the judging ZIP.

Phase 4, with the staffing sample loaded (**Recommendations** panel):

1. **Routing**: the stroke consult STF-C1 goes to Dr. Ada Staff, the only eligible
   physician. The waiting General Neuro consult goes to Dr. Di Staff, and the ringing call
   stays with Dr. Ed Staff. STF-C4 cannot be placed, and the panel says why (Bo on video,
   Cy ended a call 1 min ago). Open "Why this recommendation" for the evidence and costs.
2. **Split shifts**: seven off-shift physicians × eight rules. Only Dr. Gil Staff passes.
   CP-SAT proposes 17:45–21:45 EDT for Lakeside and Summit (deficit 195 → 60
   physician-minutes over 240 min). Trap protection keeps him off busy Harbor.
3. **Preview impact** opens **What-if**: current forecast vs "projected if accepted" for
   each hospital. Try Dr. Jo Staff to see the overlap rule reject the offer.
4. **Compare**: optimizer vs least-loaded routing, a manual staffing heuristic, and
   unrestricted vs protected trap routing, including the metrics where the baseline wins.

Phase 3, with the surge sample:

1. **Alert queue**: 15 ranked alerts. Select one to see the rule (brief or assumption),
   evidence, severity, why it has that priority, and the suggested intervention category.
2. **Hospital coverage**: pick Northgate. The chart shows the requirement dropping and the
   shortfall from 19:00 to 19:15 EDT (two shifts end while the demand spike persists),
   then a night physician joining at 19:30 as uncertain coverage. "Why" lists every cause.
3. **+15 min**: a consult that was ingested late becomes visible; the spike now lasts
   until 19:25 and the gap grows to 25 physician-minutes, with no restart.
4. **Inject events**: e.g. mark Dr. Reese Surge Temporarily Unavailable. Northgate goes
   from a projected gap to a gap now.

API equivalents:

```bash
curl -X POST "localhost:8000/api/datasets/sample?name=synthetic_surge"
curl localhost:8000/api/alerts
curl localhost:8000/api/coverage/SRG-H1
curl localhost:8000/api/demand
curl -X POST localhost:8000/api/simulation/advance -H 'content-type: application/json' -d '{"minutes": 15}'
curl -X POST localhost:8000/api/events -H 'content-type: application/json' -d '{"event_id":"LIVE-1","event_type":"physician_status_changed","event_time":"2030-09-10T18:34:30-04:00","physician_id":"SRG-P2","status":"Temporarily Unavailable"}'
```

Phase 4 API (read-only):

```bash
curl -X POST "localhost:8000/api/datasets/sample?name=synthetic_staffing"
curl localhost:8000/api/optimization/assignments
curl localhost:8000/api/optimization/split-shifts
curl localhost:8000/api/optimization/comparison
curl -X POST localhost:8000/api/optimization/simulate -H 'content-type: application/json' -d '{"action":{"kind":"split_shift","physician_id":"STF-P7","start":"2031-04-08T21:45:00Z","duration_minutes":240}}'
```

Phase 5 API (role via `X-Demo-Role`; see [docs/workflow.md §11](docs/workflow.md#11-api)):

```bash
curl -X POST "localhost:8000/api/datasets/sample?name=synthetic_workflow"
curl -X POST localhost:8000/api/interventions -H 'X-Demo-Role: coordinator' -H 'content-type: application/json' -d '{"type":"split_shift","alert_id":"COVERAGE_GAP_NOW:hospital:SRG-H3"}'
curl -X POST localhost:8000/api/interventions/INT-0001/decision -H 'X-Demo-Role: clinical_lead' -H 'content-type: application/json' -d '{"decision":"approve"}'
curl -X POST localhost:8000/api/interventions/INT-0001/send-offers -H 'X-Demo-Role: clinical_lead'
curl localhost:8000/api/offers/mine -H 'X-Demo-Role: physician' -H 'X-Demo-Actor-Id: SRG-P6'
curl -X POST localhost:8000/api/offers/OFF-0001/respond -H 'X-Demo-Role: physician' -H 'X-Demo-Actor-Id: SRG-P6' -H 'content-type: application/json' -d '{"response":"accept"}'
curl localhost:8000/api/interventions/INT-0001/audit -H 'X-Demo-Role: coordinator'
```

The judging event CSV appends to the loaded day without replacing it or any workflow
state: **Inject events → Append CSV** in the UI, or `POST /api/events/csv`.

Optimizers, constraints and objectives: [docs/optimization.md](docs/optimization.md);
rules, thresholds and methods: [docs/risk-and-coverage.md](docs/risk-and-coverage.md);
replay rules: [docs/event-processing.md](docs/event-processing.md).
Every error uses one envelope: `{"error": {"code", "message", "details"}}`.

## Configuration

| Variable (backend)          | Default                               | Notes                                   |
| --------------------------- | ------------------------------------- | --------------------------------------- |
| `APP_ENV`                   | `development`                         | `development` / `test` / `production`   |
| `DATABASE_URL`              | `sqlite:///./data/sevaro_pulse.db`    | Relative paths resolve from `backend/`  |
| `CORS_ORIGINS`              | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated                 |
| `SIMULATION_REFERENCE_TIME` | *(empty)*                             | Fallback reference time for imports (ISO-8601 **with offset**) |
| `DATASET_DIR`               | `./data/raw`                          | Suggested drop folder for dataset files |
| `SAMPLE_DATASET_DIR`        | `./sample_data/synthetic_dev`         | Loaded by `POST /api/datasets/sample`   |
| `DATASET_MAPPING_FILE`      | *(empty)*                             | JSON override for column aliases etc.   |
| `RISK_RULES_FILE`           | *(empty)*                             | JSON override for thresholds/policies   |
| `OPTIMIZATION_POLICY_FILE`  | *(empty)*                             | JSON override for optimizer weights, limits, trap policy |
| `INTELLIGENCE_POLICY_FILE`  | *(empty)*                             | JSON override for NEUROGRID lead times, weights, horizons ([ASSUMPTIONS](docs/ASSUMPTIONS.md)) |
| `MAX_UPLOAD_BYTES` / `MAX_UNCOMPRESSED_BYTES` / `MAX_ARCHIVE_ENTRIES` | 50 MB / 200 MB / 200 | Upload safety limits |

| Variable (frontend)          | Default                 |
| ---------------------------- | ----------------------- |
| `NEXT_PUBLIC_API_BASE_URL`   | `http://localhost:8000` |
| `NEXT_PUBLIC_STATUS_POLL_MS` | `15000`                 |

## Ground rules for contributors

- The backend owns all operational rules. The frontend never computes staffing,
  eligibility or breaches.
- Never hard-code physician/hospital/consult IDs, names, counts or timestamps from the
  challenge examples.
- Datetimes are always timezone-aware. Never assume a single network time zone.
- Engines receive `as_of`. They never read the wall clock.
- Messages to off-shift physicians require clinical-lead approval, enforced server-side.
- Roles are simulated with `X-Demo-Role` / `X-Demo-Actor-Id`. This is not production
  authentication.

See [docs/architecture.md](docs/architecture.md) for the suggested work split.
