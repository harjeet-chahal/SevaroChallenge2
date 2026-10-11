"""Collect dataset files from uploads, ZIP archives or a directory — safely.

ZIP archives are read in memory (never extracted to disk). Entries with absolute paths
or ``..`` components are rejected as path traversal attempts. The upload size, and the
uncompressed size and archive-entry count summed over the whole upload (every archive
and plain file), are capped. Corrupt, encrypted or unsupported archives are a
``SourceError`` (a 422 with an import report), never an unhandled exception.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.schemas.dataset import ImportIssue, IssueSeverity

try:  # optional in some Python builds; zipfile only needs it for LZMA entries
    import lzma
except ImportError:  # pragma: no cover
    lzma = None  # type: ignore[assignment]


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


class _Budget:
    """What is left of the per-upload limits. One instance is shared by every archive and
    plain file in an upload, so several small archives cannot add up past the limit."""

    def __init__(self, limits: SourceLimits) -> None:
        self.limits = limits
        self.bytes_left = limits.max_uncompressed_bytes
        self.entries_left = limits.max_archive_entries

    def spend_bytes(self, count: int, *, name: str) -> None:
        self.bytes_left -= count
        if self.bytes_left < 0:
            raise SourceError(
                [
                    _issue(
                        "archive_too_large",
                        f"the upload expands beyond {self.limits.max_uncompressed_bytes:,} bytes "
                        f"in total (limit reached at {name})",
                        name,
                    )
                ]
            )


_UNREADABLE_ENTRY_ERRORS: tuple[type[BaseException], ...] = (
    zipfile.BadZipFile,  # CRC mismatch, bad local header, truncated data
    zipfile.LargeZipFile,
    RuntimeError,  # encrypted entry (no password); NotImplementedError is a subclass
    zlib.error,
    EOFError,
    OSError,  # bz2 data errors
    ValueError,
    *([lzma.LZMAError] if lzma is not None else []),
)


def _read_entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo, name: str, cap: int) -> bytes:
    """Read one member, at most ``cap + 1`` bytes (declared sizes in a hostile archive
    can lie). Corrupt, encrypted or unsupported entries are a SourceError."""
    if info.flag_bits & 0x1:
        raise SourceError(
            [
                _issue(
                    "archive_encrypted",
                    f"{name}: '{info.filename}' is password-protected",
                    name,
                    "Upload an archive without a password.",
                )
            ]
        )
    try:
        with archive.open(info) as handle:
            return handle.read(cap + 1)
    except _UNREADABLE_ENTRY_ERRORS as exc:
        reason = str(exc) or type(exc).__name__
        raise SourceError(
            [
                _issue(
                    "archive_unreadable",
                    f"{name}: '{info.filename}' could not be read ({reason})",
                    name,
                    "The archive is corrupt or uses an unsupported compression method; "
                    "re-create it as a standard (deflate) ZIP.",
                )
            ]
        ) from exc


def expand_archive(
    name: str, data: bytes, limits: SourceLimits, budget: _Budget | None = None
) -> list[DatasetFile]:
    budget = budget or _Budget(limits)
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = [info for info in archive.infolist() if not info.is_dir()]
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError, ValueError) as exc:
        raise SourceError(
            [_issue("archive_invalid", f"{name} is not a valid ZIP file", name)]
        ) from exc

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
    budget.entries_left -= len(entries)
    if budget.entries_left < 0:
        raise SourceError(
            [
                _issue(
                    "archive_too_many_entries",
                    f"{name} has {len(entries)} entries; the upload's archives exceed the "
                    f"limit of {limits.max_archive_entries} entries in total",
                    name,
                )
            ]
        )
    declared = sum(info.file_size for info in entries)
    if declared > budget.bytes_left:
        raise SourceError(
            [
                _issue(
                    "archive_too_large",
                    f"{name} expands to {declared:,} bytes "
                    f"(limit {limits.max_uncompressed_bytes:,} for the whole upload; "
                    f"{max(budget.bytes_left, 0):,} left)",
                    name,
                )
            ]
        )

    files: list[DatasetFile] = []
    for info in entries:
        if _is_ignorable(info.filename):
            continue
        content = _read_entry(archive, info, name, max(budget.bytes_left, 0))
        budget.spend_bytes(len(content), name=name)
        files.append(
            DatasetFile(
                name=posixpath.basename(info.filename),
                data=content,
                origin=f"{name}:{info.filename}",
            )
        )
    return files


def collect_files(uploads: list[tuple[str, bytes]], limits: SourceLimits) -> list[DatasetFile]:
    """Uploads may be any mix of CSV/JSON files and ZIP archives. The uncompressed-size and
    archive-entry limits apply to the upload as a whole."""
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
    budget = _Budget(limits)
    files: list[DatasetFile] = []
    for raw_name, data in uploads:
        name = posixpath.basename(raw_name.replace("\\", "/")) or "upload"
        if name.lower().endswith(".zip"):
            files.extend(expand_archive(name, data, limits, budget))
        else:
            budget.spend_bytes(len(data), name=name)
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
