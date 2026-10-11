# Voluntary doctor availability

An off-shift physician can say "I could cover an extra shift between these times" from
the phone view. The coordinator's split-shift recommendations then prefer that physician
for a matching shortage. It is a **preference, never a rule and never an assignment**:

- every split-shift rule still applies (opt-in, credentialed at the short hospital, off
  shift, 10 h rest, ≤ 60 h in 7 days, no clash with a scheduled shift, offer ≥ 2 h after
  coming online, offer limits, declines). The dataset has no separate specialty field, so
  credentialing at the hospital is the suitability check;
- a clinical lead still approves any offer, and the physician still accepts or declines it;
- withdrawing the availability removes the preference immediately.

Code:

- `backend/app/services/availability.py`, `api/routes/availability.py`,
  `repositories/availability.py`, `db/models/availability.py` (table `wf_availability`).
- `backend/app/engines/optimization/split_shift/ranking.py` (ranking, voluntary match, cost),
  `cpsat.py` (voluntary re-solve), `candidates.py` (window-fitted offer options).
- Frontend: `components/physician/availability-panel.tsx` (**I'm Available**),
  `components/optimization/ranked-physicians.tsx`, `cost-summary.tsx`, the
  `VoluntaryBadge` in `components/shared/status-badges.tsx`.
- Tests: `backend/tests/test_voluntary_availability.py`.

## 1. Persistence and API

`wf_availability` holds one row per window: physician, start and end (UTC), status
(`active` / `withdrawn`), simulation timestamps, a version and the dataset import. The table
is new, so existing databases gain it additively (`create_all`); `SCHEMA_VERSION` is
unchanged. Rows are never deleted, and a full dataset re-import starts a new day (windows
belong to the import they were made under).

| Method | Path | Who | Notes |
| --- | --- | --- | --- |
| GET | `/api/availability/mine` | physician (own) | windows, display zone, opt-in, shortest useful window |
| POST | `/api/availability` | physician | `{start_at, end_at}` (aware datetimes) → 201 |
| GET | `/api/availability/{id}` | owner or staff | |
| PUT | `/api/availability/{id}` | physician (own) | `{start_at, end_at, expected_version}`; 409 `stale_version` |
| POST | `/api/availability/{id}/withdraw` | physician (own) | idempotent |
| GET | `/api/availability?scope=active\|all` | coordinator, clinical lead | |

Validation (422 `availability_invalid` unless noted): only off-shift roster physicians;
the window ends after it starts, lasts 30 min to 24 h, has not ended, does not start in the
past (an update may keep a start that has passed), starts at most 14 days ahead; no overlap
with the physician's other open windows (409 `availability_overlap`); at most 5 open windows
(409 `availability_limit`). A window shorter than 2 h plus the physician's time to come
online is accepted, but the portal warns it cannot hold an offer.

**Live refresh.** Every change runs in the workflow's serialized write transaction and is
audited (`availability_submitted` / `_updated` / `_withdrawn`). The audit id is the
`workflow_version`, which keys the staffing optimizer's cache and is pushed by `/api/live`,
so open coordinator views re-rank within about a second, with no reload.

## 2. How availability changes the recommendation

1. **Options.** Besides the usual offer options, each eligible volunteer gets options that
   start and end inside their window (re-checked against every rule).
2. **Voluntary option** = an offer whose whole span lies inside one of the physician's
   windows. Partial overlap does not count: nobody is asked for time they did not offer.
3. **Reference plan.** CP-SAT solves exactly as before (deficit, physicians, excess,
   offered minutes, lateness, tie-break). Without voluntary options the result *is* this
   plan, so nothing changes when nobody volunteers.
4. **Voluntary re-solve** (only if a voluntary option covers some deficit): the same number
   of physicians as the reference, and each hospital where a volunteer could help keeps at
   least `1 − coverage_tolerance` (default **85%**) of the reference's deficit reduction
   (other hospitals: no worse at all). Within that, maximize the deficit covered by
   voluntary options, then the usual stages. A volunteer can **replace** someone; they are
   never added on top and never cause coverage to be dropped. The reference is feasible, so
   this is too.

Why a tolerance (CHOICE, `voluntary.coverage_tolerance` in the optimization policy): an
unsolicited offer can be declined or expire after 10 minutes and uses one of the
physician's 3 weekly offers; a volunteer has already said yes to that time. A small
coverage difference buys a much more certain answer. `0` makes availability a pure
tie-break; `voluntary.enabled: false` switches it off.

## 3. Ranking ("Who to ask first")

`StaffingResult.rankings` has one ranking per short hospital; a proposal stores the ranking
for its need in `recommendation.ranking`. Order:

1. physicians in the recommended plan;
2. deficit removed at the need hospitals by the physician's best valid offer; an offer
   inside a volunteered window counts as removing `1 / (1 − tolerance)` times its deficit
   (the same tolerance as the re-solve);
3. estimated cost (paid minutes), 4. online sooner, 5. fewer hours in the trailing 7 days,
   6. physician id.

`rank_without_voluntary` is the same ranking with nobody's availability counting and the
reference plan: the difference (`movement`) is exactly what volunteering changed, and the
first reason explains it ("Moved up from #2 to #1: …"). Physicians who cannot be asked are
listed unranked with the reason. Each volunteer carries a `voluntary` status: `applied`,
`not_eligible`, `no_shortage_overlap`, `no_offer_fits`, `outside_tolerance`, `not_needed`
or `disabled`. Only `applied` is shown as a green **Voluntarily Available** badge; the others
are muted with the reason in words.

## 4. Cost

The optimizer's existing cost measure is paid offer time (the `offered_minutes` stage).
`cost.hourly_rate` (default $200/h, an **ASSUMPTION**: the dataset has no pay data) turns it
into an amount. The whole offer is paid, including the time to come online (the brief:
it counts against what the offer is worth). The rate is the same for every physician, so
**volunteering never makes anyone cheaper**; a volunteer can only win on cost through fewer
paid minutes.

- Staffing result: the plan's cost vs the plan without voluntary availability and vs the
  manual heuristic (earliest online, longest valid offer).
- Proposal: the primary offer vs the other ranked physicians and the manual heuristic.
- All of these are **Simulated** (projected if accepted). An intervention gets a
  **Confirmed** cost only once its split shift has been worked (completed, or cancelled
  after going online), and confirmed savings compare that actual cost with each
  alternative's projection.

## 5. Demo (workflow sample)

1. Load **workflow sample**. Select **Ridge Sample Clinic: coverage gap now**. *Who to ask
   first*: 1. Dr. Vale Surge (online in 20 min, removes 220), 2. Dr. Yara Surge (35 min, 205).
2. **Physician** tab, signed in as Dr. Yara Surge → **I'm Available** → **Next 4 h** (or
   17:35–21:35 CDT) → **Share availability**. The phone says she has not been assigned a
   shift.
3. Back in **Coordinator**: Yara is #1 with **Voluntarily Available** and *Up from #2*;
   205 is 93% of 220, within the 85% tolerance. Vale is #2.
4. **Propose split shift** opens the proposal with Yara as the primary, the ranking ("Why it
   moved up") and **Cost and savings**: same $800 as Vale (no simulated saving, honestly),
   $400 less than the manual heuristic (Simulated).
5. **Submit for clinical-lead approval** → approve → send: the approval re-check notes she is
   voluntarily available for the whole offer, and her offer says it falls within the
   availability she shared. Withdrawing the window at any point puts Vale back first.

## 6. Limitations

- Availability is self-reported intent, not a commitment: the physician can still decline.
- A physician's windows cannot overlap (at most 5 open windows), and there is no recurring
  availability.
- The cost rate is illustrative and uniform; there is no overtime, premium or per-physician
  pay data.
- Withdrawing availability after a proposal does not cancel it: the approval re-check reports
  it and the clinical lead decides.
