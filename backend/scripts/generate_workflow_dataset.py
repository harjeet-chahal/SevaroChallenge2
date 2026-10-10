"""Generate SYNTHETIC SAMPLE DATA for the Phase 5 workflow demo (``synthetic_workflow``).

It is the surge scenario (``generate_surge_dataset``, unchanged) plus exactly what the
Detect -> Decide -> Act demo needs and the surge fixture deliberately lacks:

- **A backup split-shift candidate.** SRG-P8 (Dr. Yara Surge) passes every rule for Ridge
  (SRG-H3) but comes online later than SRG-P6, so the optimizer still recommends P6 and P8
  can be added as a backup offer. This exercises "two physicians, one gap": the first
  binding acceptance wins and the other pending offer is withdrawn.
- **A busy hospital without a gap.** SRG-H4 (Lakeshore, Chicago) needs 1 physician and is
  covered by SRG-P3 all evening; SRG-P6 is also credentialed there. Its baseline gives
  modeled arrivals, so the split-shift trap is visible: unrestricted least-loaded routing
  would send the joining P6 Lakeshore's calls; the approved scope keeps P6 on Ridge.

The surge fixture and its hand-computed tests are untouched.

Regenerate: cd backend && .venv/bin/python -m scripts.generate_workflow_dataset
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

from scripts import generate_surge_dataset as surge

OUTPUT = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_workflow"
LABEL = "SYNTHETIC SAMPLE DATA — surge scenario + split-shift workflow demo"

H4 = ("SRG-H4", "Lakeshore Sample Center", "America/Chicago", "primary")
BACKUP = [
    "SRG-P8",
    "Dr. Yara Surge",
    "float",
    "yes",
    "2030-09-09T18:00:00-05:00",
    "2030-09-13T07:00:00-05:00",
    30,
    35,
    "sms",
    0,
]
CREDENTIALS = {"SRG-H3": ["SRG-P6", "SRG-P8"], "SRG-H4": ["SRG-P3", "SRG-P6"]}


def _rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


def _write(path: Path, rows: list[list[object]]) -> None:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def write_dataset(out: Path) -> None:
    surge.write_dataset(out)

    hospitals = _rows(out / "hospitals.csv")
    _write(out / "hospitals.csv", [*hospitals, list(H4)])

    coverage = _rows(out / "coverage_requirements.csv")
    _write(out / "coverage_requirements.csv", [*coverage, ["SRG-H4", "00:00", "00:00", 1]])

    baseline = _rows(out / "baseline_hourly_volume.csv")
    extra = [["SRG-H4", hour, 2.5, 4.0, "weekday"] for hour in range(24)]
    _write(out / "baseline_hourly_volume.csv", [*baseline, *extra])

    roster = _rows(out / "physicians_off_shift_roster.csv")
    _write(out / "physicians_off_shift_roster.csv", [*roster, BACKUP])

    header, *matrix = _rows(out / "credentialing_matrix.csv")
    rows = [row + [""] for row in matrix] + [[BACKUP[0], BACKUP[1], *[""] * (len(header) - 1)]]
    header = [*header, H4[0]]
    for row in rows:
        for hid, physicians in CREDENTIALS.items():
            if row[0] in physicians:
                row[header.index(hid)] = "Y"
    _write(out / "credentialing_matrix.csv", [header, *sorted(rows, key=lambda r: r[0])])

    manifest = json.loads((out / "dataset_manifest.json").read_text(encoding="utf-8"))
    manifest.update(label=LABEL, generator="backend/scripts/generate_workflow_dataset.py")
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    (out / "README.md").write_text(
        f"# {LABEL}\n\n"
        "**Everything here is invented.** The surge scenario (`synthetic_surge`) plus a backup "
        "split-shift candidate (Dr. Yara Surge, SRG-P8) and a busy hospital without a gap "
        "(Lakeshore, SRG-H4) where the recommended physician is also credentialed. Built for "
        "the Phase 5 demo: propose → approve → offer → accept → activate, conflicting "
        "acceptances and split-shift trap protection.\n\n"
        "Regenerate: `cd backend && .venv/bin/python -m scripts.generate_workflow_dataset`\n\n"
        "Load: `POST /api/datasets/sample?name=synthetic_workflow` or the UI sample picker.\n\n"
        "Expectations: `backend/tests/test_workflow.py`.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    write_dataset(target)
    print(f"Wrote SYNTHETIC SAMPLE DATA to {target}")
