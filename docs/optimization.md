# Dispatch & split-shift optimization (Phase 4)

Two optimizers sit on top of the Phase 3 analysis. They **recommend only**: no consult is
assigned, no offer is created or sent, and no staffing changes. Everything is computed by
the backend and shown in the coordinator's **Optimizer** tab. Acting on a
recommendation goes through the Phase 5 approval workflow ([workflow.md](workflow.md)).
Accepted and activated split shifts flow back in as a time-aware overlay. An active
physician is routed only inside the approved scope, with the seeded count.

```python
from app.engines.optimization import run_dispatch, run_staffing, simulate_intervention
result, baseline, problem = run_dispatch(analysis, config)   # Optimizer A
result, internals = run_staffing(analysis, config)          # Optimizer B
preview = simulate_intervention(analysis, action, ForecastConfig(config))
```

All policy lives in `backend/app/engines/optimization/config.py` and can be overridden with
a JSON file (`OPTIMIZATION_POLICY_FILE`). Every value is tagged **BRIEF** (copied from the
challenge brief), **ASSUMPTION** (the brief is silent or ambiguous) or **CHOICE**
(implementation choice: weights, tie-breaks, solver limits). Nothing below is presented
as an official Sevaro rule unless it is tagged BRIEF.

## 1. Optimizer A: consult dispatch (OR-Tools min-cost flow)

**Solver:** `ortools.graph.python.min_cost_flow.SimpleMinCostFlow`, solved exactly.

```
source ─(1)→ consult ─edge cost→ physician ─(k-th unit: k × fairness)→ sink
                 └──────── unassigned penalty U(c) ──────────────────→ sink
```

Every consult has an explicit "unassigned" arc, so the flow is always feasible and a
consult that cannot be placed is reported with a reason. It is never forced onto an
ineligible physician, because ineligible pairs have no arc at all.

**Which consults are in the problem**

| Consult | In the problem? |
| --- | --- |
| Open, unassigned, Triaged | yes, `assign` (ASSUMPTION: routing starts after triage) |
| Open, unassigned, not triaged but already rung or failed by routing | yes, `assign` (routing evidently started) |
| Call already ringing to an eligible physician | yes, pinned to that physician (`confirm_ringing`) |
| Assigned to a Temporarily Unavailable or off-shift physician, before notes | yes, `reassign`, with a disruption cost and labelled as a proposal (ASSUMPTION) |
| Still Assigned (hospital never contacted) with a critical alert, physician now busy with other work | yes, `reassign`, as a proposal (ASSUMPTION, `routing.reassign_stalled_assignment`) |
| Assigned to a working physician | **no**: never moved silently (listed under "skipped") |
| Note Pending / Documentation with an unavailable author | no: notes stay with their author |
| Received, not yet triaged | no (listed as skipped, with the reason) |

**Hard constraints** (an edge exists only if all hold)

| Constraint | Source |
| --- | --- |
| On shift and credentialed at the consult's hospital | BRIEF rule 1 |
| Not busy: Synapse call/video, or camera on with no Synapse session | BRIEF rule 2 + availability rules |
| Phone not ringing for another call | BRIEF rule 2 |
| Last call ended ≥ 2 minutes ago (exactly 120 s is eligible) | BRIEF rule 2 |
| Not Temporarily Unavailable | BRIEF availability rules |
| Hospital inside the physician's routing scope (split-shift protection) | CHOICE |
| ≤ `sync_capacity` (default 1) new consults per physician per round | CHOICE |

`counts_for_coverage` (Phase 3 coverage engine), `eligible_for_dispatch` (rules 1–2) and
`effective_routing_capacity` are reported separately for each physician. A physician on
a video call still counts toward coverage but has capacity 0. Open **asynchronous**
consults (imaging, notes) never consume synchronous capacity; they only add workload cost.

**Objective (lexicographic, CHOICE).** With *n* consults and *W* the largest possible
edge cost:

```
S      = n·W + 1                         one waiting minute outweighs any edge-cost total
U(c)   = T[tier(c)] + (wait(c) + 1)·S    unassigned penalty (> W, so assigning always wins)
T[0]=0, T[k+1] = n·(T[k] + (cap+1)·S + W) + 1
```

1. **Urgency tier** = 2 × alert severity (critical 2, warning 1, none 0) + 1 if stroke.
   This matches the Phase 3 alert ranking (severity first, then stroke). One consult of a
   higher tier is never traded for any number of lower-tier consults.
2. **Waiting time** (minutes since received, capped at 240): breaks contention within a tier.
3. **Edge cost** (bounded integers, each component capped):

   | Component | Weight | Models |
   | --- | --- | --- |
   | consults this shift | 20 each, ≤ 300 | BRIEF rule 4 (fewest consults) |
   | open consults | 15 each, ≤ 150 | workload |
   | not low volume | 200 | BRIEF rule 3 (low volume: ≤ 6 day / ≤ 4 night) |
   | recently answered | 50 − minutes since last call | BRIEF rule 4 tie-break (least recently answered*) |
   | shift ending | 2 per minute inside the last 60 | remaining shift |
   | shift end unknown | 30 | uncertainty |
   | agent offline / inferred | 100 / 30 | unverified availability |
   | reassignment | 150 | disruption |
   | k-th simultaneous consult | 100 × k | fairness (only if `sync_capacity` > 1) |

4. **Stable tie-break**, scaled below one cost unit: whoever answered longest ago (rule 4;
   the recency cost only spans 50 minutes, so this keeps the rule beyond that), then the
   lower physician id. The baseline and the greedy fallback use the same order.

**Day/night (rule 3).** The roster role decides (Day/Night). Without one (the on-shift
roster has no role column; "Float"), the shift start in the network's main time zone
(the zone most hospitals use) decides: a start from 17:00 to 05:00 is a night shift
(ASSUMPTION, `night_shift_from_hour`/`night_shift_until_hour`). The routing view says which
basis was used.

\* The event stream has no separate "answered" timestamp after a call ends, so least
recently answered is approximated by the most recent call end (ASSUMPTION). No
hospital-level priority is applied, because the brief documents none (the coverage tier
has no defined meaning).

Waiting time is bucketed only if the costs would not fit OR-Tools' range (max arc cost ×
node count, measured at about 3.7e18; checked against 2^60). For very large rounds (dozens
of waiting consults across all urgency tiers) approximate priorities are used instead: a
more urgent consult still beats a less urgent one one-for-one, but not any number of them.
Both cases are reported in the solver notes; if the solver still refuses, the labelled
greedy fallback runs instead of an error.

**Baseline.** This is least-loaded routing modelled on the brief's rules 3–5, applied one
consult at a time in arrival order: low volume first, then fewest consults, then least
recently answered, then id. It uses **the same edge set**, so it has identical hard
constraints. Both plans are scored with the same cost function.

**Exactness.** Tests compare the flow optimum against exhaustive search on six generated
problems.

## 2. Optimizer B: split-shift staffing (OR-Tools CP-SAT)

### 2.1 Candidate eligibility (every off-shift physician, every rule)

| Rule | Check | Source |
| --- | --- | --- |
| `opt_in` | opted in (missing = fail) | BRIEF |
| `credentialed_at_gap` | credentialed at ≥ 1 hospital with a gap in the planning window | BRIEF |
| `off_shift` | not currently on shift | CHOICE (structural) |
| `rest_10h` | ≥ 10 h since last shift ended, **at the offered start** (to the second) | BRIEF |
| `weekly_hours` | trailing-7-day hours + offered hours ≤ 60 | BRIEF |
| `no_overlap` | offer ends at or before the next scheduled shift | BRIEF |
| `min_length` | offer ≥ 2 h **after** the time to come online (the handbook: the time to get online "counts against what the offer is worth"). For a candidate it is judged on the longest offer the other limits allow (weekly hours, next shift, longest option); a limit already below 2 h fails that limit's rule instead | BRIEF |
| `notification_limits` | ≤ 1 open offer (an accepted, unfinished split shift also counts), ≤ 3 per rolling 7 days, from the Phase 5 offer log of the **active dataset import** (offers made before a re-import, e.g. demo rehearsals, are not part of this day) | BRIEF |
| `not_declined` | has not declined an offer for this hospital that is still running (until the declined offer's end). Only that hospital is left out: the physician can still be asked for another short hospital. A missed reply (expired offer) does not count as a decline | CHOICE |

All rules are evaluated even after one fails. Each check returns the observed value,
the threshold, a message and `missing_data`. **Missing data never passes:** missing
opt-in, last shift end, weekly hours or next shift fail their rule. A missing time to
come online is replaced by an assumed 30 minutes. This is flagged; it is not an
eligibility rule.

Rules are evaluated at the earliest valid start: now, or when 10 hours of rest are
reached. If rest is reached only after the planning window, `rest_10h` fails and the
message says when rest would be reached.

**Split shifts already worked** (completed, or cancelled after activation) count like a
scheduled shift: their end is the last shift end for `rest_10h`, and their hours are added
to the trailing 7-day hours for 7 days. An accepted or active split shift adds its planned
hours.

**Rolling 7-day window (ASSUMPTION, conservative).** The dataset gives hours worked in
the trailing 7 days as of the simulation time. For an offer ending at *E* the true window
is (*E* − 7 d, *E*]. Work that might age out before *E* has unknown timing, so it is
**not** subtracted. This can over-count but never under-count.

### 2.2 Options and model

- **Which hospitals are short (DECISION):** only those whose gap starts within the
  shortage look-ahead, `staffing.shortage_lookahead_minutes`. By default this is the
  dashboard's coverage forecast window (90 min, the brief's minimum), so the dashboard and
  the split-shift rules agree. Gaps later in the planning window are listed as "not acted
  on yet" and re-checked as the clock moves. See
  [official-scenario-audit.md](official-scenario-audit.md).
- **Stranded urgent consults (ASSUMPTION, `staffing.stranded_urgent_categories`, default
  `["stroke"]`):** capacity counts busy physicians, so a hospital whose credentialed
  physicians are all busy can look covered while its strokes wait. A stroke consult that
  needs a physician, already has an alert, and that the routing optimizer cannot place
  makes its hospital short **now**: with *n* such consults the hospital needs at least *n*
  physicians beyond those on duty there, until the end of the look-ahead (re-checked every
  clock move). It does not apply while a credentialed physician is held back only by the
  2-minute call cool-down or a phone ringing for another call. Only the split-shift
  planner reuses the consults the dashboard forecast already counted
  ([risk-and-coverage.md](risk-and-coverage.md) §4), so both show the same short hospitals.
  `[]` switches it off.
- **Planning window:** 240 min (CHOICE; offers last ≥ 2 h), used to choose offer starts
  and lengths and to value them. It is computed with the **same Phase 3 coverage engine**
  as the dashboard.
- **Starts:** the earliest valid start, plus "deficit begins (or deepens) minus time to
  online minus a login buffer" at the physician's gap hospitals (finite, ≤ 6). The buffer
  (`login_buffer_minutes`, 10 by default, CHOICE) puts the physician online a few minutes
  before the gap, because the time to come online is an estimate.
- **Lengths:** 120 / 180 / 240 / 360 min, plus (`fit_lengths_to_gap`) the shortest valid
  offer (2 h of coverage + time to come online) and lengths that end exactly when a gap
  ends, so offers don't run past the need. An option that ends exactly at the next
  scheduled shift, or uses exactly the weekly hours left, is added when shorter. Every
  option is re-checked against every rule before CP-SAT sees it.
- **Coverage:** the effective window [start + time to online, end) counts at each
  hospital in the physician's routing scope. This is non-exclusive, as the brief defines
  coverage. `count_at_all_scope_hospitals: false` switches to exclusive counting.

CP-SAT variables are x[o] ∈ {0, 1}. Constraints: at most one option per physician, at
most `max_new_physicians` (3) in total, and for each hospital and elementary time piece
`d ≥ base_deficit − Σ x`, `0 ≤ d ≤ base_deficit`. With `require_full_coverage`, Σ d = 0
at the hospitals short within the look-ahead (later gaps are not acted on yet, so they
cannot make the plan infeasible). The result may then be **INFEASIBLE**, and it is reported
as such.

**Lexicographic stages** (each fixes the previous optimum; CHOICE):
1. remaining deficit physician-seconds
2. physicians used
3. excess coverage
4. offered minutes
5. lateness (start − now)
6. stable tie-break (physician id, start, length)

Solver settings: 1 worker, fixed seed, a deterministic-time limit and a wall-clock limit
(default 3 s in total). Identical input gives identical output. Reported status:
**OPTIMAL** only if every stage is proven optimal, **FEASIBLE** if a stage hit its limit,
**INFEASIBLE** if no plan satisfies every constraint.

**Voluntary availability.** When an eligible physician has a valid offer inside a window
they volunteered, a second CP-SAT solve keeps the reference plan's number of physicians and
each hospital within `voluntary.coverage_tolerance` (15%) of its deficit reduction, and
maximizes the deficit covered by voluntary offers before the usual stages. Its stages are
reported as `voluntary`, `voluntary:deficit`, …. Without volunteers the result is
unchanged. Rankings per short hospital and an estimated cost (paid offer minutes ×
`cost.hourly_rate`) are part of the result. See
[voluntary-availability.md](voluntary-availability.md).

**Verification.** The chosen plan is re-scored with the Phase 3 coverage engine. The
response notes whether it matches the CP-SAT objective, and the coverage-engine figures
are the ones reported.

**Baseline.** A manual-style heuristic: offer first to whoever can be online soonest,
for the longest valid offer, and add physicians until the gap closes. It uses the same
eligibility-checked options.

## 3. Split-shift trap

The brief: a physician joining mid-shift starts with zero consults, so least-loaded routing
sends them nearly every call at every credentialed hospital.

**Protection policy** (CHOICE, configurable in `TrapPolicy`):
1. **Routing scope**: limited to credentialed hospitals that have the gap, with one
   exception (`overflow_outside_scope`, on by default). A consult at another credentialed
   hospital that already has an alert of at least `overflow_min_severity` (warning) gets an
   "overflow" edge to the joiner. That edge costs more than any regular edge
   (`split_shift_overflow` = the largest regular edge cost + 1), so the solver uses it only
   when otherwise a consult would be left unassigned. The least-loaded baseline uses it only
   when no regular option is left. A consult that is not overdue never reaches the joiner
   from outside the scope. Without this, an idle joiner could watch a stranded stroke
   consult at a hospital where they are credentialed.
2. **Seeded consult count**: the median routing count of the physicians who will be
   working at the same hospitals **when the joiner comes online**, read from the coverage
   windows (alternatives: `low_volume_threshold`, `none`). A peer whose shift ends before
   then is left out; one whose shift starts before then counts at 0. If nobody else works at
   those hospitals then, the median of everyone working anywhere is used. The proposal
   stores an estimate; at go-live the count is **recalculated** from the physicians working
   at that moment and written to the offer, and the audit entry records both values.
3. **Synchronous capacity**: the same as everyone else.

**Demonstration (simulate only).** Arrivals over the first 120 min after the joiner comes
online are modeled deterministically from each hospital's baseline hourly **mean**: one
arrival each time the cumulative mean crosses *k* − 0.5. These are not forecast patients.
Each arrival is routed with rules 3–4 under (a) unrestricted routing with a raw zero count
and (b) the protected policy, among the physicians counted at that hospital at that minute
(the coverage windows: a shift that ends drops out, a shift that starts later, such as a
night physician, joins at its start with 0 consults). Busy time is not modeled, which
isolates the rule-4 effect.
The result reports how many modeled consults go to the joiner, how many of those are at
hospitals without a gap, and the highest load. Protection can raise peers' load at
gap-free hospitals, and the comparison reports that honestly.

## 4. What-if preview

`POST /api/optimization/simulate` with
`{"action": {"kind": "split_shift", "physician_id", "start", "duration_minutes", "hospital_ids"}}`
or `{"action": {"kind": "assign_consult", "consult_id", "physician_id"}}`.

- Every rule is checked first, including the offer limits and declines from the Phase 5
  offer log (so a physician with an open offer, three offers this week, or a declined offer
  for that hospital is not "allowed"). A rule-breaking action returns `allowed: false` with the
  violations and **no projection**.
- Otherwise the Phase 3 coverage engine runs twice: as is, and on a copy of the model
  with the proposed window (contributor status `proposed`). Both full `HospitalCoverage`
  results are returned, labelled **"Projected if accepted — not confirmed coverage"**.
- Nothing is stored. The live forecast is unchanged (tested).
- Wait-time effects are listed as **not modeled**. No wait-time reduction is claimed.
- Consult assignment does not change coverage (coverage counts physicians, not consults),
  so before and after are identical, and the response says so.

## 5. API (read-only)

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/optimization/assignments?as_of=` | `DispatchResult`: proposals, unassigned with reasons, physician routing view, skipped consults, policy |
| GET | `/api/optimization/split-shifts?as_of=` | `StaffingResult`: every candidate × rule, plan, totals, trap analysis, infeasibility |
| GET | `/api/optimization/comparison?as_of=` | baseline vs optimized for routing, staffing and trap |
| POST | `/api/optimization/simulate` | `WhatIfResult` (stores nothing) |
| GET | `/api/optimization/input?as_of=` | Phase 3 optimizer snapshot (unchanged) |

Conventions are the same as Phase 3: the simulation clock by default, `data_version` in
every response, and the standard error envelope (`409 no_dataset`, `422
validation_error`). Results are cached per (data version, time, risk-rules signature,
policy signature, horizon). If OR-Tools is missing, a **labelled** greedy fallback runs
(`status: FALLBACK`, `fallback_used: true`, same hard constraints). With
`solver.allow_fallback: false` the API returns `503 optimizer_unavailable` instead.

## 6. Sample scenario (`synthetic_staffing`)

Generated by `backend/scripts/generate_staffing_dataset.py`. Hand-computed expectations
are in `backend/tests/test_optimization_scenario.py`.

- **Routing.** Least-loaded routing in arrival order gives the earlier General Neuro
  consult to Dr. Ada Staff (low volume) and strands the stroke consult that only she can
  take. The optimizer gives the stroke consult to Ada and the GN consult to Dr. Di Staff.
  It keeps the ringing call with Dr. Ed Staff, and explains why STF-C4 cannot be placed:
  Bo is on video and Cy ended a call 1 minute ago. The comparison reports 3 vs 2 placed
  and 1 vs 2 urgent left unassigned. It also reports that the highest workload rises from
  7 to 8 (baseline better on that metric).
- **Staffing.** Seven off-shift physicians are considered. Exactly one (Dr. Gil Staff) is
  eligible; the six others fail opt-in, rest, weekly hours, overlap, credentialing and
  missing data, one each. CP-SAT offers Gil 21:35–01:00Z (online 21:50Z, 10 minutes
  before the 22:00Z gap, ending when the gap ends) for Lakeside and Summit, reducing the
  deficit over 240 min from 195 to 60 physician-minutes. Over the
  90-min dashboard horizon, Lakeside goes from 30 to 0 and Summit from 15 to 0. Prairie's
  60 remain: its gap starts at 00:00Z, beyond the 90-min shortage look-ahead, so it is
  not acted on yet. Its only credentialed candidate (Mo) also has no recorded last shift
  end.
- **Trap.** Gil is also credentialed at busy Harbor (no gap). Unrestricted routing sends
  him 4 of Harbor's 8 modeled consults; the protected policy sends none.

## 7. Limitations

- The dispatch model is one routing round (a snapshot). It does not plan future arrivals
  or call durations.
- Least recently answered uses the last call end as a proxy.
- Staffing horizon, offer lengths, start candidates and weights are implementation
  choices. Changing them can change the plan.
- The trap demonstration uses baseline means and ignores busy time, so it shows the size
  of the effect, not a forecast.
- Notification limits use the system's own offer log (Phase 5 workflow tables). Offers
  sent before this system existed are unknown; `offers_declined_30d` is not used.
- Coverage counting is non-exclusive per the brief. A physician proposed for two gap
  hospitals counts at both (exclusive mode is available).
