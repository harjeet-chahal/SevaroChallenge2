# Assumptions

Each assumption is configurable (in `IntelligenceConfig` or the existing policy files)
and shown in the UI where it applies. Assumptions from earlier phases are listed in
[official-scenario-audit.md](official-scenario-audit.md) and
[optimization.md](optimization.md).

| # | Assumption | Default | Why / effect |
| --- | --- | --- | --- |
| A1 | Clinical-lead approval time | 5 min | Not given in the brief. Feeds the Last Safe Moment lead time |
| A2 | Expected reply to an offer | 4 min | Used only for the "expected" lead time. The conservative lead time uses the full 10 minutes from the brief |
| A3 | Planning horizon for fragility, genome, scarcity and Last Safe Moment | 240 min | Same window as the staffing planner. The dashboard forecast stays at the brief's 90 minutes. At 18:20 nothing falls short within 90 minutes; within 240 minutes Northfield, Redwood and Cedar Ridge do (see the audit) |
| A4 | Coverage counts credentialed on-duty capacity, including busy physicians | (existing) | The audit's governing definition. Pool versus exclusive allocation is shown side by side |
| A5 | Physician removal in fragility scans starts now and lasts to the horizon | — | Simplest well-defined disruption |
| A6 | Stochastic arrivals are Poisson at the baseline hourly mean, with seed 20260317 and 400 runs | rate × 1 | A sensitivity band. The p90 baseline is used only as the spike threshold |
| A7 | Historical coverage debt samples instantaneous deficits every 5 minutes over the last 120 minutes | 5 / 120 | A reconstruction, not a log of what was displayed |
| A8 | Shift-extension what-ifs last 120 minutes | 120 | Simulation only. No extension authority or on-shift hours data |
| A9 | Genome counts a shift collision when a credentialed shift ends in the 30 minutes before the shortfall | 30 min | Matches the shift-cliff detector's spirit |
| A10 | A CSV import may advance the clock only when asked, to max(event_time, ingested_at), never backward and never more than 12 hours | off by default | Keeps the existing "now does not jump" behaviour while making unseen events visible on request |
| A11 | Chaos scenarios may make labelled branch-only reference edits (a schedule end, an opt-out, an added credential) | — | Some faults cannot be expressed as events. They never reach the baseline |
| A12 | Network-level times are shown in Eastern time; hospital rows use the hospital's own zone | — | The scenario's reference zone |
