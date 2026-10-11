# Challenge 2 requirements verification

Reviewed October 10, 2026 against the supplied Challenge 2 Handbook and repository tests.
The latest completed run in this session passed 260 backend tests, Ruff lint/format,
frontend TypeScript/ESLint, and a production build. This is evidence of implemented
behavior, not a guarantee that every unseen judging input will pass.

## Handbook problem categories

| Category | Existing automated evidence | Remaining qualification |
| --- | --- | --- |
| Hospital demand surge | `test_demand_coverage.py`: local-hour p90, strict threshold, +1 requirement, duplicate demand | Future arrivals are not forecast; known surges expire as arrivals leave the window |
| Shift ends and unfinished notes | `test_demand_coverage.py`: projected gaps; `test_risk_rules.py`: open notes near shift end | Coverage means credentialed on-duty capacity; see policy ambiguity below |
| Credentialing | `test_optimization_dispatch.py`: uncredentialed doctors excluded; official matrix loaded cell-for-cell | Eligibility cannot be traded against optimization score |
| Conflicting availability signals | `test_engine_physician.py`: call/video/camera/meeting/offline precedence | Offline helper is uncertain, not proof of availability |
| Consult stage delays | `test_risk_rules.py`: exact warning/critical thresholds, stroke-only rules, note clock | Unknown consult type is flagged rather than guessed |
| Failed routing and ranking | `test_risk_rules.py`, `test_optimization_dispatch.py`: excluded pool, urgency, waiting time, capacity | Ranking weights beyond the brief are project policy choices |
| Late, duplicate, repeated requests | `test_engine_replay.py`, `test_engine_consultation.py`: replay order, dedupe, preserved original wait | Repeats do not receive an independent priority boost; original wait continues |
| Off-duty eligibility | `test_optimization_staffing.py`: all rules, rest boundary, hours, overlap, useful duration, missing fields | Handbook's expected candidate count depends on planning horizon |
| New doctor overloaded | `test_optimization_staffing.py`, `test_workflow.py`: routing scope and seeded count | Effect is simulated; not a measured clinical outcome |
| Approval, expiry, conflicts, privacy, audit | `test_workflow.py`: approval gate, revalidation, quotas, 10-minute expiry, concurrent replies, patient-free offer payload, audit | Demo role headers are not production authentication |

## Required demonstration evidence

- Official 18:20 replay: 26 entities, 174 fields, zero mismatches, verified in browser.
- Separate physician and consult views: implemented; backend state/threshold tests pass.
- Alerts and evidence: implemented and inspected in browser.
- At least 90-minute coverage horizon: tested, including time zones and DST boundaries.
- Candidate explanations: every off-duty candidate and every eligibility check tested.
- Full loop: manually rehearsed proposal -> approval -> simulated send -> accept ->
  20-minute advance -> activation. Ridge deficit at activation changed 90 -> 0.
- Trap protection: approved hospital scope verified after activation.
- New judging CSV without restart: HTTP integration test appends to the official day,
  retains intervention/import identity, handles duplicates and late records, advances
  the simulation, and verifies recomputed demand/routing findings.

## Open acceptance work

Update: the [acceptance rehearsal](rehearsal/acceptance-results.md) now covers the
browser file picker, decline, exact expiry, invalidated approval, and a newly authored
judging CSV with measured UI update times. Items 2 and 3 below describe the original
checklist; their rehearsals are now complete within the report's stated limits.

1. Mentor clarification: 240-minute staffing window yields two eligible doctors at
   18:20; the 90-minute dashboard has no capacity deficit. The handbook says exactly
   one candidate. See `official-scenario-audit.md`; tests pin our interpretation,
   not the handbook's expected count. Do not declare full specification sign-off yet.
2. Manually rehearse the judge CSV file picker, decline, expiry/no response, and an
   approval invalidated by a new event. These have backend tests but were not all
   browser-rehearsed in this session.
3. Run a separately authored unseen scenario and measure end-to-end update latency.
   Existing synthetic scenarios are useful but do not prove arbitrary unseen data.
4. Check narrow-screen layout and deployment environment if either is used in judging.
   Production build passed; cloud deployment and broad browser/load testing are unverified.

## Recommended optional sponsor extension

An evidence-linked operations briefing and what-if assistant. Use one model provider
(Azure or AWS), plus optional ElevenLabs voice. Fetch structured state, alerts, candidate
checks, and optimizer output from the existing backend. Include simulation time and
data version; associate statements with real alert/rule IDs. Ask the existing simulator
to calculate alternate plans rather than asking the model to invent outcomes.

Start read-only. A user may prepare a proposal through the existing workflow; clinical
lead approval remains enforced by the backend. Voice can read an approved patient-free
offer in the demo, while explicit buttons record acceptance or decline. Sponsor API
failure must leave all original features usable.

Before claiming this extension works, test: unsupported questions; invented doctor IDs;
ineligible requests; stale data; instructions embedded in CSV descriptions; provider
timeout; patient details leaking into offer text; and attempts to bypass approval.
Measure accuracy against structured facts and task completion time against the existing
dashboard. No sponsor API is currently integrated. Cigna-specific scope requires the
event's actual resources/prize criteria; no Cigna API availability is assumed.
