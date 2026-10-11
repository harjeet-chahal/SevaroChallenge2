# Voluntary availability: benchmark on the official dataset

What does "I'm Available" change when the official Challenge 2 dataset (`data/`) runs
through the whole Detect → Decide → Act loop? This compares the pipeline without the
feature, the feature as shipped, and a one-rule extension that is **not** in the product.

Script: `backend/scripts/benchmark_voluntary.py` (run it with the command in section 7).
Run: 200 simulated days per arm, same days in every arm (paired), 2026-10-11.

## 1. Bottom line

- **As shipped, the feature helps a little on this dataset.** It fills 21% more gaps
  (0.54 → 0.65 per day), cuts offers per filled shift by 20% (7.6 → 6.1) and closes 25% more
  of the gap (37.5 → 46.7 physician-minutes per day). It sends only 3% fewer offers. On 132
  of 200 days it changes nothing at all. It is never worse than the normal pipeline.
- **It does not reduce computation.** When a volunteer could help, the optimizer runs a
  second CP-SAT solve: 12 objective stages instead of 6 and 16 offer options instead of 10. One
  staffing run goes from about 17–21 ms to 31–33 ms (about 1.7×, measured alone; see section
  3). That happens in under 1% of dashboard refreshes here, so over a day it is +15% CP-SAT
  solves in the workflow and +4% optimizer time (2.71 s → 2.82 s). Optimizer compute is under
  3 s per simulated day in every arm, so it is not where cost lives.
- **The cost that matters is outreach**: each offer means a coordinator proposal, a
  clinical-lead approval, a message to a physician, one of that physician's 3 offers per
  week and up to 10 minutes of waiting. The shipped feature trims it by 3% per day, or 20% per
  filled shift ($68 → $54 at the assumed $8.93 per round).
- **The savings appear with one more rule: do not cold-offer a volunteer outside the times
  they shared.** In that case offers drop 41%, wasted offers 56%, approvals 41%, workflow API
  calls 40%, workflow optimizer runs 41% and workflow CP-SAT solves 21%. Filled gaps rise 52%
  and the gap closed rises 45%. Offers per filled shift go from 7.6 to 2.9.

## 2. Why the shipped feature changes so little here

1. **One eligible doctor per gap.** Over the day the only gaps with someone to ask are
   Redwood (Dr. Alvarez, PHY-010) and, from 18:31, Northfield (Dr. Okafor, PHY-009). Nobody can
   be asked for Cedar Ridge or Bluewater. Volunteering is a ranking preference, and a preference
   among one candidate cannot change who is asked.
2. **A shared window is never a "don't ask" signal.** Alvarez is offered Redwood's daytime
   surge gaps (11:30, 14:10) even if he shared only an evening window. Those offers are
   declined or expire, and they use his 3 offers per week. On 163 of 200 normal days (157 with the
   feature) he received 3 or more offers, which exhausted his quota before Redwood's 21:00 gap.
   With the extra rule this happens on 73 of 200 days.
3. **The 85% coverage tolerance.** A window that starts exactly when the gap starts cannot hold a
   valid offer after the 10 minutes to come online. Example: Alvarez sharing 21:00–24:00 gets
   `no_offer_fits`, so he is still cold-offered 20:40–22:50.

Where it does help, the effect is real and comes from the engine. On 12 of the 23 days where
the feature filled more gaps, the optimizer re-fitted the offer inside the window. Example: Okafor
shares 20:00–24:00. Without the feature he is offered 19:35–22:00, which starts outside his
window. With it he is offered 20:00–22:15, which covers 105 of Northfield's 120 gap minutes
and costs $450 instead of $483. The other 11 days come from the assumed higher reply rate for
an offer inside a shared window.

## 3. Results (mean per simulated day, 09:00–24:00 ET; 95% bootstrap CI of the paired difference)

| | Normal | Feature (shipped) | Δ | Feature + respect windows (what-if) | Δ |
| --- | ---: | ---: | ---: | ---: | ---: |
| Offers sent to physicians | 4.07 | 3.93 | −3% [−0.19, −0.09] | 2.38 | −41% [−1.86, −1.51] |
| Wasted offers (declined + expired) | 3.52 | 3.28 | −7% [−0.32, −0.17] | 1.56 | −56% [−2.17, −1.76] |
| Proposals = clinical-lead approvals | 4.07 | 3.93 | −3% | 2.38 | −41% |
| Shifts accepted (gaps filled) | 0.54 | 0.65 | +21% [+0.07, +0.16] | 0.81 | +52% [+0.22, +0.34] |
| Offers per filled shift | 7.60 | 6.05 | −20% | 2.92 | −62% |
| Acceptance rate per offer | 13% | 17% | | 34% | |
| Gap closed (physician-minutes) | 37.5 | 46.7 | +25% | 54.3 | +45% |
| Gap remaining (physician-minutes) | 295.3 | 286.1 | −3% [−12.7, −6.1] | 278.6 | −6% [−20.9, −13.0] |
| Minutes from detection to acceptance | 7.0 | 2.2 | | 4.1 | |

With no split shift at all the day has 332.8 physician-minutes of gap. Most of it cannot be
closed by any arm. Cedar Ridge (60) has nobody eligible. Bluewater (5) is too short for a 2-hour
offer. Okafor and Alvarez decline or ignore offers on many simulated days.

**Computation** (backend in-process; "workflow" = propose, approve, send, respond and the clock
sweep; "dashboard" = the coordinator's split-shift view refreshed every 5 simulated minutes):

| | Normal | Feature | Δ | What-if | Δ |
| --- | ---: | ---: | ---: | ---: | ---: |
| Workflow API calls | 15.1 | 14.8 | −2% | 9.0 | −40% |
| Workflow optimizer runs | 8.13 | 7.86 | −3% | 4.76 | −41% |
| Workflow CP-SAT solves | 8.13 | 9.34 | **+15%** | 6.45 | −21% |
| Workflow CP-SAT solves per filled shift | 15.2 | 14.4 | −5% | 7.9 | −48% |
| Workflow optimizer time | 208 ms | 239 ms | +15% | 150 ms | −28% |
| Workflow backend time | 707 ms | 733 ms | +4% | 491 ms | −31% |
| Dashboard: optimizer time per refresh | 13.7 ms | 14.1 ms | +3% | 15.5 ms | +13% |
| All optimizer time per day | 2.71 s | 2.82 s | +4% | 2.97 s | +10% |

One staffing run measured alone (40 repeats, median, official data):

| Clock (ET) | Shared window | Staffing run | CP-SAT stages | Offer options |
| --- | --- | ---: | ---: | ---: |
| 18:35 | none | 17.4 ms | 6 | 10 |
| 18:35 | Okafor 20:00–24:00 | 31.2 ms | 12 | 16 |
| 19:35 | none | 21.0 ms | 6 | 14 |
| 19:35 | Okafor 19:30–23:30 | 32.8 ms | 12 | 17 |

The what-if's dashboard refreshes cost more because Alvarez keeps his quota, so there is still a
real plan to optimize later in the day. In the normal pipeline he is used up early, and an empty
candidate list is cheap to solve.

**Cost** (paid time uses the cost policy's $200/h; outreach is an ASSUMPTION of $8.93 per
round: coordinator 3 min at $45/h, clinical lead 2 min at $200/h, $0.01 message):

| | Normal | Feature | Δ | What-if | Δ |
| --- | ---: | ---: | ---: | ---: | ---: |
| Outreach per day | $36.30 | $35.09 | −3% | $21.25 | −41% |
| Outreach per filled shift | $68 | $54 | −20% | $26 | −61% |
| Paid split-shift time per day | $243 | $295 | +21% | $367 | +51% |
| Total per gap physician-minute closed | $7.46 | $7.07 | −5% | $7.16 | −4% |

Paid time rises because more gaps are actually covered. Per minute of gap closed, the total
cost is flat to slightly lower.

## 4. Sensitivity (40 paired days per setting; one assumption changed at a time)

Each cell: offers sent / gaps filled / gap closed / workflow CP-SAT solves, change against the
normal pipeline under the same assumption. Days are paired; 40 days is a small sample, so read
the direction, not the second digit.

| Assumption changed | Normal: offers / fills / gap closed per day | Feature (shipped) | What-if |
| --- | --- | --- | --- |
| Base (main run, 200 days) | 4.07 / 0.54 / 37.5 | −3% / +21% / +25% / +15% | −41% / +52% / +45% / −21% |
| Cold reply rate 0.5 | 4.58 / 0.28 / 21.0 | −7% / +55% / +43% / +5% | −44% / +127% / +88% / −30% |
| Cold reply rate 0.9 | 3.77 / 0.53 / 32.4 | −1% / +14% / +21% / +17% | −38% / +19% / +22% / −21% |
| Willing 0.3 | 4.15 / 0.25 / 15.9 | −2% / +10% / +22% / +4% | −18% / +30% / +41% / −10% |
| Willing 0.9 | 3.90 / 0.65 / 36.2 | −6% / +19% / +27% / +16% | −63% / +54% / +55% / −36% |
| Adoption 0.5 (half the willing share) | 4.10 / 0.45 / 27.3 | −3% / +6% / +9% / +7% | −25% / +17% / +20% / −14% |

The pattern holds under every assumption. The shipped feature fills more gaps, sends slightly
fewer offers and always costs more CP-SAT solves. The what-if always cuts offers and solves.
Its advantage grows when cold offers are ignored more often and when more physicians volunteer.

## 5. Method

- **Real system, real loop.** The FastAPI app runs in-process on a throwaway SQLite copy of
  the imported official dataset. Each simulated day sets the clock to 09:00 ET and moves it
  in 5-minute steps, plus the exact minute of each reply, to 24:00. Every step:
  1. The scripted physicians answer due offers through `POST /api/offers/{id}/respond`.
  2. The coordinator refreshes the dashboard (`GET /api/optimization/split-shifts`).
  3. For each recommended shift at a short hospital, the coordinator proposes it
     (`POST /api/interventions`), the clinical lead approves it and the offer is sent. Only the
     primary physician is asked; no backups are added.
  4. The clock moves (`POST /api/simulation/advance`), which expires offers and activates
     accepted shifts.

  Eligibility, the 10 h rest rule, the 60 h limit, no-overlap, 1 open and 3 weekly offers,
  declines, 10-minute expiry, activation and the coverage overlay all come from the system.
  Human steps take no time, which favours the normal pipeline: real approval delays make each
  wasted round costlier.
- **Arms.** *Normal*: `voluntary.enabled = false`, nothing shared. *Feature*: each willing
  physician shares their window at 09:00 through `POST /api/availability`; the system as
  shipped. *What-if*: as Feature, but the coordinator skips a recommendation whose offer lies
  outside the windows that physician shared (the ranking card already says so).
- **Ground truth (ASSUMPTION; the dataset has no response data), identical in every arm.**
  - Each opted-in off-shift physician (PHY-009, -010, -011, -014) is willing to work today with
    probability 0.6.
  - A willing physician has one window: it starts at a uniformly random half hour from 09:00
    to 20:00 and lasts 4–8 h.
  - An offer is accepted only if it lies entirely inside that window.
  - A cold offer gets a reply within 10 min with probability 0.7, after 1–9 min; otherwise it
    expires.
  - An offer inside a window the physician shared gets a reply with probability 0.95, after
    1–3 min.
  - Random draws are keyed by (day, physician, k-th offer), so every arm sees the same luck.
- **Measured, not assumed:** offers and outcomes, proposals, approvals, API calls, optimizer
  runs, CP-SAT solves and stages, wall time, gap physician-minutes (Phase 3 coverage engine
  with accepted and active shifts) and paid minutes. Optimizer timings ran with 10 benchmark
  processes in parallel on one machine, so treat the absolute milliseconds as approximate and
  the ratios as the result.

## 6. Limitations

- The response model drives everything that is not measured. Section 4 varies it.
- The what-if assumes a shared window is complete: physicians in it never accept work outside
  their window. If they sometimes would, the rule gives up some coverage.
- The dataset has a tiny off-shift pool, at most two eligible physicians at any time. With
  more volunteers competing for the same gap, the ranking preference itself would matter more.
- Daytime Redwood gaps are surge gaps of 30–55 minutes. The system offers 2 h 10 min for them,
  which inflates paid time in every arm equally.

## 7. Reproduce

```bash
cd backend
.venv/bin/python -m scripts.benchmark_voluntary --runs 200 --workers 10 --out /tmp/voluntary.json
```

Options: `--willing`, `--reply-cold`, `--reply-vol`, `--adoption` (share of willing
physicians who use the portal) and `--seed-offset`. About 23 CPU-seconds per simulated day per
arm.
