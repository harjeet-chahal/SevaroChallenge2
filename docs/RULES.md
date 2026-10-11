# NEUROGRID rules

These rules extend the existing ones. For the earlier phases, see
[event-processing.md](event-processing.md) (replay and availability precedence),
[risk-and-coverage.md](risk-and-coverage.md) (alert thresholds and coverage) and
[optimization.md](optimization.md) (routing and split-shift eligibility). Where the brief
and the NEUROGRID specification disagree, **the brief wins**, and the specification's
version is kept only as a labelled proposal.

## Availability classes

The Phase 2 engine picks an availability using the precedence rules R1–R10. The NEUROGRID
class is a mapping of that decision, not a second decision.

| Rule | Class | Evidence | Auto-routable (brief) |
| --- | --- | --- | --- |
| R1 active Synapse call | BUSY_CALL | CONFIRMED | no |
| R2 active Synapse video | BUSY_VIDEO | CONFIRMED | no |
| R3 not on shift | OFF_SHIFT | CONFIRMED | no |
| R4 Temporarily Unavailable | UNAVAILABLE | CONFIRMED | no |
| R5 camera on, no Synapse video, not In Meeting | PROBABLY_BUSY_EXTERNAL | LIKELY | no ("treat as busy and flag") |
| R6/R7 In Meeting | INTERRUPTIBLE_MEETING | LIKELY | yes ("internal meetings are interruptible") |
| R8 desktop agent offline | UNCERTAIN | STALE | **yes** ("routing assumes available, but this is unverified") |
| R9 documentation, R10 default | AVAILABLE | CONFIRMED (weakened by inferred or assumed signals) | if rules 2–5 pass |

- **Brief versus specification.** The specification says not to auto-route UNCERTAIN.
  The brief says routing assumes the physician is available. NEUROGRID follows the brief,
  sets `needs_confirmation`, and shows "confirm before routing" only as a proposed policy.
  This is pinned by `test_every_physician_gets_exactly_one_class_with_evidence` and the
  `missing_agent` chaos scenario.
- **When confirmation is needed.** A physician needs confirmation when the evidence is
  STALE or UNCERTAIN, or when the busy state comes only from the camera. If a manual
  status disagrees with a confirmed Synapse call, the call is not in doubt.
- **Not probabilities.** The evidence labels are categories, not calibrated
  probabilities.

## Problem priority (alert grouping)

1. A critical stroke consult delay, or an unroutable stroke consult.
2. Other stroke warnings, or a stroke stage that turns critical within 5 minutes.
3. A coverage shortfall now.
4. A projected coverage shortfall.
5. A critical delay on a general consult, or physician workload at shift end.
6. Signals, demand and everything else.

Within a tier, problems are ordered by a transparent weighted tie-breaker:

    3·SLA share + 0.2·min over critical + 0.5·routing failures + 0.3·affected
      + coverage risk + 2·imminence + 0.2·certainty

Remaining ties are broken by the fingerprint. Alerts are grouped by
`sha1(kind|scope)`. For a hospital, its coverage-gap, routing-failure, triaged-unassigned
and surge alerts form one group. Consult alerts are grouped per consult, and workload and
signal alerts per physician. Every member alert stays listed, critical ones first.

## Last Safe Moment

**Planning versus action.** NEUROGRID forecasts candidate capacity over 240 minutes;
operational staffing targets must have a gap starting inside the configured shortage
look-ahead (90 minutes by default). A gap exactly at that window's end is excluded.
Future deadlines and simulated rescue impacts remain visible, but candidates are not
sendable and their preview options cannot create contracts yet. Approval and dispatch
still use the operational planner and revalidate every rule. Scarcity and Load Guardian
reports are planning what-ifs, not permission to contact a physician.

    lead_conservative = approval (5) + full offer life (10, brief) + time to come online (roster)
    lead_expected     = approval (5) + expected reply (4) + time to come online
    latest_initiation = shortfall_start − lead_conservative

- **No double-counting.** The steps run one after another, so they do not overlap. The
  conservative reply uses the full 10 minutes instead of the expected reply time.
- **Two sets of rules.** Rest, weekly hours, overlap and minimum length are checked at the
  offered start, because the brief says rest is "measured at the offered start time".
  Send-time rules (open offers, the weekly limit) are checked now.
- **When the start cannot be covered.** If the earliest valid start plus the time to come
  online falls after the shortfall, the candidate can only mitigate it, not prevent it.
- **Phases.** The phase is green when more than 30 minutes remain, red at 10 minutes or
  less, and amber in between. It is "missed" when time has run out but candidates exist,
  and "no_candidate" when nobody can cover.
- **Simulation clock only.** Everything runs on the simulation clock and never ticks in
  wall-clock time.

## Network fragility

- **Single-point failure.** The physician's coverage windows are removed from an
  isolated copy of the models, and the deficit integral is recomputed exactly.
- **Criticality score.** The score is a weighted sum:

      10·added deficit hours + 6·newly uncovered hospitals + 4·sole-coverage hospitals
        + 0.5·relevant credentials

  The weights live in `IntelligenceConfig`.
- **Exclusive allocation.** Each required position is matched to at most one physician
  using a maximum bipartite matching (Hopcroft-Karp). This is reported next to the
  brief's per-hospital pool definition, which stays authoritative.

## Coverage Genome

Each factor is a count taken at the moment the problem occurs.

| Factor | How it is counted |
| --- | --- |
| Credentialing | Spare physicians elsewhere who are not credentialed here, capped at the deficit |
| Capacity | The remaining deficit, plus the surge +1 |
| Shift collision | Credentialed shift ends in the 30 minutes before, capped at the deficit |
| Uncertainty | Temporarily Unavailable credentialed physicians, plus the extra deficit when only confirmed capacity is counted |
| Routing failure | Stranded consults, counted twice when nobody is routable |
| Workload | Share of credentialed physicians who are busy, times the number of stranded consults |
| Documentation | 0.25 per open note, capped at 0.5 |

The counts are normalised to shares. When the top two shares are within 15% of each
other, the diagnosis is MULTI_FACTOR. Strategic suggestions are planning items only and
never relax credentialing.

## Scarcity

For every gap hospital a backup could help, the score adds:

    urgency (now 3, ≤ 90 min 2, later 1) × (3 if sole eligible backup else 1/(1+alternatives))

A backup is marked "preserve" when it is the only option for one hospital and an
alternative for another. Scarcity only orders options that are already safe. It never
overrides a hard rule or an active critical stroke escalation.

## Rescue simulator objective (lexicographic)

Options are compared on these criteria in order:

1. Invalid, unauthorized or simulation-only options rank last.
2. The smallest remaining target deficit.
3. The fewest new shortfalls elsewhere.
4. The smallest network deficit.
5. The least workload on the joining physician beyond the peer median (modelled).
6. The fewest physicians contacted.
7. The earliest activation.

Shift extensions are always simulation-only, because the data has no authority to extend
shifts and no rest or weekly-hour data for on-shift physicians. When nothing improves the
target, escalation is recommended if a gap or stranded consult exists; otherwise "do
nothing" is.

Split shifts outside the operational staffing action window also remain simulation-only.
Their before/after impacts and combined planning options are retained, but no proposal
payload is returned. Actionable options use the operational planner's validated windows.

## Rescue contract phases (derived from intervention status)

| Intervention status | Contract phase |
| --- | --- |
| proposed | PROPOSED |
| pending_approval | AWAITING_APPROVAL (REVALIDATION_REQUIRED if the data version changed) |
| approved (split shift) | READY_TO_DISPATCH (or REVALIDATION_REQUIRED) |
| approved (escalation) | ESCALATED |
| rejected | REJECTED |
| offer_sent | RESPONSE_PENDING |
| accepted | ACTIVATION_PENDING (accepted is not online) |
| activated / completed | ACTIVE, then RESOLVED, PARTIALLY_RESOLVED, FAILED or VERIFYING, depending on verification |
| declined | FAILED |
| expired | EXPIRED |
| cancelled / no_longer_required | CANCELLED |

Transitions are enforced by the existing state machine (`engines/interventions/machine.py`).
An invalid transition returns 409 `invalid_transition`.

**Verification.** For an active rescue, the target deficit over the rescue interval is
computed from current state, both with and without the rescue physician. The verdict is:

- **resolved** when the target deficit is 0 and the plan caused no new critical deficit
  elsewhere;
- **partially_resolved** when the deficit is lower than without the rescue;
- **failed** otherwise.

A pending or accepted offer is never verified.

## Decision Freshness Lock

The existing workflow revalidates the plan on approval and on dispatch. It rechecks
eligibility, offer limits, rest, weekly hours and overlap, and whether the gap still
exists counting accepted shifts. A stale plan is blocked or closed as
`no_longer_required`, and the outcome is audited. NEUROGRID adds the
REVALIDATION_REQUIRED phase and a clinical-lead banner whenever the data version has
changed since the proposal. Acceptance uses idempotency and a check that the remaining
need still exists, so a simultaneous second acceptance is marked redundant.
