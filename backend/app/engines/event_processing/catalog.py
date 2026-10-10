"""What each documented event type must carry.

Only associations the brief makes explicit (or that a state transition cannot work
without) are required. Anything else on an event is optional.
"""

from __future__ import annotations

from app.schemas.event import KnownEventType as E

REQUIRED_FIELDS: dict[E, tuple[str, ...]] = {
    E.CONSULT_RECEIVED: ("consult_id", "hospital_id"),
    E.CONSULT_TRIAGED: ("consult_id",),
    E.PHYSICIAN_ASSIGNED: ("consult_id", "physician_id"),
    E.INCOMING_CALL_RINGING: ("physician_id",),
    E.INCOMING_CALL_STARTED: ("physician_id",),
    E.INCOMING_CALL_ENDED: ("physician_id",),
    E.OUTGOING_CALL_STARTED: ("physician_id",),
    E.OUTGOING_CALL_ENDED: ("physician_id",),
    E.IMAGING_REQUESTED: ("consult_id",),
    E.IMAGING_RETURNED: ("consult_id",),
    E.VIDEO_STARTED: ("physician_id", "consult_id"),
    E.VIDEO_ENDED: ("physician_id", "consult_id"),
    E.NOTE_STARTED: ("consult_id",),
    E.NOTE_SIGNED: ("consult_id",),
    E.ROUTING_ATTEMPT_FAILED: ("consult_id",),
    E.PHYSICIAN_STATUS_CHANGED: ("physician_id",),
    E.CAMERA_ACTIVE: ("physician_id",),
    E.CAMERA_INACTIVE: ("physician_id",),
    E.AGENT_HEARTBEAT_LOST: ("physician_id",),
    E.SHIFT_STARTED: ("physician_id",),
}
