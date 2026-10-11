from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from pydantic import AwareDatetime, TypeAdapter, ValidationError

from app.api.deps import AppSettings, DbSession
from app.core.errors import AppError
from app.schemas.dataset import (
    DatasetImportReport,
    DatasetStatus,
    SampleDataset,
    SnapshotVerification,
)
from app.services.dataset_import.service import DatasetService

router = APIRouter(prefix="/datasets", tags=["datasets"])

_aware = TypeAdapter(AwareDatetime)


async def _read_limited(uploads: list[UploadFile], limit: int) -> list[tuple[str, bytes]]:
    total = 0
    files: list[tuple[str, bytes]] = []
    for upload in uploads:
        chunks: list[bytes] = []
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise AppError(
                    f"Upload exceeds {limit:,} bytes.",
                    code="upload_too_large",
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )
            chunks.append(chunk)
        files.append((upload.filename or "upload", b"".join(chunks)))
    return files


@router.post(
    "/import",
    response_model=DatasetImportReport,
    summary="Import a dataset (one ZIP, or several CSVs) and atomically replace the active one",
)
async def import_dataset(
    db: DbSession,
    settings: AppSettings,
    files: Annotated[list[UploadFile], File(description="A ZIP and/or the dataset CSV files")],
    reference_time: Annotated[
        str | None, Form(description="Optional simulation reference time (ISO-8601 with offset)")
    ] = None,
) -> DatasetImportReport:
    reference = None
    if reference_time:
        try:
            reference = _aware.validate_python(reference_time)
        except ValidationError as exc:
            raise AppError(
                "reference_time must be ISO-8601 with a UTC offset",
                code="validation_error",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            ) from exc
    uploads = await _read_limited(files, settings.max_upload_bytes)
    return DatasetService(db, settings).import_uploads(uploads, reference)


@router.post(
    "/challenge",
    response_model=DatasetImportReport,
    summary="Load the bundled Challenge 2 developer kit, replacing the active dataset",
)
def import_challenge(db: DbSession, settings: AppSettings) -> DatasetImportReport:
    return DatasetService(db, settings).import_challenge()


@router.post(
    "/sample",
    response_model=DatasetImportReport,
    summary="Load the bundled SYNTHETIC SAMPLE DATA (repeatable)",
)
def import_sample(
    db: DbSession,
    settings: AppSettings,
    name: Annotated[str | None, Query(description="Sample folder name; see GET /samples")] = None,
) -> DatasetImportReport:
    return DatasetService(db, settings).import_sample(name)


@router.get("/samples", response_model=list[SampleDataset], summary="Bundled sample datasets")
def list_samples(db: DbSession, settings: AppSettings) -> list[SampleDataset]:
    return DatasetService(db, settings).samples()


@router.get("/status", response_model=DatasetStatus)
def dataset_status(db: DbSession, settings: AppSettings) -> DatasetStatus:
    return DatasetService(db, settings).status()


@router.get(
    "/verification",
    response_model=SnapshotVerification,
    summary="Compare the replay at the reference time against the dataset's snapshot files",
)
def verify(db: DbSession, settings: AppSettings) -> SnapshotVerification:
    return DatasetService(db, settings).verify()
