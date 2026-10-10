# Official scenario audit (18:20 ET)

Audit of Sevaro Pulse against the official Challenge 2 dataset (`data/`), the Challenge 2
Handbook (chapters 2–6, pages 13–15 for the rules) and the original brief PDF. Every number
below was computed twice: once by the engine, and once by a separate standard-library
replay of the raw CSVs that shares no code with the backend. Both agree everywhere. The
regression tests in `backend/tests/test_official_scenario.py` pin these values, with
expectations derived from the CSVs, not from the engine.

All times are Eastern (EDT, UTC−4) unless a zone is given. "Now" is 2026-03-17 18:20:00 ET
(22:20:00Z).

## Summary

1. **Import, time zones and replay are correct.** No instant is shifted. The replay
   reproduces both reference snapshots with zero mismatches. Credentials, requirements,
   baselines and spike thresholds load exactly as labelled.
2. **Governing coverage definition: credentialed on-duty capacity.** A physician on a
   call or video still counts toward coverage, and a Temporarily Unavailable one does not.
   Being free right now is a routing concept. The brief's own wording ("credentialed
   capacity below the required level now or after upcoming shift ends") and the data
   support this (section 2).
3. **Under that definition there is no shortfall anywhere through 19:50.** The first
   shortfalls come from shift ends: Northfield (SYN-008) at **20:00** (100 min ahead), then
   Cedar Ridge (SYN-001) and Redwood (SYN-003) at **21:00** (160 min ahead).
4. **Root cause of the mismatch with the handbook.** Which off-shift physicians are
   "credentialed at a hospital that is short" depends only on how far ahead "short" is
   evaluated:

   | Look-ahead from 18:20 | Short hospitals | Eligible |
   | --- | --- | --- |
   | 90–100 min (the brief's minimum; the dashboard uses 90) | none | **nobody** |
   | 101–160 min | Northfield | **PHY-009 only** |
   | ≥ 161 min (the staffing default is 240) | Northfield, Cedar Ridge, Redwood | **PHY-009 and PHY-010** |

   Split-shift eligibility uses the 240-minute staffing planning window
   (`staffing.planning_horizon_minutes`, documented in [optimization.md](optimization.md)).
   That window reaches Redwood's 21:00 gap, so PHY-010 passes. The dashboard's 90-minute
   forecast shows no coverage gap at all at 18:20. The handbook's "exactly one" therefore
   holds only for a look-ahead between 101 and 160 minutes, and the brief only says "at
   least 90 minutes".
5. **Suncrest and Oak Valley have no capacity gap at any look-ahead.** Their 18:20 problem
   is routing: every credentialed physician is busy or unavailable, so CON-2114 and CON-2105
   cannot be routed. The engine flags both consults. Counting only free physicians would
   make them "short", but it would make Redwood short too (PHY-004 free against a Tier-A
   minimum of 2), so PHY-010 would still be eligible. No consistent reading of the written
   rules makes Suncrest or Oak Valley short while keeping Redwood out.

**Conclusion.** The official data does not support "exactly one eligible off-shift
physician at 18:20" under any single interpretation the text requires. No physician ID or
expected outcome is hard-coded. The look-ahead is a policy decision (section 8).

## 1. Base dataset validation

| Check | Result |
| --- | --- |
| Files and schemas | 9 CSVs, all headers mapped: event_stream 1,164 rows (8 columns), hospitals 12, physicians_on_shift 8, physicians_off_shift_roster 6, credentialing_matrix 14 × 12, baseline_hourly_volume 288 (12 × 24, weekday, 12 weeks), coverage_requirements 36 (12 × 3 blocks), snapshot_physicians 8, snapshot_open_consults 18 |
| Hospitals / physicians | all 12 hospitals (4 zones) and all 14 physicians present; zones match `hospitals.csv` |
| Event timestamps | every `event_time` and `ingested_at` carries an explicit `-04:00` offset; stored as UTC instants unchanged |
| Reference time | 18:20:00 ET = 22:20:00Z, taken from the `_1820` snapshot file name in the offset of the latest event |
| Late / duplicate records | EVT-00529 appears twice; the first-ingested copy is applied once. 23 records were applied out of arrival order; the only one more than 30 s late is EVT-01161 (video_started 18:11:20, ingested 18:18:05) |
| On-shift roster | `shift_start_et` / `shift_end_et` (no offset) are read as ET on 2026-03-17: the 8 shift windows equal the ET wall-clock instants |
| Off-shift roster | `last_shift_end` / `next_shift_start` carry offsets and are stored unchanged; hours, opt-in and time to come online match the file |
| Credentialing | 68 Y cells loaded cell for cell (matches the brief's printed matrix) |
| Coverage requirements | `time_block_et` is converted to hospital-local clocks (Chicago −1 h, Denver −2 h, Los Angeles −3 h). The requirement at all 48 half-hours of the day and at ±1 s of every block edge equals the CSV value for the ET wall clock, for all 12 hospitals |
| Baselines | `hour_start_et` is converted to local hours; the p90 at HH:30 ET equals the CSV row HH for all 24 hours × 12 hospitals |
| Spike thresholds | arrivals = distinct consults with `consult_received` in (t − 60 min, t]; spike = arrivals > p90 of the hour containing t. At 18:20 only Suncrest spikes (5 > 1) |
| Snapshots | engine verifier: 26 entities, 174 fields, 0 mismatches. The independent replay also reproduces every stage, entry time, minutes in stage, minutes since received, assignee, derived state, counts and minutes to shift end |

Note on the baselines: the hourly curves have the same shape in every time zone. The `_et`
label is the only evidence of their zone, and the importer honours it. At 18:20 the p90
and the coverage requirement are identical under either reading for all 12 hospitals, so
this does not affect the 90-minute result.

## 2. Coverage definitions

| Tier | Definition | Used for |
| --- | --- | --- |
| Scheduled credentialed capacity | on shift (or scheduled to start), credentialed, not Temporarily Unavailable; busy still counts | coverage requirement, projected gaps, split shifts |
| Immediately available (free) | capacity, minus anyone on a Synapse call or video or with the camera on outside Synapse | routing, stranded consults |
| Routing-ready | free, minus anyone whose phone is ringing or who hung up < 2 min ago (routing rule 2) | routing simulation, dispatch |

At 18:20: busy = PHY-001 (camera, no Synapse), PHY-002 (video), PHY-003 (outgoing call),
PHY-005 (incoming call), PHY-006 (video). PHY-008 is Temporarily Unavailable. Free =
PHY-004 (documenting) and PHY-007 (agent offline, unverified). Routing-ready = PHY-004 only,
because PHY-007's phone is ringing for CON-2109.

**Evidence for capacity governing the coverage requirement**

- Brief, Detect layer: "credentialed **capacity** below the required level now or after
  upcoming shift ends".
- The requirement is a staffing minimum per time block (07–16, 16–22, 22–07), and the
  brief's projected-gap example is a staffing event ("when shifts end at 19:00").
- Data (engine replay every 5 min, 09:00–18:20): capacity meets every *base* requirement
  at every sample. The only daytime capacity gaps come from the surge +1: Redwood
  11:30–12:00 and 14:10–15:05, and Bluewater at 09:55. Counting only free physicians,
  hospitals would be "short" for a large part of the day: Redwood 71% of samples,
  Northfield 32%, Bluewater 24%, Cedar Ridge 20%, Oak Valley 12%. Redwood has exactly 2
  credentialed physicians on shift against a minimum of 2, so it would be short whenever
  either takes a call. Yet the stream holds only 4 routing failures, all after 18:09. A
  per-minute stdlib replay without spikes gives the same picture: Redwood 68%.

**Evidence for the "free" reading**: the handbook uses "available, approved doctors", and
the routing failures say "No available credentialed provider". Those failures happen
exactly where a consult waits and no credentialed physician is free: Suncrest and Oak
Valley. That is the routing tier, and the engine already alerts on it.

**Decision**: capacity governs required hospital coverage. Free and routing-ready stay
routing concepts. This is the engine's existing behaviour
(`coverage.busy_counts_as_available = true`), and it is now pinned by tests. Flipping the
flag would also drop busy physicians for the *whole* horizon. Nothing in the data says how
long a call lasts.

## 3. Hospital trace at 18:20 (forecast to 19:50, planning window to 22:20)

Capacity is listed as counted physicians. "Shift changes" are those that affect the
hospital up to 19:50; later ones are noted when they create a gap.

| Hospital (zone) | Block at 18:20 (local) | Base | Arrivals / p90 | Required | Capacity now | Busy | Free | Routing-ready | Excluded | Shift changes to 19:50 | First deficit (90) | Deficit min (90) | First deficit (240) | Deficit min (240) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SYN-001 Cedar Ridge (Chicago) | 15:00–21:00 CDT | 2 | 0 / 3 | 2 | 4: 001, 003, 004, 006 | 001, 003, 006 | 004 | 004 | — | 19:00 −003 −006 +011 → 3 | none | 0 | 21:00 (−004 → 011 alone) | 60 |
| SYN-002 Bluewater (Denver) | 14:00–20:00 MDT | 1 | 0 / 2 | 1 | 2: 002, 007 | 002 | 007 | — | — | — | none | 0 | none | 0 |
| SYN-003 Redwood (Los Angeles) | 13:00–19:00 PDT | 2 | 1 / 3 | 2 | 2: 004, 005 | 005 | 004 | 004 | — | — (20:00 −005 +012) | none | 0 | 21:00 (−004 → 012 alone) | 60 |
| SYN-004 Meadowlands (NY) | 16:00–22:00 EDT | 1 | 1 / 2 | 1 | 4: 001, 003, 005, 006 | all | — | — | — | 19:00 → 3 | none | 0 | none | 0 |
| SYN-005 Suncrest (NY) | 16:00–22:00 EDT | 1 | **5 / 1 spike** | **2** until 19:04:30, then 1 | 3: 003, 005, 006 | all | — | — | — | 19:00 −003 −006 +011 → 2 | none | 0 | none | 0 |
| SYN-006 Highland Valley (Chicago) | 15:00–21:00 CDT | 1 | 0 / 2 | 1 | 3: 001, 004, 006 | 001, 006 | 004 | 004 | 008 (Temp. Unavailable) | 19:00 → 2 | none | 0 | none | 0 |
| SYN-007 Silver Oak (NY) | 16:00–22:00 EDT | 1 | 0 / 2 | 1 | 2: 002, 004 | 002 | 004 | 004 | 008 | — | none | 0 | none | 0 |
| SYN-008 Northfield (NY) | 16:00–22:00 EDT | 2 | 1 / 3 | 2 | 4: 001, 002, 005, 006 | all | — | — | — | 19:00 −006 +011 → 4 | none | 0 | **20:00** (−001 −002 −005 → 011 alone) | 120 |
| SYN-009 Lakeview (Chicago) | 15:00–21:00 CDT | 1 | 1 / 2 | 1 | 4: 001, 003, 004, 006 | 001, 003, 006 | 004 | 004 | — | 19:00 → 3 | none | 0 | none | 0 |
| SYN-010 Oak Valley (NY) | 16:00–22:00 EDT | 1 | 1 / 1 | 1 | 1: 002 | 002 | — | — | 008 | — (20:00 −002 +012) | none | 0 | none | 0 |
| SYN-011 Harbor (NY) | 16:00–22:00 EDT | 1 | 1 / 2 | 1 | 4: 001, 002, 005, 006 | all | — | — | 008 | 19:00 → 4 | none | 0 | none | 0 |
| SYN-012 Westbridge (Denver) | 14:00–20:00 MDT | 1 | 1 / 2 | 1 | 4: 001, 003, 006, 007 | 001, 003, 006 | 007 | — | — | 19:00 → 2 | none | 0 | none | 0 |

The night physicians PHY-011 (from 19:00) and PHY-012 (from 20:00) have no known shift
end, so they are counted as *uncertain* coverage. Everyone who is not credentialed at a
hospital is excluded there, with that reason.

**Suncrest (SYN-005).** Required = 1 + 1 (5 arrivals since 17:20 vs p90 1). It has 3 on
duty (PHY-003, PHY-005, PHY-006), all busy. At 19:00 PHY-003 and PHY-006 leave and PHY-011
starts: 2 for 2. The spike ends at 19:04:30, when CON-2107 (received 18:04:30) leaves the
60-minute window; future arrivals are not invented. After 19:04:30, 2 on duty against 1
required. **No capacity gap.** At 20:00 PHY-005 leaves and PHY-011 stays: 1 for 1. A gap at
20:00 would appear only if the surge were assumed to continue, and neither the known
arrivals nor the baseline mean (0.4/h) support that. **Routing:** all 3 are busy, so
CON-2114 failed routing at 18:17:15.

**Oak Valley (SYN-010).** Required 1 (1 arrival vs p90 1, no spike). PHY-002 is on duty
(video until 20:00); PHY-008 is Temporarily Unavailable and excluded. At 20:00 PHY-002
leaves exactly as PHY-012's night shift starts. **No capacity gap at any horizon.**
**Routing:** nobody credentialed is free, so CON-2105 failed routing at 18:09:10, 18:14:10
and 18:19:10, and it is a critical Triaged-unassigned alert (10 min 55 s).

**Redwood (SYN-003).** Tier A, required 2. It has exactly PHY-004 and PHY-005; PHY-005 is on
an incoming call. Capacity 2 for 2 until 20:00. Then PHY-012 replaces PHY-005, so still 2.
At 21:00 PHY-004 leaves: 1 of 2 until the 22:00 block change. **Gap 21:00–22:00 (60
physician-minutes)**, 160 min ahead. Under the free reading Redwood would also be short at
18:20 (1 free of 2).

## 4. Off-shift physicians

Proposed start is the earliest valid start: 18:20, or the end of the 10-hour rest if that
is later. Hours are checked with the minimum 2-hour offer.

| | PHY-009 Okafor | PHY-010 Alvarez | PHY-011 Cho | PHY-012 Haddad | PHY-013 Brennan | PHY-014 Menon |
| --- | --- | --- | --- | --- | --- | --- |
| Opt-in | Yes | Yes | Yes | **No** | **No** | Yes |
| Credentialed | 004, 005, 008, 010 | 002, 003, 006, 007 | 001, 004, 005, 008, 009, 011 | 002, 003, 006, 007, 010, 012 | 005, 009, 010, 011 | 001, 005, 010 |
| Last shift end | 03-17 07:00 | 03-16 20:00 | 03-17 07:00 | 03-16 08:00 | 03-16 20:00 | 03-16 20:00 |
| Rest at 18:20 | 11.3 h | 22.3 h | 11.3 h | 34.3 h | 22.3 h | 22.3 h |
| 7-day hours + 2 h | 38 | 26 | 50 | 38 | 50 | **61** |
| Next shift | 03-18 19:00 | 03-19 08:00 | **03-17 19:00** (40 min) | **03-17 20:00** (100 min) | 03-18 08:00 | 03-19 07:00 |
| Overlap with a 2 h offer from 18:20 | no | no | **yes** | **yes** | no | no |
| Time to online | 15 min | 10 min | 0 | 0 | 20 min | 40 min |
| Longest offer (hours / next shift / 360) | 360 | 360 | 40 | 100 | 360 | 60 |
| Useful after coming online | 345 | 350 | 40 | 100 | 340 | 20 |
| Offer limits (open / 7 days) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Short hospitals credentialed, 90 min | none | none | none | none | none | none |
| Short hospitals credentialed, 240 min | **008** | **003** | 001, 008 | 003 | none | 001 |
| Engine result (240 min) | **eligible** | **eligible** | no_overlap | opt_in, no_overlap | opt_in, credentialed_at_gap | weekly_hours |

`offers_declined_last_30d` (1, 0, 2, 0, 5, 0) is informational; the brief has no rule on it.

**Why PHY-009 and PHY-010 both pass.** Each passes every rule at 18:20: opted in, rested
(11.3 h and 22.3 h), hours (38 h and 26 h with 2 h, 39 h and 27 h with the recommended
3 h), no clash with a scheduled shift, ≥ 2 h useful after coming online, and no offers
sent. Each is also credentialed at a hospital that is short in the 240-minute window:
PHY-009 at Northfield (20:00) and PHY-010 at Redwood (21:00). The recommended plan is:

- PHY-009, 19:45–22:45, online 20:00, Northfield.
- PHY-010, 20:50–23:50 (17:50–20:50 PDT), online 21:00, Redwood.

This takes the deficit from 240 to 60 physician-minutes. Cedar Ridge's 21:00 gap remains:
its only off-shift credentialed physicians are PHY-011 (already working her night shift)
and PHY-014 (hours), so the brief's answer there is to escalate.

Against the handbook: PHY-010 is meant to fail one rule ("credentialed elsewhere") and
does so for any look-ahead of 160 min or less. PHY-011 (overlap) and PHY-014 (hours) fail
exactly the expected single rule. PHY-012 fails opt-in and overlap. PHY-013 fails opt-in,
and also credentialing because none of its hospitals is short under capacity.

## 5. Look-ahead sensitivity (engine)

| Clock | Look-ahead | Eligible |
| --- | --- | --- |
| 18:20 | 90, 100 | none |
| 18:20 | 101 – 160 | PHY-009 |
| 18:20 | 161, 240 | PHY-009, PHY-010 |
| 18:30 | 90 | none |
| 18:31 – 19:30 | 90 | PHY-009 |
| 19:31 | 90 | PHY-009, PHY-010 |

Change it with an optimization policy file
(`OPTIMIZATION_POLICY_FILE` → `{"staffing": {"planning_horizon_minutes": N}}`).

## 6. Judge CSV ingestion (official day)

Test: `test_judge_csv_appends_to_the_official_day_without_resetting_anything`. Eight rows
were sent at 18:20: a new stroke consult at Suncrest, a repeat call for CON-2105, a record
5.5 min late, the same record twice, a base record resent, and a backfilled record.

| Requirement | Result |
| --- | --- |
| Appends to the active base dataset | same import ID; data version +1; base events untouched |
| Preserves workflow state | a split-shift intervention proposed before the upload stays `pending_approval` |
| Late records | applied at their event time (CON-2107 Note Pending from 18:22). A backfilled 18:15 record is visible at once (CON-2118 Documentation from 18:15) |
| Duplicates | in-file repeat and resent base record reported as `duplicate`, stored, never applied twice |
| Updates alerts, coverage and recommendations | after advancing to 18:30: Suncrest 6 arrivals (spike), ROUTING_FAILURE for CON-9001, staffing recomputed at the new data version |
| No restart | same running app throughout |
| Waiting time not reset | CON-2105 keeps `received_at` 18:07:30 (22 min 30 s at 18:30) and is not new demand (Oak Valley stays at 1 arrival) |
| Future records | stored, then shown as "not yet ingested" until the simulation clock reaches their `ingested_at` ("now" never jumps by itself) |

## 7. Changes made

- `backend/app/engines/consultation_state/engine.py`: a repeated `consult_received` for a
  consult that is already open (the hospital calling again) is now labelled
  `repeat_request` ("same patient, counted once, waiting time still runs from the first
  request"). It was labelled `received_out_of_sequence`, which the consult panel displayed
  as a data-ordering error. Behaviour was already correct: no clock reset, no double
  demand.
- No change to coverage, eligibility, time-zone or import logic. Nothing confirmed a bug
  there.

## 8. Open specification questions

1. **Look-ahead for "a hospital that is short"** (decides the eligible count; section 5).
   The brief says "at least 90 minutes". The dashboard uses 90 and the staffing default is
   240. Options:
   - **240 (current).** Two eligible; PHY-010 is offered for Redwood's 21:00 gap.
   - **120 (the minimum offer length).** Exactly PHY-009; reproduces the handbook. The
     argument for it: decide now only the gaps that a minimum-length offer made now could
     reach. Note this value was chosen knowing the answer it gives.
   - **90 (same as Detect).** The dashboard and staffing agree. Nobody at 18:20; PHY-009
     alone from 18:31.
2. **Meaning of "available"** in the coverage rule. Resolved by evidence (section 2), but
   not stated explicitly in the brief.
3. **Surge projection.** The +1 ends when known arrivals leave the window (19:04:30 at
   Suncrest). Assuming the surge continues would create a Suncrest gap at 20:00.
4. **ET labels on baselines** whose curves look the same in every zone (section 1).
5. **Night physicians with unknown shift ends** (PHY-011, PHY-012) are counted as
   uncertain coverage through the horizon.
6. **Temporarily Unavailable** (PHY-008) is assumed to last the whole horizon; no return
   time is given.
7. **"Each fails one rule".** PHY-012 fails two rules (opt-in and overlap) under every
   reading, and PHY-013 fails two under capacity.
8. **Display.** An open-notes alert whose consults span several zones prints the shift end
   in UTC (e.g. "23:00 UTC" for 19:00 ET). The instant is correct; only the zone is
   unhelpful.
9. **"Should move up the list".** A repeat call keeps its original clock, so it ranks by
   its full wait. There is no separate priority boost.
