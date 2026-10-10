# backend/data

- `raw/`: a convenient place to drop the judging dataset (loose `*.csv` files or a
  `.zip`). Contents are git-ignored. Import with `POST /api/datasets/import` or the
  **Upload dataset** control in the coordinator view.
- `sevaro_pulse.db`: the local SQLite database, created on first start (git-ignored).
  It holds the active dataset, the event log (including injected events), import history,
  the simulation clock and the Phase 5 workflow tables (`wf_*`), so state survives
  restarts. Delete it to reset everything.
- `demo_phase5.db`: used only by the isolated `backend-demo` launch configuration
  (port 8001), so a demo never touches your development database.

See [`docs/dataset-import-plan.md`](../../docs/dataset-import-plan.md) for the expected
files, column mapping and validation rules.
