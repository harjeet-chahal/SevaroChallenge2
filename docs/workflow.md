# Intervention workflow (Phase 5): Detect → Decide → Act

Phase 5 turns recommendations into a human-approved workflow across three views:

- the **coordinator** proposes;
- the **clinical lead** approves or rejects;
- the **off-shift physician** accepts or declines on a phone-sized screen.

The backend is authoritative for every state change. The frontend only renders what the API returns and calls transition endpoints. Each intervention carries `allowed_actions`, so a button appears only when the server would accept that action.

Code:

- `backend/app/engines/interventions/`: pure state machines, policy, overlay and offer privacy.
- `backend/app/services/workflow.py`: orchestration, transactions and audit writes.
- `backend/app/services/workflow_records.py`: audited transitions and the re-import closure.
- Routes in `backend/app/api/routes/{interventions,offers,live}.py`.
- Tests in `backend/tests/test_workflow.py`.

## 1. Simulated identity (not authentication)

Every workflow call carries `X-Demo-Role` (`coordinator`, `clinical_lead` or `physician`) and optionally `X-Demo-Actor-Id`. For a physician this is their physician ID, and it is required. Role checks happen at the API layer (403 `permission_denied`), not just in the UI. The `system` role marks automatic policy steps in the audit log and is refused if a client sends it.

**This is a clearly labelled demo stand-in, not production authentication.**

| Action | coordinator | clinical_lead | physician |
| --- | :-: | :-: | :-: |
| Preview / propose an intervention | ✓ | | |
| Approve / reject (split shift, escalation) | | ✓ | |
| Send approved offers (simulated) | ✓ | ✓ | |
| Apply a consult reassignment | ✓ | | |
| Resolve an escalation | ✓ | ✓ | |
| Cancel an intervention / withdraw an offer | ✓ | ✓ | |
| Simulate a physician going online | ✓ | | own offer |
| See / answer offers | all (read) | all (read) | own only |
| Read interventions and the audit log | ✓ | ✓ | |

## 2. State machines

Every status change goes through `require_transition` / `require_offer_transition`. Anything not listed is refused with 409 `invalid_transition`, whatever the role.

```
split_shift   pending_approval → approved | rejected | cancelled | no_longer_required
              approved         → offer_sent | cancelled | no_longer_required
              offer_sent       → accepted | declined | expired | cancelled | no_longer_required
              accepted         → activated | cancelled
              activated        → completed | cancelled
escalation    pending_approval → approved (authorized) | rejected | cancelled | no_longer_required
              approved         → completed (resolved) | cancelled
reassign      proposed         → completed (applied) | cancelled | no_longer_required

offer         sent      → accepted | declined | expired | withdrawn | redundant
              accepted  → active | cancelled
              active    → completed | cancelled
```

- A split-shift intervention's status after sending is derived from its offers (`split_shift_status_from_offers`).
- Submitting a split shift creates `pending_approval`. No offer record exists until a clinical lead approves and someone sends it, so an offer cannot be sent before approval: the transition does not exist (409 `approval_required`).
- A coordinator reassignment needs no clinical approval, because coordinators move consults. Applying it records a simulated Synapse `physician_assigned` event with `source = "workflow"`. That event is distinguishable from imported events and is replayed like any other.

## 3. Persistence (new tables, additive)

| Table | Holds |
| --- | --- |
| `wf_interventions` | Type and status, the problem snapshot, the recommendation with its algorithm and policy version, every candidate evaluated with each rule, the offer plan, impact, trap analysis, reassignment or escalation detail, proposer, simulation and wall-clock times, `version` (optimistic concurrency), `dataset_import_id` |
| `wf_approvals` | One decision per intervention (unique). Records approve/reject, who, simulation time, wall time, note, data version and what was re-validated |
| `wf_offers` | One row per physician offered. Records status, hospitals, routing scope, seeded count, start/end, minutes to come online, generated reason, simulated channel, approver, sender, sent/expires/responded/accepted times, expected online, activation time and source, impact at activation, end time |
| `wf_offer_responses` | Every reply attempt, including duplicates and refused ones, with its outcome and response time in simulated seconds |
| `wf_audit_log` | Append-only. Records simulation time (`occurred_at`), wall time (`recorded_at`), actor, action, intervention/offer, from→to status, summary, details and data version |

The names are new, so existing databases gain these tables additively. `SCHEMA_VERSION` was not bumped, so no developer database is rebuilt. The Phase 1 placeholder tables (`interventions`, `offers`, `audit_log`) were never written to. Existing databases keep them unused; new databases no longer create them.

Database-level invariants:

- a unique decision per intervention;
- a partial unique index allowing at most one `sent` offer per physician.

## 4. Approval and revalidation

Proposal, approval and sending each re-derive everything from the current data. Nothing a client saw earlier is trusted.

- **Preview** (`POST /api/interventions/preview`) is a dry run at the current data version. The coordinator UI refetches it whenever the data version, workflow version or clock changes.
- **Propose** re-runs it and stores the result. `expected_data_version` produces a "data changed — re-validated" warning. An ineligible physician, an offer that fails any rule (including a start in the past), a duplicate open request for the same alert or physician, or no gap at all gives 422 `proposal_invalid` with the reasons.
- **Approve** (clinical lead only) works as follows:
  1. Checks the role.
  2. Applies anything due on the clock.
  3. Requires `pending_approval`. A repeat gets 409 `already_decided`; an `expected_version` mismatch gets 409 `stale_version`.
  4. Re-checks that a coverage gap still exists at the need hospitals, counting accepted shifts.
  5. Re-runs every split-shift rule for each planned offer at its exact start, length and hospitals. This includes ≤ 1 open offer and ≤ 3 per rolling 7 days from the offer log.
  6. Records the decision with approver, simulation timestamp, note and the revalidation lines.
  7. Moves the intervention to `approved`.

  If the gap is gone, the intervention becomes `no_longer_required` (409). If a rule fails, the approval is blocked (409 `revalidation_failed`) and the attempt is audited.
- **Send** requires `approved`. It re-checks the offer limits, rules and remaining useful time, then creates `sent` offers that expire 10 simulated minutes later.

## 5. Offer limits and expiry

| Rule | Implementation |
| --- | --- |
| One open offer per physician | `sent` offers count as open. An accepted, unfinished split shift also blocks new offers to that physician. Checked at proposal, approval and send, and enforced by a partial unique index |
| ≤ 3 offers per week | **Rolling 7 × 24 h** window ending at the simulation time, counting every offer sent (any outcome). Rolling is stricter than a calendar week and needs no week-start convention |
| Expires after 10 min | `expires_at = sent_at + 10 min` (simulation clock). Expiry is applied before any reply, so an expired offer can never be accepted |
| Declined / cancelled / withdrawn cannot be accepted | 409 `offer_declined` / `offer_cancelled` / `offer_withdrawn`. The attempt is still recorded |
| Duplicate replies | Repeating the same answer returns 200 with `idempotent_replay: true` and changes nothing |
| Everything logged | Every attempt goes to `wf_offer_responses` and `wf_audit_log` |

Simulated time passes only when the clock is moved. Every clock move, every workflow request and `POST /api/offers/expire-due` applies what became due, at the exact simulated timestamp: expiry at `expires_at`, activation at the expected online time, completion at `end_at`.

## 6. Conflicting acceptances (two physicians, one gap)

Two physicians can be offered the same gap in two ways:

- one request with backup offers (sent together);
- two requests whose need hospitals overlap.

These are different from two replies to one physician's offer, which are handled by idempotency.

Policy (CHOICE, documented in `engines/interventions/policy.py`):

1. Each acceptance runs in its own serialized transaction: a process lock plus SQLite `BEGIN IMMEDIATE`.
2. An acceptance is **binding immediately** (no second confirmation; the clinical lead already approved) if both of these hold:
   - fewer binding acceptances already serve this need than it requires (`required_physicians` is the peak deficit at the need hospitals, counted across open requests with overlapping hospitals);
   - the forecast still shows a deficit at the offer's hospitals during the time it would cover.
3. Otherwise the acceptance is recorded as **`redundant`**. The physician is released and told so, nothing is activated, and `conflict_detected` and `conflict_resolved` are audited. Valid acceptances are never dropped.
4. As soon as a need is met, every other `sent` offer for it is **withdrawn** with the reason shown on the physician's phone. A later acceptance of a withdrawn offer is still recorded (`redundant_acceptance_recorded`) and returns 409 `offer_withdrawn`.

Tested sequentially (primary plus backup) and concurrently (two threads accepting at once for the same gap). Exactly one binds.

## 7. Activation and recalculation

| Phase | Physician state | Coverage forecast | Routing |
| --- | --- | --- | --- |
| Accepted (preparing) | still off shift | `pending_activation` window from the expected online time. Uncertain, never at "now", never confirmed | not routable |
| Active | on shift until the offer ends | confirmed contributor at the approved scope hospitals only | routable inside the approved scope, with seeded count = seed + consults taken |
| Completed / cancelled | back off shift | removed | removed |

- **Expected online time** is max(offer start, acceptance time) + the roster's minutes to come online.
- **Activation (deterministic simulation):** the physician may press "I'm online" from the phone once the shift has started, or the coordinator may simulate it. Otherwise, when the clock reaches the expected online time, the system activates the physician at exactly that simulated time.
- On activation the system:
  1. updates staffing (overlay);
  2. applies the routing scope;
  3. bumps the data version, so the forecast, alerts, dispatch and staffing optimizers all recompute;
  4. stores the coverage impact before and after;
  5. audits `physician_activated` and `coverage_recalculated`.
- **Overlay.** Accepted and active split shifts are workflow decisions, not source events. `apply_workflow_overlay` layers them onto the replayed state, time-aware by `as_of`, in `/api/state`, every analysis and both optimizers. Source events stay untouched and remain the truth for everything else. Snapshot verification uses the pure replay (`with_workflow=False`).
- **Re-import policy.** A full dataset replacement closes the previous dataset's open items, all audited:
  - sent offers are withdrawn;
  - accepted or active shifts are cancelled, and their overlay stops applying;
  - open interventions become `no_longer_required` (or `cancelled` where the state machine requires it).

  History stays visible with `GET /api/interventions?scope=all`. An event-CSV append (`POST /api/events/csv`, the judging file) is not a replacement and leaves all workflow state intact.
- Moving the clock **backwards** does not undo decisions. Derived staffing applies a workflow fact only from its simulated timestamp onwards.

## 8. Split-shift trap protection (live)

On activation, the Phase 4 protection policy is applied to real routing:

- the routing scope is the credentialed gap hospitals (`routing_scope_hospital_ids`);
- the routing count is seeded (median of on-shift peers covering those hospitals) plus the consults actually taken.

`GET /api/interventions/{id}/impact` reports:

- the intended scope;
- the authorized scope;
- credentials;
- workload before joining (actual and seeded);
- current consults;
- current dispatch proposals to the physician;
- the modeled baseline comparison: unrestricted least-loaded routing vs the protected policy.

This is all simulated within Sevaro Pulse. It does not change Sevaro's production routing.

## 9. Privacy

The physician payload (`PhysicianOfferView`) has a fixed set of fields:

- hospitals;
- start, end and duration;
- minutes to come online and expected online time;
- a generated reason;
- send, expiry and response times;
- status, flags and a message.

The reason is generated from hospital names, the shortfall time and whether demand is surging. Consult IDs, consult types, patient details and the coordinator's note are never included. A defensive check runs on every offer reason, and a test scans the payloads.

## 10. Live updates

`GET /api/live` is a small Server-Sent Events stream. Each connection checks once a second and emits `{data_version, workflow_version, simulation_time, pending_approvals, …}` on change.

- The frontend refreshes `/api/config` when it sees a change, and every keyed resource refetches.
- `data_version` bumps on staffing-relevant decisions (accept, activate, end); `workflow_version` = latest audit id.
- The 15 s config poll remains the fallback.

The Clinical Lead tab shows a pending-approval badge.

## 11. API

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/interventions/preview` | dry run, stores nothing |
| POST | `/api/interventions` | create (201). Split shift → `pending_approval` |
| GET | `/api/interventions?scope=active\|all&status=&type=` | list with `allowed_actions` for the caller |
| GET | `/api/interventions/summary` | counts and versions (no identities) |
| GET | `/api/interventions/{id}` | one intervention, its offers and approval |
| POST | `/api/interventions/{id}/decision` | `{decision: approve\|reject, note, expected_version}` |
| POST | `/api/interventions/{id}/send-offers` | simulated delivery |
| POST | `/api/interventions/{id}/apply` | reassignment |
| POST | `/api/interventions/{id}/resolve` | escalation |
| POST | `/api/interventions/{id}/cancel` | withdraws sent offers, ends accepted shifts |
| GET | `/api/interventions/{id}/impact` | proposed / at activation / now, trap and routing |
| GET | `/api/interventions/{id}/audit`, `/api/audit` | audit log |
| GET | `/api/offers` | all offers (staff) |
| GET | `/api/offers/mine` | the calling physician's offers |
| GET | `/api/offers/recipients` | simulated sign-in list |
| POST | `/api/offers/{id}/respond` | `{response: accept\|decline}` |
| POST | `/api/offers/{id}/activate` | physician online (or coordinator simulation) |
| POST | `/api/offers/{id}/withdraw` | |
| POST | `/api/offers/expire-due` | apply what is due now |
| GET | `/api/live` | SSE version stream (`?once=true` for one event) |

Errors use the standard envelope. Workflow codes include `approval_required`, `already_decided`, `stale_version`, `revalidation_failed`, `no_longer_required`, `proposal_invalid`, `offer_expired`, `offer_declined`, `offer_withdrawn`, `offer_limit_reached`, `shift_not_started` and `invalid_transition`.

## 12. Demo

Load **workflow sample** (`synthetic_workflow`). It is the surge scenario plus a backup candidate, Dr. Yara Surge, and a gap-free hospital, Lakeshore, where the recommended physician is also credentialed. The surge fixture itself is unchanged.

1. Select **Ridge Sample Clinic: coverage gap now** and click **Propose split shift**. Every off-shift physician is shown with every rule; optionally add Yara as a backup.
2. Submit, which creates a pending approval.
3. In **Clinical Lead**, approve, then **Send approved offer**.
4. In **Physician**, Dr. Vale Surge accepts. Yara's offer is withdrawn automatically.
5. Back in **Coordinator**, advance the clock 20 min. Vale is activated at 17:55 CDT and Ridge goes from 90 to 0 deficit physician-minutes. The Ridge alert disappears, routing proposes SRG-C220 → Vale, and trap protection shows 4 → 0 calls at hospitals without a gap.

To run the demo against an isolated database, use the `backend-demo` (:8001, `backend/data/demo_phase5.db`) and `frontend-demo` (:3001) configurations in `.claude/launch.json`. Build the frontend first with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8001 npm run build`.

## 13. Limitations

- Roles are simulated headers, not authentication. There are no real messages (no SMS or push); delivery is recorded only.
- One backend process is assumed for the in-process lock. SQLite `BEGIN IMMEDIATE` still serializes across processes, but caches are per process.
- `required_physicians` is the peak deficit at the need hospitals in the 240-minute planning window. Partial coverage by a later acceptance is treated as redundant once the quota is met.
- An offer's start is fixed at proposal. If the clock passes it before approval, the approval is refused as stale and must be re-proposed.
- Activation timing is a deterministic simulation (the roster estimate), not a measured login. No-shows are not modeled beyond "never activated before the shift ended" when auto-activation is disabled.
- Reassignment writes a simulated Synapse event. A later real assignment event in the data supersedes it by event time.
- Coverage still counts busy physicians as available (Phase 3 default). See §14.

## 14. Handbook compliance audit (Phase 5 preflight)

Checked against the Challenge 2 Handbook (chapters 2–5, the routing, split-shift and
offer rules).

| Requirement | Status |
| --- | --- |
| Routing baseline: rules 1–5 (on shift + credentialed; skip busy, ringing, < 2 min since hang-up; low volume ≤ 6 day / ≤ 4 night first; fewest consults, tie → least recently answered; fail → retry) | Compliant. "Least recently answered" uses the last call end (documented proxy) |
| Split shift: opt-in, credentialed at a short hospital, 10 h rest at the offered start, trailing 7 d + offer ≤ 60 h, no clash with a scheduled shift | Compliant (unchanged) |
| ≥ 2 h, time to come online counts against the offer | **Fixed.** Previously only `offer ≥ 2 h and > 0 min after coming online`; now the useful time after coming online must be ≥ 2 h |
| ≤ 3 offers / week, 1 open offer | **Now enforced.** Previously wired to an empty offer log; now the Phase 5 offer log, a rolling 7-day window and a DB index |
| Judging CSV appends to the existing day | Compliant (`POST /api/events/csv`), and it never touches workflow state (tested) |
| Real dataset (`data/`) imports | **Fixed.** Header aliases were missing (import failed with 422); ET-labelled blocks and hours are now converted to hospital-local time |
| Explainable eligibility and projected impact | Compliant: every candidate × every rule, projected before/after, trap analysis |

**Resolved by the official-scenario audit
([official-scenario-audit.md](official-scenario-audit.md)).** Import, time zones and
replay are correct (0 snapshot mismatches). Coverage is credentialed on-duty capacity:
busy physicians count. This is supported by the brief ("credentialed capacity below the
required level") and by the data (counting only free physicians would leave Redwood short
71% of the day). Under that definition no hospital is short through 19:50; the first gaps
are Northfield at 20:00, then Cedar Ridge and Redwood at 21:00.

**Team decision (2026-10-10):** a hospital counts as short for split shifts only if its
gap starts within the dashboard's 90-minute forecast window
(`staffing.shortage_lookahead_minutes`, default = the forecast window). Offers are still
planned over 240 minutes, so they are long enough. Effect on the official data:

- 18:20: nobody can be asked; a split-shift proposal is refused with "monitor or
  escalate".
- 18:31–19:30: Dr. Grace Okafor (PHY-009) only, for Northfield.
- From 19:31: Okafor and Dr. Ben Alvarez (PHY-010).

Suncrest and Oak Valley are routing problems (every credentialed physician busy or
unavailable), handled by escalation or reassignment, not capacity gaps.
