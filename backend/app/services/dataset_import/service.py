"""Dataset import orchestration: collect -> validate -> persist atomically -> report."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT, Settings
from app.core.errors import AppError, DatasetValidationError, NotFoundError
from app.core.time import utc_now
from app.repositories import EventRepository, ReferenceRepository, SystemRepository
from app.schemas.dataset import (
    ActiveDataset,
    DatasetImportReport,
    DatasetImportStatus,
    DatasetStatus,
    ImportIssue,
    IssueSeverity,
    SampleDataset,
    SnapshotVerification,
)
from app.services.dataset_import.manifest import DATASET_MANIFEST_FILENAME
from app.services.dataset_import.mapping import DatasetMapping, load_mapping
from app.services.dataset_import.persistence import replace_active_dataset
from app.services.dataset_import.pipeline import validate_dataset
from app.services.dataset_import.sources import (
    DatasetFile,
    SourceError,
    SourceLimits,
    collect_files,
    read_directory,
)
from app.services.dataset_import.verification import SnapshotRecord, verify_snapshot
from app.services.state import StateService

logger = logging.getLogger(__name__)


class DatasetService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.system = SystemRepository(session)

    @property
    def limits(self) -> SourceLimits:
        return SourceLimits(
            max_upload_bytes=self.settings.max_upload_bytes,
            max_uncompressed_bytes=self.settings.max_uncompressed_bytes,
            max_archive_entries=self.settings.max_archive_entries,
        )

    def mapping(self) -> DatasetMapping:
        return load_mapping(self.settings.resolved_dataset_mapping_file)

    # --- import ------------------------------------------------------------------

    def import_uploads(
        self, uploads: list[tuple[str, bytes]], reference_time: datetime | None
    ) -> DatasetImportReport:
        names = ", ".join(name for name, _ in uploads) or "upload"
        return self._run(lambda: collect_files(uploads, self.limits), names, reference_time)

    def import_challenge(self) -> DatasetImportReport:
        """Load the committed developer kit through the normal validation/replay pipeline."""
        directory = BACKEND_ROOT.parent / "data"
        return self._run(
            lambda: read_directory(directory, self.limits), "Challenge 2 developer kit", None
        )

    def samples(self) -> list[SampleDataset]:
        """Bundled sample datasets: sibling folders of SAMPLE_DATASET_DIR with a manifest."""
        default = self.settings.resolved_sample_dataset_dir
        found = []
        root = default.parent
        if root.is_dir():
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                manifest = folder / DATASET_MANIFEST_FILENAME
                if not manifest.is_file():
                    continue
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                found.append(
                    SampleDataset(
                        name=folder.name,
                        label=str(data.get("label") or folder.name),
                        synthetic=bool(data.get("synthetic", False)),
                        reference_time=data.get("reference_time"),
                        default=folder.resolve() == default.resolve(),
                    )
                )
        return found

    def import_sample(self, name: str | None = None) -> DatasetImportReport:
        directory = self.settings.resolved_sample_dataset_dir
        if name is not None and name != directory.name:
            known = {s.name for s in self.samples()}
            if name not in known:
                raise NotFoundError(
                    f"Unknown sample dataset '{name}'",
                    details={"available": sorted(known)},
                )
            directory = directory.parent / name
        return self._run(
            lambda: read_directory(directory, self.limits), f"sample:{directory.name}", None
        )

    def _fail(self, report: DatasetImportReport, message: str) -> DatasetValidationError:
        report.status = DatasetImportStatus.FAILED
        report.completed_at = utc_now()
        self.system.save_import_report(report)
        self.session.commit()
        return DatasetValidationError(message, details=report.model_dump(mode="json"))

    def _run(
        self, collect, source_name: str, reference_time: datetime | None
    ) -> DatasetImportReport:
        import_id = f"imp_{uuid.uuid4().hex[:12]}"
        started = utc_now()
        try:
            files: list[DatasetFile] = collect()
        except SourceError as exc:
            report = DatasetImportReport(
                import_id=import_id,
                status=DatasetImportStatus.FAILED,
                source_name=source_name,
                started_at=started,
                issues=exc.issues,
            )
            raise self._fail(
                report, "Dataset files were rejected; the active dataset is unchanged."
            ) from exc

        dataset = validate_dataset(
            files,
            self.mapping(),
            import_id=import_id,
            source_name=source_name,
            started_at=started,
            reference_override=reference_time,
            env_reference=self.settings.simulation_reference_time,
        )
        if not dataset.ok:
            errors = sum(1 for i in dataset.report.issues if i.severity is IssueSeverity.ERROR)
            raise self._fail(
                dataset.report,
                f"Dataset failed validation with {errors} error(s); "
                "the active dataset is unchanged.",
            )
        try:
            replace_active_dataset(self.session, dataset, now=utc_now())
        except Exception as exc:
            logger.exception("Dataset persistence failed; rolled back")
            dataset.report.issues.append(
                ImportIssue(
                    severity=IssueSeverity.ERROR,
                    code="persistence_failed",
                    message=f"saving the dataset failed and was rolled back: {type(exc).__name__}",
                )
            )
            self._fail(dataset.report, "")
            raise AppError(
                "Saving the dataset failed; the previous dataset was kept.",
                code="dataset_persist_failed",
                status_code=500,
                details=dataset.report.model_dump(mode="json"),
            ) from exc
        return dataset.report

    # --- status & verification ----------------------------------------------------

    def status(self) -> DatasetStatus:
        state = self.system.get_simulation_state()
        active_row = (
            self.system.get_import(state.active_import_id)
            if state and state.active_import_id
            else None
        )
        latest_row = self.system.latest_import()
        last_attempt = (
            DatasetImportReport.model_validate(latest_row.report)
            if latest_row and (active_row is None or latest_row.id != active_row.id)
            else None
        )
        if active_row is None:
            return DatasetStatus(loaded=False, last_attempt=last_attempt)

        report = DatasetImportReport.model_validate(active_row.report)
        events = EventRepository(self.session).counts()
        counts = {**ReferenceRepository(self.session).counts(), **events}
        return DatasetStatus(
            loaded=True,
            active=ActiveDataset(
                import_id=active_row.id,
                label=report.label,
                synthetic=report.synthetic,
                source_name=report.source_name,
                imported_at=report.completed_at or report.started_at,
                reference_time=state.reference_time if state else None,
                reference_source=state.reference_source if state else None,  # type: ignore[arg-type]
                counts=counts,
                live_events=events["live_events"],
                rejected_events=events["rejected_events"],
                warnings=sum(1 for i in report.issues if i.severity is IssueSeverity.WARNING),
            ),
            active_report=report,
            last_attempt=last_attempt,
        )

    def verify(self) -> SnapshotVerification:
        state_row = self.system.get_simulation_state()
        if not state_row or not state_row.active_import_id or state_row.reference_time is None:
            return SnapshotVerification(available=False, notes=["no dataset loaded"])
        rows = [
            SnapshotRecord(file=r.file, kind=r.kind, row_number=r.row_number, data=r.data)
            for r in ReferenceRepository(self.session).snapshot_rows()
        ]
        if not rows:
            return SnapshotVerification(
                available=False, notes=["dataset has no reference snapshot files"]
            )
        state = StateService(self.session, self.settings).state(
            state_row.reference_time, with_workflow=False
        )
        return verify_snapshot(state, rows, self.mapping())
