# NEUROGRID live demo (official scenario, 18:20 ET)

Every number in this script was produced by the engines on the official `data/` folder.
If you load the bundled sample instead, the steps are the same but the numbers differ.

## Setup

```bash
make install          # or follow README "Run it"
make backend          # http://localhost:8000
make frontend         # http://localhost:3000
```

Open **Data Import**. Under *Dataset & simulation controls*, upload the 9 CSVs in `data/`
(or call `curl -X POST localhost:8000/api/datasets/import -F files=@data/<each file>`).
The simulation clock is set to **Tue 17 Mar 2026, 18:20 EDT**, taken from the snapshot
file name. It never uses the computer's clock.

## Script

1. **Load and reproduce the snapshot.** `GET /api/datasets/verification` compares 174
   fields across 26 entities and finds 0 mismatches.

2. **Most urgent problem.** In the **Command Center**, Priority One is *CON-2110:
   Assigned, physician not yet contacted — 12 min 45 s* (tier 1, critical). Expand it in
   *Ranked problems* to see its two linked alerts, the factors and the fingerprint.
   *Oak Valley: staffing / routing failure* is grouped as one problem, with root cause
   ROUTING_ELIGIBILITY_FAILURE.

3. **Evidence.** In *Availability intelligence*:
   - Dr. Maya Patel is PROBABLY_BUSY_EXTERNAL (camera on, no Synapse video).
   - Dr. Elena Torres is UNCERTAIN / STALE (agent offline). She is still routable per the
     brief, but she is not routable right now because her phone is ringing.
   - Dr. Noah Williams is UNAVAILABLE while holding open consults.

   The *Event history* panel shows the source events and timestamps.

4. **Forecast.** In the **Time Machine**, there is no shortfall within 90 minutes. Scrub
   to +40: shifts end at 19:00 EDT, and the grid and handoff panel show Dr. Sofia Ramirez
   and Dr. Marcus Lee leaving while holding open work. The stochastic band shows demand
   sensitivity per hospital.

5. **Last Safe Moment.** Three cards:
   - **Northfield:** short from 20:00 EDT. Start the rescue by 19:30 EDT (70 minutes
     left) with Dr. Grace Okafor: lead 30 minutes = approval 5 + reply up to 10 + online
     15.
   - **Redwood:** short from 18:00 PDT. Start by 17:35 PDT with Dr. Ben Alvarez.
   - **Cedar Ridge:** *no eligible candidate*, so escalate.

6. **Off-duty candidates.** In **Network → Rescue scarcity index**, all 6 off-shift
   physicians appear with their failed rules:
   - Hannah Cho fails *no overlap*.
   - Omar Haddad fails *opt-in* and *overlap*.
   - Lucy Brennan fails *opt-in* and *credentialed at gap*.
   - Ravi Menon fails *weekly hours*: 59 h worked + 2 h offered > 60.

   Okafor and Alvarez are each the *sole* backup for their hospital. The rule-by-rule
   arithmetic is in Command Center → Recommendations → split shifts.

7. **Simulate.** In the **Rescue Simulator**, with target Northfield at 18:20:
   - **Planning preview: Dr. Grace Okafor.** Target deficit goes from 120 to 0
     physician-minutes. The network deficit drops from 240 to 120, with no new shortfalls.
     The Load Guardian shows 1 modeled consult under protection versus 5 unrestricted.
     The split shift is **simulation only** with no contract creation yet: the 20:00 gap
     is outside the operational 90-minute shortage look-ahead. Escalation remains available.
   - **Comparators.** Do nothing and escalation are listed alongside. Four shift
     extensions are marked *simulation only*, and Hannah Cho is *infeasible*.

8. **Secondary consequences.** In **Network**, *Pool vs exclusive allocation* covers 7 of
   16 positions exclusively right now. *Multi-failure* shows that losing the two earliest
   shift-enders leaves Suncrest newly short.

9. **Open the staffing action window.** Advance the simulation clock by **11 minutes**
   to **18:31 EDT**. Northfield's 20:00 gap is now inside the 90-minute look-ahead.
   Okafor's split shift becomes actionable and recommended; Redwood remains a preview.
   **Create the Rescue Contract** with *Create rescue contract* on Okafor's option. Its status
   becomes `pending_approval` and nobody is contacted yet.

10. **Clinical Lead.** The *Decision freshness lock* banner confirms the data version is
    unchanged. Click **Approve**: the plan is re-validated on the server.

11. **Send.** Click *Send approved offer (simulated)*. It expires in 10 simulated minutes.

12. **Physician (phone view).** Sign in as Dr. Grace Okafor. The offer shows hospitals,
    hours, time to come online and the deadline, with no patient data. Tap **Accept**.

13. **Recalculate and verify.** In **Rescue Contracts**, the phase is ACTIVATION_PENDING
    and verification is *pending*, because acceptance is not activation. Advance the clock
    by 60 minutes. The physician is activated at the expected online time. Click **Verify
    & record**: the verdict is *resolved* (target deficit 0, versus 120 without the
    rescue), and it is written to the audit log.

14. **Judges' CSV.** In **Data Import**, choose the file, keep *Advance the simulation
    clock* checked, and click **Validate & preview impact**. The preview runs on an
    isolated branch and lists new and duplicate rows, conflicts, unknown types, clock
    before and after, and alerts gained or lost. Then click **Apply events**.

15. **Fresh reconstruction without a restart.** Every view refetches automatically
    through `/api/live`, keyed on data version, workflow version and clock.

16. **Optional: Chaos Lab.** Click **Run all**. All 16 scenarios run on temporary branch
    databases with real assertions, and each reports *baseline untouched*. The evaluation
    workflow scenarios advance only their branch clock when needed to enter the staffing
    action window, and report that step. At the original 18:20 snapshot, the evaluation
    table measures the planning-window deficit as 240 with monitoring only, 103 reactive,
    and 60 with NEUROGRID. This modeled comparison waits for the staffing action window
    before starting future rescues; it does not authorize offers now. The 60 left over is
    Cedar Ridge, which has no eligible backup. Figures recompute after events or clock moves.
