# RU Health Hack: submission and demo

The submission is Sevaro Pulse, the existing Next.js/FastAPI command center in this
repository. The goal is to demonstrate Detect -> Decide -> Act using the supplied
Challenge 2 CSVs. All identities and records are synthetic. Offers are simulated.

## Start locally

Follow the two-terminal setup in the root README. Once installed, start with:

```bash
# Terminal 1, from the repository root
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
# Terminal 2, from the repository root
cd frontend
npm run dev
```

Open http://localhost:3000/coordinator. No cloud account or login is required.
Use localhost consistently for the frontend development server.

## Official data: show correctness first

1. Expand **Dataset & simulation controls** and select **Load challenge dataset**.
   This imports the repository's `data/` files through the normal validation pipeline.
   It replaces the active dataset and workflow state, so do it before the rehearsal.
2. Select **Verify reference snapshots**. At the supplied 18:20 Eastern baseline,
   expect 26 entities, 174 fields checked, and zero mismatches.
3. Collapse the dataset controls. Show the ranked alerts, the reason for the top
   alert, physician signal conflicts, and consult-stage timers.
4. Show the 90-minute hospital forecast, then the routing and split-shift
   recommendations. Explain that routing-ready physicians differ from on-duty
   coverage capacity. Recommendations are computed from the imported data.

## Demonstrate the complete action loop

Use **Load workflow sample** for a compact, reproducible intervention demonstration.
Clearly identify it as the additional synthetic scenario, separate from the official day.

1. Select **Ridge Sample Clinic: coverage gap now (0/1)** in the alert queue.
2. Select **Propose split shift**. Explain the candidate rule checks, projected
   improvement, and restriction to the short hospital to avoid swamping the new doctor.
3. **Submit for clinical-lead approval**. Switch to **Clinical Lead**, review, and
   **Approve**. Then **Send approved offer (simulated)**.
4. Switch to **Physician**, select Dr. Vale Surge, and **Accept** the offer.
5. Return to **Coordinator** and advance **+15 min**, then **+5 min**. Observe
   activation, Ridge's cleared coverage gap, updated routing, and the audit trail.

The modeled coverage improvement is not a measured patient outcome. Do not claim
reduced mortality or measured treatment-time savings from this synthetic simulation.

## The judges' new CSV

Load the official challenge dataset before the judging test. In dataset controls,
use **Judge CSV · append to this day -> Append CSV** for the new event file.
Do not use the full-dataset import, which replaces the day.

The existing day and approval history stay in place. Events are deduplicated and
replayed in event-time order. Records whose arrival time is in the future stay pending
until the simulation clock reaches it; advance or set the simulation time explicitly.
Show the resulting alerts and recommendations without restarting either server.

## Important assumption to disclose

The supplied handbook says exactly one off-duty doctor qualifies. The current
240-minute staffing horizon reaches later gaps and produces two eligible candidates;
the 90-minute dashboard horizon shows no capacity shortfall at 18:20. This is analyzed
in `official-scenario-audit.md`, including sensitivity to a 120-minute staffing window.
Ask the challenge mentor to clarify the intended horizon. Do not hard-code an eligible
physician or silently change the definition to reproduce a desired count.

## Remaining 12-hour priorities

1. Confirm the actual submission cutoff and required submission artifacts with the event.
2. Rehearse the official-data import, snapshot check, approval loop, and new-CSV update.
3. Resolve the planning-horizon question with the mentor and record any policy change.
4. Run backend tests, lint, frontend type-checking, and a production build on the
   submission machine. Keep the local demo ready even if cloud deployment is delayed.
5. Record a short backup demo and prepare the pitch, architecture, limitations, and
   README links. Freeze features before submission and submit with time to spare.

## Verification on October 10, 2026

- Backend: 260 tests passed; Ruff lint and formatting passed.
- Frontend: TypeScript, ESLint, and the Next.js production build passed.
- Browser: official dataset loaded; 26 entities and 174 reference fields matched.
- Browser: workflow sample proposed, approved, sent a simulated offer, accepted,
  and activated after advancing 20 minutes. Ridge's modeled deficit changed from
  90 to 0 physician-minutes at activation; routing stayed scoped to Ridge.
- The official baseline was reloaded after the rehearsal. No sponsor service was used.

Build troubleshooting: an initial sandbox permission failure was retained in the
production Turbopack cache. Preserving that cache elsewhere and rebuilding with
the approved permissions succeeded. The development server cache was left intact.

## Sponsor scope

AWS and Azure are potential hosting choices; select one if a public deployment is
needed. Neither is required for the local judging loop. A possible ElevenLabs extension
is an optional spoken version of the already-approved, patient-free offer; it must
preserve the existing approval and response workflow and fail without blocking it.
Cigna-specific work depends on the resources or prize criteria actually supplied by
the event. No sponsor integration is currently implemented or claimed in this repo.

Cloud deployment, real authentication, real messaging, and clinical-system integration
remain separate from this hackathon demo. The demo role headers are not authentication.
