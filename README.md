# Sevaro Pulse: Tele-Neurology Operations Command Center

A hackathon build for the Rutgers Health Hack (Sevaro Challenge 2). It **detects**
coverage risk across a tele-neurology network, helps operations **decide** on an
intervention, and **acts** on it through clinical-lead approval and simulated offers to
off-shift physicians.

> **Status: Phase 5 (human-in-the-loop intervention workflow).** On top of detection
> (Phase 3) and the OR-Tools optimizers (Phase 4), the full Detect → Decide → Act loop
> runs end to end. A coordinator proposes a split shift, a reassignment or an
> escalation. A clinical lead approves or rejects; approval re-validates eligibility,
> offer limits and the remaining need. Approved offers are sent (simulated). The
> off-shift physician accepts or declines on a phone-sized view, and the system tracks
> activation and recalculates coverage, alerts and routing. Conflicting acceptances,
> expiry, idempotent replies and trap protection are handled server-side, and every step
> is audited. See [docs/workflow.md](docs/workflow.md).

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
                     interventions (Phase 5: state machines, policy, overlay, privacy)
    services/        … + workflow.py (Phase 5 orchestration, transactions, audit)
  data/raw/          drop dataset CSVs / ZIP here (git-ignored)
  sample_data/       SYNTHETIC SAMPLE DATA fixtures: synthetic_dev, synthetic_surge,
                     synthetic_staffing, synthetic_workflow (Phase 5 demo)
  scripts/           fixture generators (deterministic)
  tests/
frontend/   Next.js 16 App Router + TypeScript + Tailwind v4 + shadcn/ui + Lucide + Recharts
  src/app/           /, /coordinator, /clinical-lead, /physician
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

- Python **3.11+** (developed on 3.12)
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

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .
cd frontend && npx tsc --noEmit && npm run lint && npm run build
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

UI: open http://localhost:3000/coordinator → the dataset button in the page toolbar (it
opens **Dataset & simulation controls** in a drawer) → **Load staffing sample** (Phase 4
scenario), **Load surge sample** (Phase 3 scenario) or **Load dev sample** (Phase 2 replay
scenario), or upload the judging ZIP. The **Advance +1m/+5m/+15m/+60m** buttons next to it
move the simulation clock, which is always shown in the header.

Phase 4, with the staffing sample loaded (**Optimizer** tab at the bottom of the page):

1. **Routing**: the stroke consult STF-C1 goes to Dr. Ada Staff, the only eligible
   physician. The waiting General Neuro consult goes to Dr. Di Staff, and the ringing call
   stays with Dr. Ed Staff. STF-C4 cannot be placed, and the panel says why (Bo on video,
   Cy ended a call 1 min ago). Open "Why this recommendation" for the evidence and costs.
2. **Split shifts**: seven off-shift physicians × eight rules. Only Dr. Gil Staff passes.
   CP-SAT proposes 17:35–21:00 EDT for Lakeside and Summit: online 10 minutes before the
   gap, ending when it ends (deficit 195 → 60 physician-minutes over 240 min). Trap protection keeps him off busy Harbor.
3. **Preview impact** opens **What-if**: current forecast vs "projected if accepted" for
   each hospital. Try Dr. Jo Staff to see the overlap rule reject the offer.
4. **Compare**: optimizer vs least-loaded routing, a manual staffing heuristic, and
   unrestricted vs protected trap routing, including the metrics where the baseline wins.

Phase 3, with the surge sample:

1. **Needs attention**: 15 ranked alerts. Select one to see the time against the standard
   and the recommended next step; the rule (brief or assumption), why it has that
   priority and the evidence are one click away.
2. **Coverage forecast** tab: pick Northgate. The chart shows the requirement dropping and the
   shortfall from 19:00 to 19:15 EDT (two shifts end while the demand spike persists),
   then a night physician joining at 19:30 as uncertain coverage. "Why" lists every cause.
3. **Advance +15m**: a consult that was ingested late becomes visible; the spike now lasts
   until 19:25 and the gap grows to 25 physician-minutes, with no restart.
4. **Inject events** (in the dataset drawer): e.g. mark Dr. Reese Surge Temporarily Unavailable. Northgate goes
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
