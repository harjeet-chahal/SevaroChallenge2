"""Atomic dataset replacement.

Everything happens in one database transaction: delete the previous dataset, insert the
new one, close the previous dataset's open workflow items (audited, never deleted), move
the simulation clock. Any failure rolls back to the previous dataset
untouched. Validation has already happened, so this only fails on infrastructure errors.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories import EventRepository, ReferenceRepository, SystemRepository
from app.schemas.dataset import DatasetImportStatus
from app.schemas.event import EventSource
from app.services.dataset_import.pipeline import ValidatedDataset
from app.services.workflow_records import close_workflow_for_dataset_replacement


def replace_active_dataset(session: Session, dataset: ValidatedDataset, *, now: datetime) -> None:
    if not dataset.ok:
        raise ValueError("refusing to persist a dataset that failed validation")
    report = dataset.report
    system, events, reference = (
        SystemRepository(session),
        EventRepository(session),
        ReferenceRepository(session),
    )
    try:
        report.status = DatasetImportStatus.COMPLETED
        report.completed_at = now
        system.save_import_report(report)
        session.flush()

        events.delete_all()
        reference.delete_all()
        reference.insert(
            hospitals=dataset.hospitals,
            physicians=dataset.physicians,
            coverage=dataset.coverage,
            baseline=dataset.baseline,
            snapshot_rows=[(r.file, r.kind, r.row_number, r.data) for r in dataset.snapshot_rows],
        )
        events.add(dataset.events, report.import_id)
        for rejected in dataset.rejected:
            events.add_rejection(
                source=EventSource.DATASET_IMPORT,
                import_id=report.import_id,
                source_file=rejected.source_file,
                source_row=rejected.source_row,
                event_id=rejected.event_id,
                event_type=rejected.event_type,
                errors=rejected.errors,
                raw=rejected.raw,
                recorded_at=now,
            )

        state = system.get_or_create_simulation_state(now)
        # Re-import policy (Phase 5): open workflow items of the previous dataset are
        # closed and audited at that dataset's simulation time, never deleted.
        close_workflow_for_dataset_replacement(
            session,
            previous_import_id=state.active_import_id,
            new_import_id=report.import_id,
            at=state.current_time or now,
        )
        state.reference_time = report.reference_time
        state.reference_source = report.reference_source
        state.current_time = report.reference_time
        state.active_import_id = report.import_id
        state.data_version = (state.data_version or 0) + 1
        state.updated_at = now
        session.commit()
    except Exception:
        session.rollback()
        report.status = DatasetImportStatus.FAILED
        raise
