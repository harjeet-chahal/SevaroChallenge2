# Risk detection, demand spikes & coverage forecasting (Phase 3)

One pure entry point computes everything from the event log and reference data:

```python
from app.engines.analysis import analyze
analysis = analyze(events, reference, as_of, config)   # alerts, coverage, demand, metrics
```

It is deterministic (same inputs → same outputs, regardless of event order), never reads
the wall clock, and never uses an event that is not yet visible at `as_of`. All thresholds
and policies live in `backend/app/engines/rules/config.py` and can be overridden with a JSON
file pointed to by `RISK_RULES_FILE`. Each rule is tagged **from the brief** or
**assumption**, and every alert carries that tag.

## 1. Alert rules

| Rule code | Condition | Warning | Critical | Source |
| --- | --- | --- | --- | --- |
| `STAGE_TRIAGED_UNASSIGNED` | Triaged, not yet assigned — all consults | ≥ 5 min | ≥ 10 min | Brief table |
| `STAGE_ASSIGNED_NOT_CONTACTED` | Assigned, physician not yet contacted — Stroke | ≥ 3 min | ≥ 8 min | Brief table |
| `STAGE_IMAGING_PENDING` | CT/CTA or Imaging Pending — Stroke | ≥ 12 min | ≥ 20 min | Brief table |
| `STAGE_IMAGING_REVIEW` | Imaging Review (imaging back, video not started) — Stroke | ≥ 6 min | ≥ 12 min | Brief table |
| `NOTE_OVERDUE` | Note Pending + Documentation, from end of video or call — Stroke | ≥ 30 min | ≥ 45 min | Brief table |
| `NOTE_OVERDUE` | same — General Neuro | ≥ 45 min | ≥ 90 min | Brief table |
| `OPEN_NOTES_NEAR_SHIFT_END` | Open notes (Note Pending/Documentation) with ≤ 60 min to shift end | any (≥ 1) | ≥ 2 | Brief table |
| `COVERAGE_GAP_NOW` | available credentialed < required now | — | always | Brief (gap rule); severity assumed |
| `COVERAGE_GAP_PROJECTED` | gap starts within the horizon | always | — | Brief (gap rule); severity assumed |
| `DEMAND_SPIKE` | trailing-60-min arrivals > hourly p90 | always | — | Brief (spike rule); severity assumed |
| `SIGNAL_EXTERNAL_VIDEO` | camera on, no Synapse, not In Meeting | info | — | Brief ("flag it"); severity assumed |
| `SIGNAL_AGENT_OFFLINE` | desktop agent offline | always | — | Brief ("surface the risk"); severity assumed |
| `ASSIGNED_PHYSICIAN_UNAVAILABLE` | open consult's physician unavailable or off shift | other cases | Stroke before documentation | **Assumption** (situation listed, no threshold) |
| `ROUTING_FAILURE` | unassigned consult with ≥ 1 `routing_attempt_failed` | always | — | **Assumption** (event defined, no threshold) |

Thresholds use **≥**: an alert fires *at* the documented minute, never a second
before (tested to the second). Stage clocks start at stage entry. The note clock starts
at the Note Pending entry of the current note phase (the end of the video or call that
ended the clinical work; a provisional Note Pending that imaging or video later superseded
never counts) and keeps running through Documentation. Consults of unknown type are
evaluated only against "All" standards, and this is stated in `notes`. "Received, not yet
triaged" has no standard, unless routing has visibly started (a ring or a failed routing
attempt): the consult is then timed against "Triaged, not yet assigned" from the first
routing activity. Notes still open after a shift has ended stay flagged as critical, and a
consult owned by a physician whose shift ended is flagged even if that physician is still
on another call (not if the call is for that consult). A current gap's start is not known
from the forward-looking forecast, so its alert has no "since" time.

Recommended action categories (never executed): `reassign_consult`, `escalate`,
`contact_physician`, `propose_split_shift`, `monitor`, mapped per rule and severity in the
config. A reassignment is recommended only if another credentialed on-shift physician is
free to take the consult now (available, not ringing for another call); otherwise the alert
recommends `escalate` and names who was checked and why each cannot take it.

**Identity.** `alert_id = RULE_CODE:entity_kind:entity_id` (e.g.
`STAGE_TRIAGED_UNASSIGNED:consult:DEV-C109`). It is stable while the issue persists, even
as severity escalates, and disappears when the condition clears.

## 2. Prioritisation

Lexicographic key, most significant first (`alert_detection/rank.py`):

1. **severity** — critical, warning, info (hard safety precedence)
2. **category** — 0 stroke consult at risk · 1 coverage gap now · 2 other consult at risk ·
   3 projected gap · 4 open notes near shift end · 5 demand spike · 6 signal conflict
3. **repeat calls** — the hospital called again about this consult (same patient,
   counted once, clock not restarted): more repeat calls first, as the brief asks
4. **urgency** — time rules: elapsed ÷ critical standard; projected gaps: imminence;
   current gaps: deficit physician-minutes
5. **coverage risk** — the alert's hospital has a gap now (2) / projected (1) / none (0)
6. **affected** — consults or items touched
7. `alert_id` — stable tie-break

Workload factors (3–6) can never lift an alert above a higher severity or a more
safety-critical category. Every alert returns `priority`, the structured `rank` and
`priority_reasons` in words.

## 3. Demand spikes

> "A demand spike (trailing 60-minute consults above the hospital's p90 baseline for that
> hour) raises the requirement by one." — brief

- **Arrivals** are distinct consults whose `consult_received` `event_time` lies in
  **(t − 60 min, t]**. They come from the replayed state, so duplicates can never count
  twice and only events visible at the simulation time are used.
- **"That hour"** is the hospital-local clock hour containing *t* (IANA zone, DST-aware),
  matched to `baseline_hourly_volume.hour`. A window can span two hours; the hour
  containing *t* decides.
- **Spike** when arrivals **>** p90 (strictly above). The requirement rises by 1.
- **Missing baseline** gives `baseline_status: "missing"` and `spike: null`. No value is
  substituted, and the forecast is marked uncertain.
- **Day type:** if a hospital's baseline rows carry one day type it is used, and a
  weekday/weekend mismatch is flagged. If they carry several, the matching
  weekday/weekend label is chosen; otherwise the result is "ambiguous".
- **Forecast:** at future instants only arrivals already known count (a lower bound), so
  a projected spike ends when known arrivals age out (`spike_ends_at`). Future arrivals
  are never fabricated.

## 4. Coverage forecast (≥ 90 min)

Deterministic piecewise-constant simulation (`coverage_prediction/forecast.py`):

```
R(t) = base requirement of the local time block containing t  (+1 while a spike is active)
A(t) = distinct physicians credentialed at the hospital whose contribution window contains t
deficit(t) = max(0, R(t) − A(t))
deficit physician-minutes = Σ deficit × segment length   (exact, over half-open segments)
```

**Change points:** simulation time, horizon end, every shift start/end, local
coverage-block boundaries (both occurrences in a repeated DST hour, none in a skipped
one), local hour boundaries, arrivals leaving the spike window, and UTC-offset
transitions. R and A are constant between change points, so the integral is exact.
Regular 5-minute samples are added for the chart only.

**Who counts (contribution windows):**

| Situation | Counted? | Certainty |
| --- | --- | --- |
| On-shift roster, within scheduled shift | until scheduled end | confirmed |
| On shift by `shift_started` event, no scheduled end | through the horizon | **uncertain** (end unknown) |
| Off-shift roster, `next_shift_starts_at` within horizon | from that time | **uncertain** (end unknown) |
| Busy (call / video / external video) | yes — on duty | unchanged |
| Temporarily Unavailable now | **no**, for the whole horizon (no return time known) | — |
| Agent offline / agent online only inferred | yes | **uncertain** |
| Not credentialed at the hospital | **no** (listed with reason) | — |
| Credentialed at several hospitals | yes, at **each** (non-exclusive, as the brief defines coverage) | — |

Unknown shift ends are never replaced with made-up times. Deficits are reported both
with all counted physicians and with confirmed coverage only
(`deficit_physician_minutes_if_uncertain_excluded`).

**Metrics per hospital:** required now, available now, deficit now, first shortfall time,
minutes until it, shortfall duration, worst deficit, deficit physician-minutes (modeled),
and confidence (`confirmed` / `uncertain` / `unknown`) with reasons.

**Explanations** are deterministic templates over the computed segments, e.g.
"Dr. Quinn Surge and Dr. Reese Surge's shifts end at 19:00 EDT, reducing available
coverage from 3 to 1." or "No usable p90 baseline for 17:00–18:00 CDT (missing); the
demand-spike adjustment cannot be evaluated."

These figures are **modeled** from schedules, credentials and current signals. They are
not measured patient outcomes.

## 5. Time-zone evidence

- Sample dataset: the local-hour baselines resolve to `17:00 EDT` (New York), `16:00 CDT`
  (Chicago), `15:00 MDT` (Denver), `14:00 MST` (Phoenix, no DST) and `14:00 PDT`
  (Los Angeles) for the same instant (2030-05-14 21:30Z).
- Tests: NY and LA requirement blocks change at their own 19:00 (23:00Z vs not in
  horizon). On DST fall-back (2031-11-02) the 01:45 block boundary occurs at both 05:45Z
  and 06:45Z. On spring-forward (2031-03-09) the non-existent 02:30 boundary takes effect
  at the 07:00Z jump. The baseline hour stays 1 for both 01:30 EDT and 01:30 EST.

## 6. Optimizer-ready interface (for Phase 4)

`GET /api/optimization/input` (`engines/optimization_input`) exposes data only:
hospital deficit intervals (exact segments), physician credentials, availability,
workload, schedule boundaries, open notes, roster attributes, consult urgency, waiting
time, next threshold time and credentialed on-shift pool, and **candidate interventions
with their coverage effect**. Each candidate is the deficit physician-minutes saved if an
off-shift physician came online after their time-to-online. Split-shift eligibility is
deliberately not evaluated. `ConsultMatcher` / `StaffingOptimizer` Protocols define
where OR-Tools solvers plug in. Coverage counting is non-exclusive per the brief; an
exclusive one-physician-one-place constraint is a Phase 4 modelling choice. The Phase 4
optimizers are documented in [optimization.md](optimization.md).

## 7. API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/alerts?as_of=&severity=&rule_code=&hospital_id=&limit=` | ranked alerts (global priorities kept when filtered) |
| GET | `/api/alerts/{alert_id}?as_of=` | one alert (404 if not active) |
| GET | `/api/coverage?as_of=&horizon_minutes=(90–720)&step_minutes=` | all hospitals |
| GET | `/api/coverage/{hospital_id}` | one hospital with segments, points, annotations, explanations |
| GET | `/api/demand?as_of=` | arrivals vs hourly p90 per hospital, exact comparison text |
| GET | `/api/metrics?as_of=` | summary: physicians, consults, alerts, coverage, demand, workload |
| GET | `/api/optimization/input?as_of=` | Phase 4 snapshot (read-only) |
| GET | `/api/datasets/samples` · POST `/api/datasets/sample?name=` | choose a bundled sample |

All default to the simulation clock and use the standard error envelope. Results are
cached per (`data_version`, `as_of`, horizon, step, rules signature), so a new event, an
import, or a clock move always recomputes.

## 8. Assumptions that may differ from the judging dataset

- What "available" means for the coverage rule: busy physicians count; Temporarily
  Unavailable physicians stay excluded for the horizon.
- Severities for gap, spike, signal, routing-failure and assigned-unavailable alerts.
- The spike window is half-open (an arrival exactly 60 min ago no longer counts), and
  the spike comparison is strictly greater.
- The note clock runs from the Note Pending entry of the current note phase. Phone-only
  Note Pending is inferred from the call end (Phase 2).
- Overlapping coverage blocks use the maximum requirement. A hospital with no block at a
  time has "no requirement" and so no gap.
- Off-shift physicians are counted from `next_shift_starts_at` with an unknown end.
