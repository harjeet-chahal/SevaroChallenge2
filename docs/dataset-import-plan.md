# Dataset import

Status: **implemented (Phase 2)**. Code: `backend/app/services/dataset_import/`.

The judging dataset arrives later and may differ from what we have seen, so the importer
relies only on what the challenge brief documents. Everything else goes through an
explicit, overridable mapping, and every interpretation is listed in the import report.
Nothing is guessed silently.

## 1. Inputs

`POST /api/datasets/import` (multipart `files`, optional `reference_time`) accepts one
ZIP, several CSVs, or both. `POST /api/datasets/sample` loads the bundled SYNTHETIC
SAMPLE DATA.

Safety (`sources.py`): ZIPs are read in memory and never extracted. Entries with
absolute paths or `..` are rejected (path traversal). The upload size, total
uncompressed size (enforced while reading, not just from the declared sizes) and entry
count are capped (`MAX_*` settings). `__MACOSX/` and dotfiles are ignored; directories
are flattened.

## 2. Files

Matched by filename pattern, case-insensitively (overridable via `file_patterns`):

| Logical table | Pattern | Required | Used in Phase 2 |
| --- | --- | --- | --- |
| `event_stream` | `event_stream*.csv` | yes | replay |
| `hospitals` | `hospitals*.csv` | yes | names, IANA zones |
| `physicians_on_shift` | `physicians_on_shift*.csv` | yes | shift windows |
| `credentialing_matrix` | `credentialing*.csv` | yes | stored (eligibility is Phase 4) |
| `physicians_off_shift_roster` | `physicians_off_shift*.csv` | warn if absent | stored |
| `baseline_hourly_volume` | `baseline*.csv` | warn if absent | stored (Phase 3) |
| `coverage_requirements` | `coverage_requirements*.csv` | warn if absent | stored (Phase 3) |
| `reference_snapshot` | `snapshot*.csv` (several allowed) | no | verification only |
| `dataset_manifest.json` | exact name | no | project convention: label, synthetic flag, reference time |

Two files matching one table is an error. Unrecognized files are reported and ignored.

## 3. Column mapping (`mapping.py`)

Each internal field has an alias list. Headers are compared after normalization
(lowercase, non-alphanumerics → `_`), so `Phys.` → `phys` and `Event time` → `event_time`.
The brief's table headers (`Event`, `Ingested`, `Consult`, `Phys.`, `Hosp.`, `Opt-in`,
`Hrs 7d`, `Min to online`, …) are included as aliases. They are *not* treated as the
official schema.

- Missing required field → error listing the accepted aliases **and** the headers found,
  with the fix.
- Two headers matching one field → error.
- Unmapped columns are kept verbatim (`attributes` / `payload.attributes`) and listed.
- A trailing zone label on a header (`Shift (ET)` → `shift` + `et`) is recorded and used
  to interpret offset-less times in that column.

**If the judging schema differs**, put the header in a JSON override and point
`DATASET_MAPPING_FILE` at it. No code change is needed:

```json
{ "tables": { "hospitals": { "timezone": { "aliases": ["iana_zone"], "required": true } } } }
```

Other overridable settings include `events.status_description_pattern`,
`events.consult_type_description_pattern`, `true_values`/`false_values`,
`timezone_labels`, `datetimes.naive_timezone`,
`credentialing.hospital_header_prefix`, `snapshot.*_labels` and
`max_event_rejection_ratio`.

## 4. Validation

| Check | Result |
| --- | --- |
| Event timestamp without UTC offset | row rejected → `event_rejections` + warning |
| Event missing a required association / bad status value | row rejected (same) |
| > 5 % of event rows rejected, or none valid | **import fails** (format probably differs) |
| Unknown event type | stored + warning; not applied |
| Duplicate `event_id` | stored; first-ingested copy applied; conflicting content → warning |
| Event references unknown physician/hospital | warning (events kept) |
| Hospital time zone not IANA | mapped via `timezone_labels` (reported) or **error** |
| Duplicate hospital / physician IDs (across both rosters) | error |
| Credential/baseline/coverage row → unknown physician or hospital | error |
| Wide credential matrix header not matching a hospital | error (exact → configured prefix → unique `-suffix` match, each reported) |
| Bad booleans / numbers / hours / time blocks | error with file, row, column, value |
| Roster value without offset | interpreted (header zone → `naive_timezone` → the single offset shared by every event timestamp) and reported; else error |

Errors block the import; warnings and info do not. The report (`DatasetImportReport`)
carries every issue with `file`, `row`, `column`, `value` and `hint`, per-table row
counts, the column mapping actually used, and the chosen reference time and its source.

## 5. Atomic replacement (`persistence.py`)

Validation runs entirely in memory. Only a fully valid dataset is persisted, in **one
transaction**: delete the previous dataset (including injected events), insert the new
one, move the simulation clock to the reference time, bump `data_version`. Any failure
rolls back to the previous dataset untouched. Failed attempts are recorded in
`dataset_imports` and shown as `last_attempt` in `GET /api/datasets/status`.

## 6. Reference time

First match wins: `reference_time` on import → `dataset_manifest.json` →
`SIMULATION_REFERENCE_TIME` → snapshot file name `_HHMM` (in the latest event's own UTC
offset, accepted only within ±1 h of it) → latest `ingested_at` rounded up to the minute.
Events ingested after the reference time are kept and become visible as the clock
advances.

## 7. Snapshot verification

`GET /api/datasets/verification` replays to the reference time and compares physician
rows (activity, status, agent, consult/call/open counts, minutes to shift end) and
consult rows (stage, assignee, type, hospital, minutes in stage, presence) against the
snapshot files. Label maps (`snapshot.activity_labels`, `snapshot.stage_labels`) translate
display labels like "CT/CTA or Imaging Pending". Mismatches are reported as-is; the
engine is never tuned to force a match.

## Challenge-dataset header aliases and Eastern-labelled times (Phase 5 preflight)

The handbook's dataset uses headers that the original alias lists missed, so the real
`data/` folder failed to import. These aliases were added:

| File | Header | Internal field |
| --- | --- | --- |
| `physicians_off_shift_roster.csv` | `hours_worked_last_7d` | `hours_worked_trailing_7d` |
| `physicians_off_shift_roster.csv` | `est_minutes_to_online` | `minutes_to_come_online` |
| `physicians_off_shift_roster.csv` | `preferred_channel`, `offers_declined_last_30d` | channel, declines |
| `baseline_hourly_volume.csv` | `hour_start_et` (= `hour_start` + zone hint `et`), `dow_type` | `hour_local`, `day_type` |
| `coverage_requirements.csv` | `min_available_credentialed_physicians` | `min_available_physicians` |

Baseline hours and coverage blocks whose header carries a zone label (e.g. `_et`) are
converted to each hospital's local time. The engines read them as hospital-local, and
the conversion uses the UTC offsets on the dataset's reference date. For example, a
16:00–22:00 ET block is 15:00–21:00 at a Chicago hospital. The import report lists
which hospitals were shifted (`zone_hint_converted`). Tested in
`backend/tests/test_challenge_dataset.py`, which also appends a judge-style event CSV to
the loaded day.
