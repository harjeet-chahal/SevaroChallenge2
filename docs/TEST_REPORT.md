# Test report

Integration validation on 11 Oct 2026 (America/New_York), macOS, Python 3.14.3,
Node 20.20.2. This updates the original 10 Oct report for main merged into juvana.

| Suite | Command | Result |
| --- | --- | --- |
| Backend unit, integration, property and regression | `cd backend && .venv/bin/pytest` | **310 passed**; final intelligence regression rerun: **50 passed** |
| Backend lint and format | `ruff check . && ruff format --check .` | clean |
| Frontend types | `npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | clean |
| Frontend components (Vitest + RTL) | `npm test` | **9 passed** |
| End-to-end (Playwright, Chromium) | `E2E_API_PORT=18000 E2E_FRONTEND_PORT=13000 npx playwright test` | **Blocked before test bodies**: macOS sandbox denies Chromium MachPortRendezvous startup. Six tests are defined; the original branch reported five passing on 10 Oct. No passing E2E result is claimed for the integration. |
| Production build | `npm run build` | 11 routes built |

## What the NEUROGRID tests cover

`tests/test_neurogrid_engines.py` runs against every bundled sample dataset **and** the
official data.

- **Availability classes.** Every physician gets exactly one class, with evidence.
  External-camera means not routable; agent-offline means UNCERTAIN, STALE and
  confirmation needed.
- **Single-point failure.** Dropping one physician's windows gives the same result as an
  independent rebuild without that physician. Removal never lowers the deficit
  (monotonicity).
- **Fragility.** Ranks are consistent. Each physician fills at most one position in the
  exclusive matching. Edges are always real credentials.
- **Property tests (Hypothesis).** Random removal sets never improve coverage, and the
  matching stays valid.
- **Last Safe Moment arithmetic.** The lead time equals approval + 10 + online time. On
  the official data, the deadline is re-derived from `physicians_off_shift_roster.csv`.
- **Scarcity.** An ineligible backup is never counted as an alternative, and the report
  flags "no feasible candidate".
- **Simulator.** Options are evaluated on isolated copies: the live models are unchanged.
  An ineligible or simulation-only option is never proposable. Keys are sorted
  lexicographically, and exactly one option is recommended.
- **Problem groups.** They partition the alerts deterministically, every critical alert
  is retained, and tiers are ordered.

`tests/test_neurogrid_api.py` covers:

- **Endpoints.** Every intelligence endpoint answers with the current data version.
- **Time Machine.** Only "now" is observed. Exact change points are kept as frames. The
  seeded bands are reproducible.
- **Chaos Lab.** All scenarios run without touching the baseline (data version, events,
  workflow version and clock are unchanged). The physician role is refused.
- **Import.** The preview changes nothing. Applying with `advance_clock` moves the clock
  forward. A later import containing only late events never moves it backward. An invalid
  CSV stores nothing, and a non-CSV upload is refused.
- **Rescue contract.** Verification stays *pending* while the offer is only accepted. The
  verdict becomes resolved or partially resolved after activation and is audited. The
  physician role is refused.
- **Official data.** All 16 chaos scenarios pass.
- **Main integration.** At 18:20, future Northfield candidates, deadlines, load protection
  and rescue impact remain visible, but the split shift is simulation-only without a
  proposal. Direct contract creation is refused. At the exact 18:30 window boundary it
  remains refused; at 18:31 Okafor becomes actionable and contract creation succeeds.

`frontend/e2e/*.spec.ts` (each run starts from a fresh database):

- `critical-rescue`: Command Center → Simulator → create contract → Clinical Lead approve
  and send → physician accepts on a phone viewport (no consult IDs visible) → verification
  pending → clock +60 → Verify & record gives resolved.
- `hidden-csv`: preview (with one duplicate), apply, the clock advances, and the new
  consult is triaged. A malformed CSV is refused and nothing is stored.
- `chaos-lab`: three scenarios PASS through the UI and the baseline config is unchanged.
- `approvals`: the clinical lead sees the stale-decision warning after an event arrives.
- `alert-progress`: linked escalation progress is visible on the alert and another open
  escalation is disabled. Component tests also cover completed, rejected and unrelated
  intervention types.

The official-data rescue and approvals E2E tests now advance to 18:31 before creating a
split shift. The rescue test first checks the simulation-only preview at 18:20. Alternate
ports start isolated backend/frontend servers with matching CORS, without reusing a
development server or its database.

## In-app browser inspection

The production build was inspected on separate local test ports. The Command Center,
future deadlines and simulation-only rescue impacts loaded. At 18:31 the rescue became
actionable. API-created test interventions appeared in the Clinical Lead view and in
the alert details as "Clinical escalation · Pending approval"; the duplicate escalation
control was disabled. This confirms rendering and action-state display, not a passing
automated browser workflow. A contract-creation attempt from the in-app browser reported
a network error; the same API proposal succeeded directly (201) and is covered by tests.

## Chaos Lab on the official data (18:20)

All 16 scenarios pass. Workflow fault scenarios advance only their isolated branch clock
when a forecast gap must enter the 90-minute action window; that step is reported in the
injected changes. No operational policy is relaxed and the baseline stays unchanged.

## Known gaps

- Docker Compose, `uv`, Python 3.12 and Node 24 were **not exercised** here; none of
  them is installed on the build machine.
- There are no load or performance tests beyond the timings in the evaluation endpoint.
  Analysis takes about 20 ms; the fragility scan and simulator take about 100–300 ms
  uncached.
- If the e2e suite runs against a backend that already holds offer history, weekly offer
  limits correctly change the outcome. The Playwright config therefore always starts a
  fresh backend.
