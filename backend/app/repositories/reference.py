from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.db.models import (
    BaselineVolumeRecord,
    CoverageRequirementRecord,
    HospitalRecord,
    PhysicianCredential,
    PhysicianRecord,
    ReferenceSnapshotRow,
)
from app.schemas.coverage import BaselineVolume, CoverageRequirement
from app.schemas.hospital import Hospital
from app.schemas.physician import Physician, PhysicianSchedule, ShiftWindow
from app.schemas.state import ReferenceData


class ReferenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def load(self) -> ReferenceData:
        hospitals = [
            Hospital.model_validate(row)
            for row in self.session.scalars(select(HospitalRecord).order_by(HospitalRecord.id))
        ]
        creds: dict[str, list[str]] = defaultdict(list)
        for cred in self.session.scalars(
            select(PhysicianCredential).order_by(
                PhysicianCredential.physician_id, PhysicianCredential.hospital_id
            )
        ):
            creds[cred.physician_id].append(cred.hospital_id)
        physicians = [
            Physician(
                id=row.id,
                display_name=row.display_name,
                roster=row.roster,  # type: ignore[arg-type]
                roster_role=row.roster_role,
                credentialed_hospital_ids=creds.get(row.id, []),
                split_shift_opt_in=row.split_shift_opt_in,
                notification_channel=row.notification_channel,
                schedule=PhysicianSchedule(
                    current_shift=(
                        ShiftWindow(start=row.shift_start_at, end=row.shift_end_at)
                        if row.shift_start_at and row.shift_end_at
                        else None
                    ),
                    last_shift_ended_at=row.last_shift_ended_at,
                    next_shift_starts_at=row.next_shift_starts_at,
                    hours_worked_trailing_7d=row.hours_worked_trailing_7d,
                    minutes_to_come_online=row.minutes_to_come_online,
                    offers_declined_30d=row.offers_declined_30d,
                ),
                attributes=row.attributes or {},
            )
            for row in self.session.scalars(select(PhysicianRecord).order_by(PhysicianRecord.id))
        ]
        return ReferenceData(
            hospitals=hospitals,
            physicians=physicians,
            coverage_requirements=[
                CoverageRequirement.model_validate(r)
                for r in self.session.scalars(
                    select(CoverageRequirementRecord).order_by(CoverageRequirementRecord.id)
                )
            ],
            baseline_volume=[
                BaselineVolume.model_validate(r)
                for r in self.session.scalars(
                    select(BaselineVolumeRecord).order_by(BaselineVolumeRecord.id)
                )
            ],
        )

    def snapshot_rows(self) -> list[ReferenceSnapshotRow]:
        return list(
            self.session.scalars(select(ReferenceSnapshotRow).order_by(ReferenceSnapshotRow.id))
        )

    def counts(self) -> dict[str, int]:
        def count(model) -> int:
            return self.session.scalar(select(func.count()).select_from(model)) or 0

        return {
            "hospitals": count(HospitalRecord),
            "physicians": count(PhysicianRecord),
            "credentials": count(PhysicianCredential),
            "coverage_requirements": count(CoverageRequirementRecord),
            "baseline_rows": count(BaselineVolumeRecord),
            "snapshot_rows": count(ReferenceSnapshotRow),
        }

    def delete_all(self) -> None:
        for model in (
            ReferenceSnapshotRow,
            PhysicianCredential,
            CoverageRequirementRecord,
            BaselineVolumeRecord,
            PhysicianRecord,
            HospitalRecord,
        ):
            self.session.execute(delete(model))

    def insert(
        self,
        *,
        hospitals: Iterable[Hospital],
        physicians: Iterable[Physician],
        coverage: Iterable[CoverageRequirement],
        baseline: Iterable[BaselineVolume],
        snapshot_rows: Iterable[tuple[str, str, int, dict]],
    ) -> None:
        def bulk(model, values: list[dict]) -> None:
            if values:
                self.session.execute(insert(model), values)

        physicians = list(physicians)
        bulk(
            HospitalRecord,
            [
                h.model_dump(include={"id", "name", "timezone", "coverage_tier", "attributes"})
                for h in hospitals
            ],
        )
        bulk(
            PhysicianRecord,
            [
                {
                    "id": p.id,
                    "display_name": p.display_name,
                    "roster": p.roster,
                    "roster_role": p.roster_role,
                    "split_shift_opt_in": p.split_shift_opt_in,
                    "notification_channel": p.notification_channel,
                    "shift_start_at": p.schedule.current_shift.start
                    if p.schedule.current_shift
                    else None,
                    "shift_end_at": p.schedule.current_shift.end
                    if p.schedule.current_shift
                    else None,
                    "last_shift_ended_at": p.schedule.last_shift_ended_at,
                    "next_shift_starts_at": p.schedule.next_shift_starts_at,
                    "hours_worked_trailing_7d": p.schedule.hours_worked_trailing_7d,
                    "minutes_to_come_online": p.schedule.minutes_to_come_online,
                    "offers_declined_30d": p.schedule.offers_declined_30d,
                    "attributes": p.attributes,
                }
                for p in physicians
            ],
        )
        bulk(
            PhysicianCredential,
            [
                {"physician_id": p.id, "hospital_id": h}
                for p in physicians
                for h in p.credentialed_hospital_ids
            ],
        )
        bulk(CoverageRequirementRecord, [c.model_dump() for c in coverage])
        bulk(BaselineVolumeRecord, [b.model_dump() for b in baseline])
        bulk(
            ReferenceSnapshotRow,
            [{"file": f, "kind": k, "row_number": n, "data": d} for f, k, n, d in snapshot_rows],
        )
