from __future__ import annotations

from app.schemas.dataset import ImportIssue, IssueSeverity


class IssueLog:
    """Collects import issues. Errors are always counted; storage is capped for readability."""

    def __init__(self, limit: int = 300) -> None:
        self.limit = limit
        self.issues: list[ImportIssue] = []
        self.truncated = 0
        self.errors = 0

    def add(
        self,
        severity: IssueSeverity,
        code: str,
        message: str,
        *,
        file: str | None = None,
        row: int | None = None,
        column: str | None = None,
        value: str | None = None,
        hint: str | None = None,
    ) -> None:
        if severity is IssueSeverity.ERROR:
            self.errors += 1
        if len(self.issues) >= self.limit:
            self.truncated += 1
            return
        self.issues.append(
            ImportIssue(
                severity=severity,
                code=code,
                message=message,
                file=file,
                row=row,
                column=column,
                value=value[:200] if value else value,
                hint=hint,
            )
        )

    @property
    def has_errors(self) -> bool:
        return self.errors > 0
