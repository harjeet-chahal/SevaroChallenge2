"""Logical tables a dataset may contain.

File names come from the challenge brief's data-package list. Matching patterns live in
``mapping.py`` so they can be overridden without code changes.
"""

from __future__ import annotations

from enum import StrEnum


class LogicalTable(StrEnum):
    EVENT_STREAM = "event_stream"
    HOSPITALS = "hospitals"
    PHYSICIANS_ON_SHIFT = "physicians_on_shift"
    PHYSICIANS_OFF_SHIFT = "physicians_off_shift_roster"
    CREDENTIALING = "credentialing_matrix"
    BASELINE_VOLUME = "baseline_hourly_volume"
    COVERAGE_REQUIREMENTS = "coverage_requirements"
    REFERENCE_SNAPSHOT = "reference_snapshot"


# Tables that may legitimately span several files (e.g. physician + consult snapshots).
MULTI_FILE_TABLES = frozenset({LogicalTable.REFERENCE_SNAPSHOT})

DATASET_MANIFEST_FILENAME = "dataset_manifest.json"
"""Optional project convention (not part of the challenge format): label, synthetic flag
and reference time for a dataset. Used by the bundled SYNTHETIC SAMPLE DATA."""
