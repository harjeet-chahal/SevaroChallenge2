# Test report

Run on 10 Oct 2026 (local), macOS, Python 3.14.3, Node 20.20.2.

| Suite | Command | Result |
| --- | --- | --- |
| Backend unit, integration, property and regression | `cd backend && .venv/bin/pytest` | **308 passed** (259 existing + 49 NEUROGRID) |
| Backend lint and format | `ruff check . && ruff format --check .` | clean |
| Frontend types | `npx tsc --noEmit` | clean |
| Frontend lint | `npm run lint` | clean |
| Frontend components (Vitest + RTL) | `npm test` | **6 passed** |
| End-to-end (Playwright, Chromium) | `npx playwright test` | **5 passed** |
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

`frontend/e2e/*.spec.ts` (each run starts from a fresh database):

- `critical-rescue`: Command Center → Simulator → create contract → Clinical Lead approve
  and send → physician accepts on a phone viewport (no consult IDs visible) → verification
  pending → clock +60 → Verify & record gives resolved.
- `hidden-csv`: preview (with one duplicate), apply, the clock advances, and the new
  consult is triaged. A malformed CSV is refused and nothing is stored.
- `chaos-lab`: three scenarios PASS through the UI and the baseline config is unchanged.
- `approvals`: the clinical lead sees the stale-decision warning after an event arrives.

## Chaos Lab on the official data (18:20)

All 16 scenarios pass. Each run takes 170–520 ms on its own branch database.

## Known gaps

- Docker Compose, `uv`, Python 3.12 and Node 24 were **not exercised** here; none of
  them is installed on the build machine.
- There are no load or performance tests beyond the timings in the evaluation endpoint.
  Analysis takes about 20 ms; the fragility scan and simulator take about 100–300 ms
  uncached.
- If the e2e suite runs against a backend that already holds offer history, weekly offer
  limits correctly change the outcome. The Playwright config therefore always starts a
  fresh backend.
