"""Compare a replayed state against reference snapshot rows (pure).

Mismatches are reported exactly as found. The engine is never adjusted to match.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.engines.event_processing import normalize_label
from app.schemas.dataset import SnapshotMismatch, SnapshotVerification
from app.schemas.state import OperationalState
from app.services.dataset_import.mapping import DatasetMapping


@dataclass(frozen=True)
class SnapshotRecord:
    file: str
    kind: str
    row_number: int
    data: dict[str, Any]


def _columns(data: dict[str, Any], spec) -> dict[str, Any]:
    by_norm = {normalize_label(k): v for k, v in data.items()}
    out: dict[str, Any] = {}
    for name, column in spec.items():
        for alias in column.aliases:
            if alias in by_norm and str(by_norm[alias]).strip() != "":
                out[name] = str(by_norm[alias]).strip()
                break
    return out


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class _Comparer:
    def __init__(self) -> None:
        self.mismatches: list[SnapshotMismatch] = []
        self.fields = 0

    def check(
        self, kind: str, entity: str, field: str, expected: Any, actual: Any, *, tolerance: int = 0
    ):
        self.fields += 1
        if isinstance(expected, int) and isinstance(actual, int):
            same = abs(expected - actual) <= tolerance
        else:
            same = expected == actual
        if not same:
            self.mismatches.append(
                SnapshotMismatch(
                    kind=kind, entity_id=entity, field=field, expected=expected, actual=actual
                )
            )


def verify_snapshot(
    state: OperationalState, rows: Iterable[SnapshotRecord], mapping: DatasetMapping
) -> SnapshotVerification:
    rows = list(rows)
    if not rows:
        return SnapshotVerification(
            available=False, notes=["no reference snapshot files in the dataset"]
        )
    labels = mapping.snapshot
    cmp = _Comparer()
    notes: list[str] = []
    physicians = {p.physician_id: p for p in state.physicians}
    consults = {c.consult_id: c for c in state.consultations}
    entities = 0
    snapshot_consults: set[str] = set()

    for row in rows:
        if row.kind == "physicians":
            v = _columns(row.data, mapping.columns("snapshot_physicians"))
            pid = v.get("physician_id")
            if not pid:
                continue
            entities += 1
            p = physicians.get(pid)
            if p is None:
                cmp.check("physician", pid, "present", True, False)
                continue
            if "derived_state" in v:
                expected = labels.activity_labels.get(normalize_label(v["derived_state"]))
                if expected is None:
                    notes.append(f"{row.file}: unmapped activity label '{v['derived_state']}'")
                else:
                    cmp.check("physician", pid, "activity", expected, p.activity.value)
            if "self_reported" in v:
                status = mapping.events.status_labels.get(normalize_label(v["self_reported"]))
                cmp.check(
                    "physician",
                    pid,
                    "self_reported_status",
                    status.value if status else v["self_reported"],
                    p.signals.self_reported_status.value,
                )
            if "agent" in v:
                cmp.check(
                    "physician",
                    pid,
                    "agent",
                    normalize_label(v["agent"]),
                    "offline" if p.signals.agent_online is False else "online",
                )
            for field, actual in (
                ("consults", p.consults_this_shift),
                ("calls", p.calls_this_shift),
                ("open_consults", len(p.open_consult_ids)),
            ):
                if field in v:
                    cmp.check("physician", pid, field, _int(v[field]), actual)
            if "minutes_to_end" in v:
                cmp.check(
                    "physician",
                    pid,
                    "minutes_to_shift_end",
                    _int(v["minutes_to_end"]),
                    p.minutes_to_shift_end,
                    tolerance=1,
                )

        elif row.kind == "consults":
            v = _columns(row.data, mapping.columns("snapshot_consults"))
            cid = v.get("consult_id")
            if not cid:
                continue
            entities += 1
            snapshot_consults.add(cid)
            c = consults.get(cid)
            if c is None:
                cmp.check("consult", cid, "present", True, False)
                continue
            cmp.check("consult", cid, "is_open", True, c.is_open)
            if "stage" in v:
                expected = labels.stage_labels.get(normalize_label(v["stage"]))
                if expected is None:
                    notes.append(f"{row.file}: unmapped stage label '{v['stage']}'")
                else:
                    cmp.check("consult", cid, "stage", expected, c.stage.value)
            physician = v.get("physician", "")
            if normalize_label(physician) in labels.unassigned_values:
                physician = None
            cmp.check("consult", cid, "assigned_physician_id", physician, c.assigned_physician_id)
            if "consult_type" in v and c.consult_type:
                cmp.check(
                    "consult",
                    cid,
                    "consult_type",
                    normalize_label(v["consult_type"]),
                    normalize_label(c.consult_type),
                )
            if "hospital" in v and c.hospital_id:
                cmp.check(
                    "consult",
                    cid,
                    "hospital_id",
                    True,
                    c.hospital_id.lower() in v["hospital"].lower(),
                )
            if "minutes_in_stage" in v:
                cmp.check(
                    "consult",
                    cid,
                    "minutes_in_stage",
                    _int(v["minutes_in_stage"]),
                    c.seconds_in_stage // 60,
                    tolerance=1,
                )
            if "minutes_since_received" in v and c.seconds_since_received is not None:
                cmp.check(
                    "consult",
                    cid,
                    "minutes_since_received",
                    _int(v["minutes_since_received"]),
                    c.seconds_since_received // 60,
                    tolerance=1,
                )

    if snapshot_consults:
        for c in state.consultations:
            if c.is_open and c.consult_id not in snapshot_consults:
                cmp.check("consult", c.consult_id, "present_in_snapshot", False, True)

    return SnapshotVerification(
        available=True,
        as_of=state.as_of,
        files=sorted({r.file for r in rows}),
        compared_entities=entities,
        compared_fields=cmp.fields,
        mismatches=cmp.mismatches,
        notes=sorted(set(notes)),
    )
