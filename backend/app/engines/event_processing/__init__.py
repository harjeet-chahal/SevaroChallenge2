"""Event processing: validate, identify, de-duplicate and order operational events.

Pure functions only (no HTTP, no SQL):
- ``normalize_event``: one raw record -> ``NormalizedEvent`` or ``EventValidationError``
- ``annotate_event_log``: duplicate / out-of-order classification for a whole log
- ``replay_sort_key`` / ``is_visible``: the ordering and visibility policy
"""

from app.engines.event_processing.log import (
    AnnotatedEvent,
    annotate_event_log,
    ingestion_sort_key,
    is_visible,
    replay_sort_key,
)
from app.engines.event_processing.normalize import (
    CANONICAL_EVENT_FIELDS,
    DEFAULT_EVENT_RULES,
    EventParsingRules,
    EventValidationError,
    NormalizationResult,
    normalize_event,
    normalize_label,
)

__all__ = [
    "CANONICAL_EVENT_FIELDS",
    "DEFAULT_EVENT_RULES",
    "AnnotatedEvent",
    "EventParsingRules",
    "EventValidationError",
    "NormalizationResult",
    "annotate_event_log",
    "ingestion_sort_key",
    "is_visible",
    "normalize_event",
    "normalize_label",
    "replay_sort_key",
]
