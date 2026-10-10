# SYNTHETIC SAMPLE DATA — development fixture

**Everything in this folder is invented.** No real physicians, hospitals, patients or
schedules. IDs (`DEV-*`), names, dates (May 2030) and times are deliberately unlike the
challenge examples, and none of the challenge's expected outcomes are reproduced.

Regenerate (deterministic, fixed seed):

```bash
cd backend && .venv/bin/python -m scripts.generate_sample_dataset
```

Load it: `POST /api/datasets/sample`, or **Load synthetic sample** in the UI.

Reference time: `2030-05-14T17:30:00-04:00` (from `dataset_manifest.json`, a project
convention; it is not part of the challenge format).

What it exercises:

| Situation | Where |
| --- | --- |
| 5 hospitals in 5 IANA zones (incl. America/Phoenix, no DST) | `hospitals.csv` |
| Event times in hospital-local offsets, ingest times in UTC `Z` | `event_stream.csv` |
| One physician with 3 open consults in 3 stages (video / imaging pending / note pending) | DEV-P01 |
| Late `video_started` (7.5 min) — state differs before vs after it arrives | DEV-C101 |
| Active call with camera on; duplicate call-start event (same `event_id`) | DEV-P02 / DEV-C104 |
| Camera active with no Synapse session; older `camera_inactive` arriving 50 min late | DEV-P03 |
| In Meeting + camera; events arriving opposite to occurrence order | DEV-P04 |
| Desktop agent offline + phone ringing | DEV-P05 |
| Temporarily Unavailable with an assigned stroke consult | DEV-P06 / DEV-C108 |
| Unassigned consult with repeated routing failures; duplicate `consult_received` | DEV-C109 |
| Undocumented event type (`sample_unrecognized_event`) — stored and reported | DEV-P04 |
| Malformed row (timestamp without offset) — rejected and reported | DEV-P04 |
| Events ingested after the reference time — revealed by advancing the clock | several |
| Off-shift roster, credentials, baselines, coverage blocks (kept for later phases) | other CSVs |
| Expected state at the reference time, written from the scenario script | `snapshot_*_ref.csv` |
