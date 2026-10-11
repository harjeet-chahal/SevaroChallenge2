# Sevaro Pulse: demo recording script

A click-by-click script for recording the demo on the **official challenge dataset**
(Tuesday 17 March 2026, "now" = 18:20 ET). Every number below was checked against the
running app on 2026-10-11. Some values are relative to the clock and change if you move
it differently.

- **90-second cut:** the next section. Use this one if your slot is 1½ minutes.
- **Full cut:** about 8 minutes (scenes 0–10). **Short cut:** about 3½ minutes (scenes
  marked ★). The longer scenes double as rehearsal notes and Q&A prep.
- **Story:** "At 18:20 everything looks covered. At 20:00, three of Northfield's four
  neurologists go off shift. Sevaro Pulse sees it coming, finds the one physician who can
  legally cover it, gets a clinical lead's sign-off and brings her online, with every step
  audited."

---

## 90-second cut

The loop is the backbone, because the brief requires it ("run the full loop"), and **every
step resolves one of the brief's edge cases on screen**. That separates this demo from a
happy-path walkthrough. About 185 words of voiceover, which fits 90 seconds.

**Record it in two sessions, then edit them together:**
- **Clip A, official dataset** (beats 1–6 and 8): fresh database, official ZIP imported,
  clock at **18:20**. Three tabs: **Command center**, **Clinical Lead**, and **Physician** in
  phone mode as **Dr. Grace Okafor**. Keep `live_test_suncrest_stroke.csv` ready.
- **Clip B, workflow sample** (beat 7, recorded after clip A). Off camera: **Load workflow
  sample** → **Ridge Sample Clinic: coverage gap now** → **Propose split shift** → tick
  **Dr. Yara Surge** under *Backup offers* → **Submit** → Clinical Lead **Approve** → **Send**.
  Start recording on the Physician tab as **Dr. Vale Surge**.
- Browser zoom at 110–125%, so text stays readable in a small video.

| Time | Edge case resolved | Do | Say |
| --- | --- | --- | --- |
| 0:00–0:14 | Doctor goes unavailable while holding a stroke consult · contradictory signals · consult can't be routed | Command center at 18:20. Zoom on the **Priority one** card (CON-2110, *4 min past critical*) and the **Recommended: Escalate** text, which lists *Dr. Maya Patel (external video suspected)*. | "Official dataset, 18:20. Top risk: a stroke consult whose doctor just went unavailable. Pulse checked every colleague. One says 'Available' but her camera is on outside Synapse, so she's busy. Reassigning would fail, so it recommends escalation." |
| 0:14–0:26 | Live judge events · duplicate event · no restart | **Data & simulation → Inject events → Append CSV** → `live_test_suncrest_stroke.csv` → **"3 event(s) accepted, 1 duplicate(s)"**. Close: **Unassigned 3 → 4**, new **CON-9001** alert, **Suncrest demand spike (6 consults in 60 min)**. | "Judges add events live. Here's a new stroke consult at the surging hospital, with one row sent twice. Three applied, the duplicate caught, alerts updated, no restart." |
| 0:26–0:32 | Gap from shift ends, before it happens | Clock **+5, +5, +1** (18:31). **Coverage gaps 0 → 1**. Click **Northfield Medical: coverage gap at 20:00 EDT**. | "At 18:31, Northfield's 8 pm gap enters the 90-minute window." |
| 0:32–0:50 | Several doctors look eligible but each fails a rule · split-shift trap | **Propose split shift**. Scroll to **Every off-shift physician evaluated (6)** (zoom on the Fail cells), then up to **Routing scope: SYN-008 (not SYN-004, SYN-005, SYN-010)**. **Submit for clinical-lead approval**. | "Five off-shift doctors look plausible. Each fails a rule: credentialed elsewhere, clashes with a night shift, over 60 hours, opted out. Only Dr. Okafor passes, and she's routed to Northfield only, so the split-shift trap can't move the overload." |
| 0:50–0:58 | Human approval with a live re-check · 10-min expiry | **Clinical Lead** → click the request → **Approve** → **Send approved offer (simulated)**. Zoom on **expires 18:41 EDT**. | "The clinical lead approves after a live re-check. The offer expires in 10 minutes." |
| 0:58–1:08 | No patient data · coverage updates on accept | **Physician** (⌘R if needed) → **Accept**. Cut to Command center: **Coverage gaps 1 → 0**. | "She accepts from her phone, with no patient data shown, and projected coverage closes the gap instantly." |
| 1:08–1:22 | Two doctors, one gap · stop asking once filled | **Clip B.** Caption *"Edge case · synthetic workflow sample"*. As Vale, **Accept**. Switch to **Dr. Yara Surge**: **"Withdrawn: coverage was secured by another physician; this offer is no longer needed."** | "Two doctors, one gap: the first acceptance binds and the backup is withdrawn automatically. Declines and timeouts loop back to the next eligible doctor, or to escalation." |
| 1:22–1:30 | Every offer logged | Back to clip A: Command center → intervention card → **Audit trail: every recorded step**. | "Every step is audited: who was considered, who was excluded and why, who approved, and the outcome." |

**How to hit 90 seconds:**
- **Record the screen silently first.** Cut the dead time (drawer loading, tab switches),
  then record the voiceover over the edit.
- **Label clip B honestly.** The official data has only one eligible doctor, so the
  two-acceptance case can't happen there. Judges know this dataset, and the caption shows
  you do too.
- **Said aloud but not shown:** decline and timeout. If asked, show them live: an offer
  that isn't answered expires after 10 simulated minutes (advance +15), and a declined
  doctor isn't asked again for that gap.
- **Left out on purpose:** the landing page, event-log badges, forecast chart, Optimizer
  comparison and the 19:50 activation. Keep them for Q&A (answers at the end of this
  file).

---

## Before you hit record

1. **Use a fresh database.** Interventions are then numbered from INT-0001, and the Clinical
   Lead history is empty. Stop your usual backend, then run:

   ```bash
   cd backend && DATABASE_URL=sqlite:///./data/recording.db .venv/bin/uvicorn app.main:app --port 8000
   ```

   To reset between takes, stop it, delete `backend/data/recording.db` and start it again.

2. **Run the frontend as a production build.** This removes the Next.js dev badge and
   avoids stale CSS. Stop `npm run dev` first, then run:

   ```bash
   cd frontend && npm run build && npm run start
   ```

3. **Dataset file:** `backend/data/raw/official_dataset.zip` (the 9 CSVs from `data/`, already
   created). **Live-test file:** `docs/demo/live_test_suncrest_stroke.csv`. Put both
   somewhere easy to reach in the file picker.

4. **Browser:** use Chrome at 1440×900 (or 1920×1080 at 125% zoom), with the bookmarks bar
   hidden and notifications off. Open four tabs:

   | Tab | URL |
   | --- | --- |
   | 1 | `http://localhost:3000` (landing page) |
   | 2 | `http://localhost:3000/clinical-lead` |
   | 3 | `http://localhost:3000/physician`, in DevTools device mode (⌘⌥M → iPhone 14 Pro, DevTools undocked into its own window so only the phone shows) |
   | 4 | `http://localhost:8000/api/datasets/verification` (load it after the import) |

5. **Fix or avoid the landing-page claim.** It says "reduces manual coordination work by
   80%". Nothing in the app measures that, and Sevaro's ops team will ask where it comes
   from. Either cite a source or say something the demo proves (see the closing line in
   scene 10).

6. **Rehearse once.** Pause about a second after each click; live updates arrive over SSE
   in about 1 second.

---

## Scene 0 ★ · Hook (0:25)

**Do:** Tab 1, the landing page. Slowly scroll to "How it works".

**Point at:** the live clock (**18:20 EDT**), the counts (critical alerts, gaps ≤ 90 min,
pending approvals) and the five-step loop: Detect → Decide → Propose → Approve → Accept.

**Say:**
> "About 795,000 Americans have a stroke every year, and every minute without treatment
> costs brain tissue. Sevaro already has a live view that shows what is happening right now.
> It can't tell you that a hospital will be short a neurologist at 8 pm, who could legally
> cover the gap, or how to get that person online safely. Sevaro Pulse closes that loop:
> detect, decide, act, with a clinical lead approving every step that reaches a physician."

---

## Scene 1 · Trust the data (0:45) · Brief #1

**Do**
1. Click **Open the command center**. In the sidebar, click **Data & simulation**.
2. **Upload dataset** → `official_dataset.zip` → **Import**.
3. Point at the active dataset: **12 hospitals · 14 physicians · 1164 events · 0 rejected rows**.
4. Switch to Tab 4 (reload it): `compared_entities: 26`, `compared_fields: 174`, `mismatches: []`.
5. Back in the app, close the drawer. Open the **Event log** tab at the bottom:
   - the row **EVT-01161 · video started**. Event time 18:11:20, ingested 18:18:05, badge
     **late**.
   - **Duplicates → Duplicates only → Apply**: **EVT-00529** with the badge **duplicate**.
     Set it back to **All**.

**Say:**
> "We rebuild the network from the raw event stream, ordered by when things happened, not
> when they arrived. Our replay matches the reference snapshot on all 174 fields with zero
> mismatches. This video-start arrived almost seven minutes late and is applied at its real
> time. This event appears twice in the stream and is applied once."

---

## Scene 2 ★ · Detect: what needs attention now (1:00) · Brief #2, #3

**Do**
1. Point at the summary strip: **Critical alerts 6**, **Coverage gaps 0**, **Unassigned 3 of 18
   open**, **Physicians available 2 / 8 on shift**.
2. **Needs attention** lists 15 ranked items. The Priority one card shows **CON-2110 · Harbor
   Regional · Dr. Noah Williams**, *Assigned, physician not yet contacted*, **12 min 45 s**,
   **4 min past critical**.
3. Read the **Recommended: Escalate to clinical lead** box. It explains why reassignment is
   impossible and names each colleague and what they are doing.
4. Open **Why this alert and this priority**. Point at the brief's 3 / 8-minute standard and
   "1.59× the critical standard". Open **Evidence (6)** → source event **EVT-01141**.
5. Open the **Physicians** tab. Expand **Dr. Maya Patel**: *Camera on, no Synapse session* →
   **Why busy? (R5_CAMERA_NO_SYNAPSE)**. Point at **Dr. Elena Torres: availability
   unverified** (desktop agent offline) and **Dr. Noah Williams: Temporarily unavailable**.
6. Open the **Consults** tab. Expand **CON-2101**: its stage history runs Received → Triaged →
   … → Imaging review → Video in progress. It is tracked separately from Dr. Kim's activity.

**Say:**
> "The coordinator sees the single most urgent problem first. A stroke consult at Harbor has
> been waiting 12 minutes for first contact, 4 minutes past the critical standard, because
> its physician just went Temporarily Unavailable. The system doesn't just flag it: it has
> already checked every credentialed colleague, found them all busy, and recommends
> escalation. Every alert explains its rule, its rank and the events behind it.
>
> Availability is inferred, not self-reported. Dr. Patel says she's available, but her
> camera is on with no Synapse session, so we treat her as busy on an external call. Dr.
> Torres looks free, but her presence agent is offline, so we flag it as unverified.
> Physician activity and consult stages are tracked separately, each with its own clock."

---

## Scene 3 · Decide and act on the top issue: escalate (0:25)

**Do:** Scroll back up. On the Priority one card, click **Request escalation**. The drawer
shows *Every credentialed on-shift physician is excluded* and *Eligible off-shift physicians
for Harbor Regional: none*. Click **Submit for clinical-lead approval**.

**Point at:** the toast **"INT-0001 created — waiting for clinical-lead approval. No physician
has been contacted."** The card now shows **In progress · Clinical escalation · Pending
approval**.

**Say:**
> "One click turns the recommendation into a request. The backend rebuilds and re-checks it.
> Nobody is contacted until the clinical lead decides."

---

## Scene 4 ★ · Live test: judges add an event (0:40) · Brief #8

**Do**
1. **Data & simulation** → expand **Inject events** → **Append event rows** → choose
   `live_test_suncrest_stroke.csv` → **Append CSV**.
2. Result: **"3 event(s) accepted, 1 duplicate(s)"**.
3. Close the drawer. The page updates on its own:
   - **Unassigned consults 3 → 4 of 19 open**.
   - A new alert, **CON-9001: routing failed 1×**, at Suncrest Medical Pavilion.
   - **Suncrest Medical Pavilion: demand spike (6 consults in 60 min)** (it was 5).

**Say:**
> "During judging you'll add events in the same CSV format. Here is another stroke consult at
> Suncrest, the hospital that is already surging, with one row sent twice. Three events are
> applied, the duplicate is caught, and alerts, demand and routing all update with no restart
> and no reload."

*(The file holds `consult_received`, `consult_triaged` and `routing_attempt_failed` for
CON-9001 at SYN-005, timed 18:19:20–18:19:53, plus one duplicate row.)*

---

## Scene 5 ★ · Look ahead 90 minutes (0:40) · Brief #4

**Do**
1. Open the **Coverage forecast** tab. All 12 hospitals show **Covered** for the next 90
   minutes.
2. Open the **Optimizer** tab → **Split shifts**. Read: *"No hospital is short in the next 90
   min… Gaps that start later… Northfield Medical from 20:00 EDT, Cedar Ridge…, Redwood…"*
3. In the sidebar clock, click **+5**, **+5**, **+1**. The clock reads **18:31 EDT**.
4. **Coverage gaps 0 → 1** · *"0 now · 1 within 90 min · first 20:00 EDT"*. A new alert
   appears: **Northfield Medical: coverage gap at 20:00 EDT · Due in 89 min · Next: Propose
   split shift**.

**Say:**
> "At 18:20 nothing is short inside the next 90 minutes, so we don't wake anyone up yet, but
> we're already tracking three later gaps. Watch the clock. At 18:31, Northfield's 8 pm gap
> enters the 90-minute window. Dr. Kim, Dr. Patel and Dr. Shah all finish at 20:00, so
> Northfield drops from four credentialed neurologists to one against a requirement of two.
> The baseline view can't see this coming."

---

## Scene 6 ★ · Decide: who can legally cover it? (1:15) · Brief #5, #7

**Do**
1. Click the **Northfield Medical: coverage gap at 20:00 EDT** alert. The card shows **Who to
   ask first → 1 Dr. Grace Okafor**: 19:35–22:00 EDT · online 19:50 · removes 120
   physician-min · est. $483 · 36 h in 7 d.
2. Click **Propose split shift**. In the drawer, point at, top to bottom:
   - **Recommended intervention:** *Offer Dr. Grace Okafor a split shift 19:35–22:00 EDT for
     Northfield Medical* · **OR-Tools CP-SAT (OPTIMAL)**.
   - **Northfield deficit 120 → 0 physician-min over 240 min if accepted (projected)**.
   - **Every off-shift physician evaluated (6)**, one row per physician and one column per rule:

     | Physician | Result |
     | --- | --- |
     | Dr. Grace Okafor | **passes all 9 rules** |
     | Dr. Ben Alvarez | not credentialed at the gap hospital |
     | Dr. Hannah Cho | overlaps her 19:00 scheduled night shift |
     | Dr. Omar Haddad | opted out (+2 more) |
     | Dr. Lucy Brennan | opted out (+1 more) |
     | Dr. Ravi Menon | 59 h + 2 h exceeds 60 h, and not credentialed at the gap |

   - **Routing scope while on the split shift: SYN-008 (not SYN-004, SYN-005, SYN-010)**, plus
     the seeded consult count.
   - Expand **Split-shift trap protection**: unrestricted least-loaded routing sends her **1**
     consult at a hospital without a gap; protected routing sends **0**.
   - **Cost and savings:** $483 vs the manual heuristic's $1,200, **saves $717 (Simulated)**.
3. Click **Submit for clinical-lead approval**. Toast: **INT-0002 created… No physician has
   been contacted.**

**Say:**
> "This is the decision that today takes a coordinator a spreadsheet and several phone
> calls. The optimizer checks all six off-shift physicians against every rule in the brief:
> opt-in, credentialed at the hospital that is actually short, 10 hours of rest, 60 hours a
> week, no clash with a scheduled shift, at least 2 useful hours after coming online, and
> offer limits. Exactly one passes, Dr. Okafor, and you can see why each of the others
> fails.
>
> It also handles the split-shift trap. A new physician starts at zero consults, so normal
> routing would pull her into every hospital she's credentialed at. We scope her to
> Northfield only and seed her consult count, so she fixes the gap instead of moving it. The
> offer is sized to the gap, 2 hours 25 minutes instead of a blanket 6, and the cost is
> clearly labelled as simulated."

---

## Scene 7 ★ · Approve: a person signs off (0:35)

**Do**
1. Tab 2, **Clinical Lead**. The sidebar **Clinical approval** shows the pending badge, and
   **Pending approvals** lists **2 waiting**.
2. Select the **escalation** (INT-0001) → **Approve** → *"approved (escalation authorized)"*.
3. Select the **split shift** (INT-0002). Optionally type a note, e.g. *"Northfield 20:00 gap
   confirmed."*, then **Approve** → *"approved after revalidation"*.
4. Click **Send approved offer (simulated)** → **OFF-0001 · Awaiting reply · sent 18:31 EDT via
   simulated app_push · expires 18:41 EDT**.

**Say:**
> "The clinical lead sees the same evidence. Approving doesn't trust what the coordinator saw:
> it re-checks eligibility, offer limits and whether the gap still exists against the current
> data. Sending is a separate, deliberate step, and the offer expires in 10 minutes."

---

## Scene 8 ★ · Accept from a phone (0:30)

**Do:** Tab 3, the phone frame. **Signed in as Dr. Grace Okafor: 1 new offer.** Point at
**Northfield Medical · 19:35–22:00 EDT · 2 h 25 min · about 15 min to come online · Why you were
asked · Offer expires 18:41 EDT (10 simulated min left)**. Tap **Accept** → *"Accepted. You are
not counted as active capacity until you go online."*

**Say:**
> "The physician gets exactly what the brief allows: hospital, hours, start time and why she
> was asked. There are no patient details, and the payload can't carry any. She accepts in
> one tap."

---

## Scene 9 ★ · Close the loop (0:50) · Brief #6

**Do**
1. Tab 1, **Command center**. **Coverage gaps 1 → 0**, and the Northfield alert has left the
   queue. Under **Interventions**, the split shift shows **Accepted · preparing**.
2. Keep the camera on the **Interventions** panel and click **+60**, **+15**, **+5** (clock
   **19:51**).
3. The card now shows **Activated**: *"Online since 19:50 EDT (simulation policy); routable only
   at SYN-008."* Point at:
   - **Coverage at activation (recalculated): Northfield Medical 80 → 0**.
   - **Split-shift trap protection (live):** intended SYN-008 · authorized scope SYN-008 ·
     credentialed at SYN-004, SYN-005, SYN-008, SYN-010.
4. Open **Audit trail: every recorded step**: proposed → approval requested → approved →
   offer sent → accepted → physician online → coverage recalculated, each with actor and
   simulated time.

**Say:**
> "As soon as she accepts, the forecast counts her as incoming, and the alert clears so nobody
> asks a second person. At her expected online time she becomes active: Northfield's
> shortfall goes to zero, routing can reach her only at Northfield, and every step is in the
> audit log with who did it and when."

> ⚠️ Keep the camera off the alert queue at 19:51. The dataset stops at 18:20, so after an
> 80-minute jump every open consult has aged and the queue turns red. That is correct, but it
> distracts from the story.

---

## Scene 10 · Under the hood and close (0:45)

**Do (optional):** **Optimizer → Compare**. Do this at 18:31 (right after scene 6), or say
the numbers over the closing shot. It reads *"Routing: the optimizer ties the baseline on
every metric"*, and for staffing, **offered minutes 360 → 145** and **excess coverage 105 →
10**.

**Say:**
> "Under the hood: a FastAPI backend replays events by event time, and Google OR-Tools solves
> routing as a min-cost flow and split shifts with CP-SAT, proven optimal in milliseconds. We
> compare against a simple baseline and report ties honestly. Every state change goes through
> a server-side state machine, and 366 automated tests pin the official scenario, the
> conflicts and the safety rules.
>
> Sevaro Pulse doesn't just show that a gap is coming. It finds the one physician who can
> legally fill it, gets a clinical lead's approval and closes the gap before it opens."

---

## Optional bonus (60–90 s): two acceptances and "I'm Available"

The official data has only one eligible physician, so record this on the workflow sample at
the very end. Loading a sample closes the official dataset's open items.

1. **Data & simulation → Load workflow sample**. Select **Ridge Sample Clinic: coverage gap
   now** → **Propose split shift**.
2. Under **Backup offers (optional)**, tick **Dr. Yara Surge**. Read the note: *"The first
   binding acceptance fills the need; the others are withdrawn automatically."* Submit.
3. Clinical Lead → **Approve** → **Send approved offer**. This sends 2 offers.
4. Physician: as **Dr. Vale Surge**, **Accept**. Switch to **Dr. Yara Surge**: her offer reads
   **Withdrawn: coverage was secured by another physician; this offer is no longer needed.**

> "Two physicians, one gap. Acceptances are serialized in the database. The first binding
> one wins, and the rest are withdrawn automatically with a clear message. We never staff a
> gap twice."

For voluntary availability ("I'm Available"), follow the steps in the README's Demo
section.

---

## Coverage of the brief's "What teams must demonstrate"

| # | Requirement | Where |
| --- | --- | --- |
| 1 | Rebuild state, handle late and duplicate events, match the snapshot | Scene 1 |
| 2 | Physician activity and consult lifecycle shown separately, time in stage vs standards | Scene 2 |
| 3 | Detect and rank, explain why | Scene 2 |
| 4 | Project coverage ≥ 90 min (shift ends, demand baseline) | Scene 5 |
| 5 | Recommend an intervention; every off-shift physician × every rule | Scene 6 |
| 6 | Full loop: propose → approve → send → accept → coverage updated | Scenes 6–9 |
| 7 | Split-shift trap | Scenes 6 and 9 |
| 8 | Live test without a restart | Scene 4 |

**Short cut (★):** 0 → 2 → 4 → 5 → 6 → 7 → 8 → 9, about 3½ minutes. In scene 2, keep only
the summary strip, Priority one and its "Why"; skip the Physicians and Consults tabs.

---

## Questions to expect, and the answers

**"The handbook says exactly one physician is eligible at 18:20. You show none."**
Under the brief's own coverage definition (credentialed capacity), no hospital is short
before 20:00. We decide shortage over the 90-minute forecast window, so at 18:20 nobody is
woken up, and from 18:31 Dr. Okafor is the only eligible physician. A 101–160-minute
look-ahead gives "exactly one" at 18:20. It's one setting
(`staffing.shortage_lookahead_minutes`). The full audit, with an independent replay, is in
`docs/official-scenario-audit.md`.

**"Why do busy physicians count toward coverage?"**
The brief says "credentialed capacity". Counting only free physicians would leave Redwood
"short" 71% of the day, yet the stream has only 4 routing failures. Free physicians are a
routing question, and routing has its own alerts (Suncrest, Oak Valley).

**"What if she declines or doesn't answer?"**
The offer expires after 10 simulated minutes, and expiry is applied before any reply. A
decline blocks re-asking her for that gap. The next eligible physician is proposed;
if there is none, the proposal is refused with "escalate instead of bending a rule".

**"What if two physicians accept?"**
Each acceptance is its own serialized transaction (a process lock plus SQLite
`BEGIN IMMEDIATE`). The first binding acceptance wins; the others are withdrawn or recorded
as redundant. This is tested sequentially and with two concurrent threads (bonus scene).

**"Why is a Suncrest consult routed to Okafor when you scoped her to Northfield?"**
(This can show up at 19:51.) It's a deliberate last-resort exception: a consult at another
hospital she's credentialed for that is already past a warning threshold, with nobody else
able to take it, can reach her. Everything else stays scoped.

**"Does this change our production routing?"** No. It models the routing rules to predict
whether an intervention helps. Nothing is executed outside the app.

**"Are the dollar figures real?"** No. They come from a simulated cost model, labelled
*Simulated* everywhere. A saving is confirmed only from a completed shift.

**"Does it scale to 200+ hospitals?"** Solves take milliseconds on 12 hospitals; we haven't
benchmarked at network scale. Say so plainly, as a next step.

---

## Known on-screen quirks (don't dwell)

- Dr. Sofia Ramirez's open-notes alert says "shift ends **23:00 UTC**". The instant is
  correct (19:00 EDT), but the zone label is UTC because her consults span several time
  zones.
- Northfield's forecast evidence includes "reducing available coverage from 4 to 4". Dr. Lee
  leaves as Dr. Cho joins.
- The Split shifts summary at 18:31 also says "No eligible offer reduces the deficit." That
  refers to the later Cedar Ridge and Redwood gaps, not Northfield.
- If body text looks serif or buttons look blue, a dev server is serving stale CSS. Restart
  it, or use the production build from step 2.
