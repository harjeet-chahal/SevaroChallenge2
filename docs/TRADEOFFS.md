# Trade-offs

- **Kept Next.js and the `engines/` + `services/` layout.** The repository is the source
  of truth for structure. All NEUROGRID engines live in `app/engines/intelligence/` and
  are pure functions, like the other engines. Orchestration lives in `services/`.

- **No new scenario tables or Alembic.** Chaos and preview branches are temporary SQLite
  copies made with the online backup API. Every real service runs on them unchanged, and
  the baseline cannot be written by construction. The cost is no persistent scenario
  history; chaos results are returned, not stored. Schema changes still use the existing
  "schema version, then rebuild" approach.

- **Contract phases are derived, not stored.** The existing validated intervention state
  machine already enforces approval-before-offer, expiry, idempotency and conflicting
  acceptances. A second state machine would duplicate safety logic, so phases are mapped
  from it (see RULES.md). The cost is that VERIFYING and PARTIALLY_RESOLVED are computed
  views rather than stored states.

- **Simulator ranking uses exact re-evaluation, not a new CP-SAT model.** There are few
  options per target, and the exact piecewise engine gives exact before and after values.
  The combined plan comes from the existing CP-SAT staffing optimizer, and nothing is
  approximated. A CP-SAT `x[p,h,t]` model would mainly pay off at network scale.

- **The brief wins over the specification on agent-offline routing.** UNCERTAIN
  physicians stay routable, and "confirm before routing" is labelled as a proposed policy.

- **The CSV clock advance is opt-in.** Existing tests pin "now does not jump" on append.
  The UI checkbox defaults to on, so unseen future events become visible.

- **Planning horizon of 240 minutes for planning engines.** The brief's 90-minute
  dashboard window shows no shortfall at 18:20. The planner needs to see the 20:00–21:00
  cliffs in time to act. Both horizons are shown and labelled.

- **Pool coverage stays authoritative.** Exclusive allocation is reported next to it, so
  the gap between the two readings is visible (for example, 7 of 16 positions are
  exclusively coverable at 18:20) without changing the brief's definition.

- **Single process, SQLite WAL.** WAL and a busy timeout are now enabled. Live updates
  remain the existing SSE stream. Moving to Postgres and multiple workers would need
  interprocess broadcasting; that is not needed for the demo.
