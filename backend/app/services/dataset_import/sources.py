"""Collect dataset files from uploads, ZIP archives or a directory — safely.

ZIP archives are read in memory (never extracted to disk). Entries with absolute paths
or ``..`` components are rejected as path traversal attempts, and both the upload size
and the total uncompressed size are capped.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.schemas.dataset import ImportIssue, IssueSeverity


@dataclass(frozen=True)
class DatasetFile:
    name: str
    """Base file name (directories inside archives are flattened)."""
    data: bytes
    origin: str
    """Where it came from, e.g. 'upload' or 'archive.zip:folder/file.csv'."""


@dataclass(frozen=True)
class SourceLimits:
    max_upload_bytes: int
    max_uncompressed_bytes: int
    max_archive_entries: int


class SourceError(Exception):
    """Fatal problem with the uploaded files themselves (size, archive safety)."""

    def __init__(self, issues: list[ImportIssue]):
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues


def _issue(
    code: str, message: str, file: str | None = None, hint: str | None = None
) -> ImportIssue:
    return ImportIssue(
        severity=IssueSeverity.ERROR, code=code, message=message, file=file, hint=hint
    )


def _is_unsafe(member: str) -> bool:
    if member.startswith(("/", "\\")) or (len(member) > 1 and member[1] == ":"):
        return True
    parts = PurePosixPath(member.replace("\\", "/")).parts
    return ".." in parts


def _is_ignorable(member: str) -> bool:
    base = posixpath.basename(member)
    return member.startswith("__MACOSX/") or base.startswith(".") or not base


def expand_archive(name: str, data: bytes, limits: SourceLimits) -> list[DatasetFile]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SourceError(
            [_issue("archive_invalid", f"{name} is not a valid ZIP file", name)]
        ) from exc

    entries = [info for info in archive.infolist() if not info.is_dir()]
    unsafe = [info.filename for info in entries if _is_unsafe(info.filename)]
    if unsafe:
        raise SourceError(
            [
                _issue(
                    "archive_path_traversal",
                    f"{name} contains unsafe entry paths: {', '.join(unsafe[:5])}",
                    name,
                    "Re-create the archive with relative paths only.",
                )
            ]
        )
    if len(entries) > limits.max_archive_entries:
        raise SourceError(
            [
                _issue(
                    "archive_too_many_entries",
                    f"{name} has {len(entries)} entries (limit {limits.max_archive_entries})",
                    name,
                )
            ]
        )
    declared = sum(info.file_size for info in entries)
    if declared > limits.max_uncompressed_bytes:
        raise SourceError(
            [
                _issue(
                    "archive_too_large",
                    f"{name} expands to {declared:,} bytes "
                    f"(limit {limits.max_uncompressed_bytes:,})",
                    name,
                )
            ]
        )

    files: list[DatasetFile] = []
    total = 0
    for info in entries:
        if _is_ignorable(info.filename):
            continue
        # Read with a hard cap: declared sizes in a hostile archive can lie.
        with archive.open(info) as handle:
            content = handle.read(limits.max_uncompressed_bytes - total + 1)
        total += len(content)
        if total > limits.max_uncompressed_bytes:
            raise SourceError(
                [_issue("archive_too_large", f"{name} expands beyond the size limit", name)]
            )
        files.append(
            DatasetFile(
                name=posixpath.basename(info.filename),
                data=content,
                origin=f"{name}:{info.filename}",
            )
        )
    return files


def collect_files(uploads: list[tuple[str, bytes]], limits: SourceLimits) -> list[DatasetFile]:
    """Uploads may be any mix of CSV/JSON files and ZIP archives."""
    total = sum(len(data) for _, data in uploads)
    if total > limits.max_upload_bytes:
        raise SourceError(
            [
                _issue(
                    "upload_too_large",
                    f"upload is {total:,} bytes (limit {limits.max_upload_bytes:,})",
                )
            ]
        )
    files: list[DatasetFile] = []
    for raw_name, data in uploads:
        name = posixpath.basename(raw_name.replace("\\", "/")) or "upload"
        if name.lower().endswith(".zip"):
            files.extend(expand_archive(name, data, limits))
        else:
            files.append(DatasetFile(name=name, data=data, origin="upload"))
    return files


def read_directory(directory: Path, limits: SourceLimits) -> list[DatasetFile]:
    if not directory.is_dir():
        raise SourceError([_issue("directory_missing", f"{directory} does not exist")])
    uploads = [
        (path.name, path.read_bytes())
        for path in sorted(directory.iterdir())
        if path.is_file() and not path.name.startswith(".")
    ]
    return collect_files(uploads, limits)
