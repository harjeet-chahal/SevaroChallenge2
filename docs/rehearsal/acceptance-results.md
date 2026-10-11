# Acceptance rehearsal: October 10, 2026

Tested the running local browser frontend and FastAPI backend. All contacts and offers
were simulated. The fresh CSV was hand-authored for this rehearsal, independently of
the existing sample generators; it was not an external judge's hidden test.

## Results

| Check | Observed result | Status |
| --- | --- | --- |
| Planning-window sensitivity at official 18:20 | 90 min: none; 120 min: PHY-009; 240 min: PHY-009 and PHY-010 | Behavior verified; specification decision remains open |
| CSV uploaded with actual browser file picker | 8 rows, 7 accepted, 1 duplicate; original 18 consults become 20, not 21 | Pass |
| Repeat call and late/out-of-order triage | Original CON-2105 received time preserved; new consults rebuilt by event time | Pass in new integration test |
| Two new consults at the same hospital | Both remain distinct; Oak Valley arrival count is 3 and creates a surge | Pass |
| Future status event | PHY-004 unavailable now, available after advancing beyond the 18:25 arrival | Pass in integration test; browser metrics update |
| Existing workflow survives append | INT-0002 remains pending approval after the upload | Pass in browser |
| Physician decline | OFF-0002 / INT-0003 show Declined in both physician and coordinator views; Ridge remains short | Pass |
| Offer one second before expiry | OFF-0003 still offers Accept/Decline at 18:44:59 EDT | Pass |
| Offer at exact expiry | At 18:45:00 EDT, OFF-0003 moves to past offers, says Expired, and has no Accept button; coordinator shows INT-0004 Expired | Pass |
| Proposal invalidated by a new event | Propose INT-0005, inject SRG-P7 shift_started, then attempt approval: closes No longer required, explains no remaining Ridge gap, provides rechecked data version 9 | Pass |
| Malformed status description | Import rejected atomically with actionable field errors; no partial new consults | Pass in new regression test |

## Browser timing observations

Wall-clock timings were measured with Date.now immediately before the UI action and
after waiting for the relevant visible DOM element. Browser automation overhead is
included. These are single observations on this local machine with warmed servers,
not a percentile benchmark, a load test, or a production SLA.

| Measurement | Time |
| --- | ---: |
| Click Append CSV -> visible 7 accepted / 1 duplicate result | 423 ms |
| Click Append CSV -> REHEARSAL-C1 visible in consultation table | 1,082 ms |
| Click Set time (18:30) -> critical REHEARSAL-C1 alert visible | 867 ms |

## Automated checks added and run

- `backend/tests/test_acceptance_surprise.py`: fresh judging CSV and malformed-file atomicity.
- `backend/tests/fixtures/judging_rehearsal.csv`: reusable 8-column event file for the official day.
- Explicit 120-minute planning-horizon case added to the official scenario tests.
- Focused run: 61 tests passed across surprise, official scenario, and workflow tests.
- Ruff lint and formatting passed. No production business rules were changed.

## Findings and limits

The handbook ambiguity cannot be resolved by testing alone. The existing documented
definition counts credentialed on-duty doctors toward coverage, including busy doctors;
routing availability is separate. The 240-minute planning horizon includes later gaps
that a 120-minute horizon does not. Ask the challenge mentor to confirm the intended
coverage definition and planning window. Changing to 120 only to produce one candidate
would not establish that the interpretation is correct.

Two minor presentation observations: the physician countdown rounds to "0 simulated
min" during the final seconds while the offer is still valid; past declined/expired
offers still show an estimated online time. These did not alter expiry or coverage.

A transient API timeout occurred while development files were being edited; the running
backend uses auto-reload. Refresh recovered the UI. The measured upload and workflow
steps were performed after reconnection, without a server restart to ingest data.
Use a stable, non-reloading server for the final judged rehearsal.

State snapshots were saved before dataset replacement and after testing:

- `/private/tmp/sevaro-before-acceptance-tests.db`: original official baseline and user pending approval.
- `/private/tmp/sevaro-acceptance-rehearsal-results.db`: rehearsal workflow and audit evidence.

The official baseline is reloaded for the user afterward. Reloading closes previous
open interventions; the pre-test snapshot preserves the original pending approval.
