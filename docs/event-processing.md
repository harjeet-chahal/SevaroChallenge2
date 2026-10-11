# Event processing & state reconstruction (Phase 2)

All operational state is rebuilt from the stored event log by one pure function:

```python
from app.engines.replay import reconstruct_state
state = reconstruct_state(events, as_of, reference)   # -> OperationalState
```

It has no FastAPI or database dependencies and is deterministic: the same events,
reference data and `as_of` always give the same result, whatever order the events are
passed in. State is rebuilt from scratch on every call (≈ms for thousands of events), so
there is no mutable "current value" that a late event could corrupt.

## 1. Events

### Normalized fields

| Field | Meaning |
| --- | --- |
| `event_id` | Stable identity (deduplication key) |
| `event_type` | Plain string. Documented types drive state; others are stored and reported |
| `event_time` | When it happened — normalized to UTC |
| `ingested_at` | When the system learned of it — normalized to UTC |
| `event_time_raw`, `ingested_at_raw` | The original strings, offsets intact |
| `consult_id`, `physician_id`, `hospital_id` | Associations, when applicable |
| `payload` | Typed values per type (`status`, `consult_type`, `priority`) + `attributes` (unmapped columns) |
| `raw` | The source record exactly as received |
| `source`, `source_file`, `source_row`, `sequence` | Provenance; `sequence` is insertion order |

### Validation (`engines/event_processing/normalize.py`)

- `event_id`, `event_type`, `event_time` are required; `ingested_at` is required for
  dataset rows and defaults to the **simulation** time for live injection.
- Timestamps must be ISO-8601 **with** a UTC offset (or `Z`). Naive values are rejected.
- Timestamps must fall in years 1900–2200, and IDs (`event_id`, `consult_id`,
  `physician_id`, `hospital_id`) are at most 128 characters; otherwise that row is
  rejected with a field-level error (a CSV append keeps its other rows).
- Required associations per documented type (`catalog.py`), e.g. `video_started` needs
  `physician_id` and `consult_id`; `physician_status_changed` needs a status.
- `physician_status_changed` status: a `status` column, or — documented fallback — a
  description like `Self-reported status: In Meeting`. Accepted values: Available,
  In Meeting, Temporarily Unavailable (normalized). Anything else is rejected with the
  accepted list.
- `consult_received` consult type: a `consult_type` column, or the description
  `"<Type> consult request received"`. Missing type is a warning, not an error.
- Invalid records are **never dropped silently**: dataset rows are quarantined in
  `event_rejections` and listed in the import report; live injections return 422 with
  per-field errors and are also recorded. Unknown event types are stored, counted in
  `diagnostics.unknown_event_types`, and not applied.

### Identity, duplicates, ordering, visibility (`engines/event_processing/log.py`)

| Rule | Policy |
| --- | --- |
| Identity | `event_id` |
| Canonical copy | Earliest by `(ingested_at, sequence)`. Later copies are `duplicate` (same content hash) or `conflicting_duplicate` (different content); both are stored and never applied |
| Visibility at T | `ingested_at <= T` **and** `event_time <= T` |
| Replay order | `(event_time, ingested_at, event_id, sequence)` — total and deterministic |
| Late arrival | Flagged `arrived_out_of_order` when an event with a later `event_time` was already ingested; it is applied at its true `event_time` |

So at simulation time T the system uses only what it knew by T, applied in the order
things actually happened. An older event arriving last can never overwrite newer state.

## 2. Consultation lifecycle (`engines/consultation_state/transitions.py`)

| Event | Target stage | Guard |
| --- | --- | --- |
| `consult_received` | Received | creates the consult; sets hospital, type, received time |
| `consult_triaged` | Triaged | forward only |
| `physician_assigned` | Assigned | forward only; always updates the assignee (reassignments recorded) |
| `incoming_/outgoing_call_started` | Provider Contacted | only if earlier than Provider Contacted |
| `imaging_requested` | CT/CTA or Imaging Pending | forward only |
| `imaging_returned` | Imaging Review | forward only |
| `video_started` | Video In Progress | forward only |
| `video_ended` | Note Pending | forward only |
| `incoming_/outgoing_call_ended` | Note Pending (**provisional**) | only while at Provider Contacted (phone-only consult) |
| `note_started` | Documentation | forward only |
| `note_signed` | Signed Off (closed) | — |
| `routing_attempt_failed` | — | counted (`routing_failures`), stage unchanged |
| `incoming_call_ringing` | — | does **not** assign the consult |

- Stages may be skipped (phone-only consults skip video).
- A provisional Note Pending is superseded by a later imaging or video event.
- A backwards event is recorded as an `out_of_sequence` anomaly and the stage is kept;
  events after sign-off are recorded as `event_after_sign_off`. A consult whose first
  event is not `consult_received` is still built and flagged `missing_consult_received`.
- If no `physician_assigned` exists, the first call/video/note event by a physician
  links them, flagged as `assignment_inferred`.
- Consult state is **independent** of physician activity: one physician can own many
  consults in different stages; becoming busy changes none of them.

## 3. Physician availability (`engines/physician_state/availability.py`)

Raw signals are tracked separately (`signals`): self-reported status, active calls,
active video sessions, ringing phones, camera, desktop-agent status, last call end. A
physician can have several at once. The first applicable rule decides:

| Rule | Condition | Availability | Activity |
| --- | --- | --- | --- |
| R1_SYNAPSE_CALL | active Synapse call | busy | incoming/outgoing call |
| R2_SYNAPSE_VIDEO | active Synapse video | busy | video consult |
| R3_OFF_SHIFT | not on shift | off_shift | off shift |
| R4_TEMPORARILY_UNAVAILABLE | self-reported Temporarily Unavailable | unavailable | temporarily unavailable |
| R5_CAMERA_NO_SYNAPSE | camera active, no Synapse video, not In Meeting | busy + `external_video_suspected` flag | camera on, no Synapse |
| R6_CAMERA_IN_MEETING | camera active while In Meeting | available (interruptible) | in meeting |
| R7_IN_MEETING | In Meeting, camera off | available | in meeting |
| R8_AGENT_OFFLINE | desktop agent offline | available + `availability_unverified` warning | — |
| R9_DOCUMENTATION | a consult in Documentation | available (not a busy signal) | documentation |
| R10_DEFAULT | otherwise | available | available |

- Camera rules apply only while the agent is online: offline means camera state unknown.
- There is no documented "agent back online" event: a later camera event (sent by the
  desktop agent) marks it online again, flagged `agent_online_inferred`.
- Every state carries `decision_rule`, an ordered `explanation`, `flags` and the
  `evidence_event_ids` behind the decision.
- On shift: within the on-shift roster window, after a `shift_started` event, or (flagged)
  after an off-shift roster's `next_shift_starts_at`.
- `consults_this_shift` = distinct consults assigned via `physician_assigned` since shift
  start; `calls_this_shift` = call starts since shift start (duplicates never count).

## 4. Simulation clock

The clock is stored in SQLite and moves only via the API; it never follows the server's
wall clock (`server_time` is reported separately for contrast).

| Endpoint | Effect |
| --- | --- |
| `GET /api/simulation` | current time, reference time + source, events not yet ingested, server time |
| `POST /api/simulation/time` `{"time": "...+offset"}` | set a time (naive rejected; must be within a year of the loaded data, else 422 `simulation_time_out_of_range`) |
| `POST /api/simulation/advance` `{"minutes": 5}` | move forward (same window) |
| `POST /api/simulation/reset` | back to the reference time |

Reference time on import, first match wins: `reference_time` form field → dataset
`dataset_manifest.json` → `SIMULATION_REFERENCE_TIME` → snapshot file name `_HHMM` (in the
latest event's offset, within ±1 h of it) → latest `ingested_at` rounded up to the minute.
The chosen source is reported.

## 5. API (Phase 2)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/datasets/import` | multipart `files` (ZIP and/or CSVs), optional `reference_time`. 422 + full report on validation failure; previous dataset untouched |
| POST | `/api/datasets/sample` | load the bundled SYNTHETIC SAMPLE DATA (repeatable) |
| GET | `/api/datasets/status` | active dataset, counts, import report, last failed attempt |
| GET | `/api/datasets/verification` | replay at the reference time vs. snapshot files; mismatches listed |
| GET | `/api/state?as_of=` | full `OperationalState` (default: simulation time) |
| GET | `/api/physicians?as_of=&on_shift=` · `/api/physicians/{id}` | derived physician states |
| GET | `/api/consultations?as_of=&open=&hospital_id=&physician_id=&stage=` · `/{id}` | consult states |
| GET | `/api/events?as_of=&physician_id=&consult_id=&event_type=&visibility=&dedupe=&recognized=&order=&limit=&offset=` | annotated event log |
| POST | `/api/events` | inject one event or a list (all-or-nothing) |
| POST | `/api/events/csv` | append rows in `event_stream.csv` format. Valid rows are stored and invalid ones reported (`rejected` outcomes, also in `/api/events/rejections`); 422 only if no row is valid or the file can't be read. An unquoted comma inside `description` is joined back into that column (warning). The delimiter is read from the header line; quoting is always standard `"` |
| GET | `/api/events/rejections` | every rejected record |

`/api/config` reports `simulation_time`, `dataset_loaded` and `data_version` (bumped on
every import or injection), which the UI polls to know when to refetch.

## 6. Known assumptions

- Column names other than `event_time`/`ingested_at` are not documented; they are matched
  through explicit aliases (brief display headers included) and reported per import.
- Phone-only Note Pending timing (a call ending at Provider Contacted, or at Imaging
  Review once scans are back) is an interpretation of "Note Pending + Documentation, from
  end of video or call". It is provisional: a later imaging or video event supersedes it.
- A ring stops when the consult moves on: the call is answered (by anyone), the consult is
  assigned to someone else, routing fails, or it is signed off. A ring left unanswered for
  5 minutes (the routing retry interval) is treated as over (assumption).
- A consult rung or failed by routing without a triage event is still waiting for a doctor:
  `routing_started_at` records the first ring or failed attempt, and the "Triaged, not yet
  assigned" standard is timed from it (flagged).
- A `shift_started` after a physician's scheduled shift has ended starts a new shift with no
  known end (flag `shift_restarted`).
- Counting definitions for "consults" and "calls" are ours; snapshot verification will
  surface any difference rather than hide it.
