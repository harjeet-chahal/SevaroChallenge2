"""ORM models. Importing this package registers every table on ``Base.metadata``."""

from app.db.models.event import EventLogEntry, EventRejectionRecord
from app.db.models.reference import (
    BaselineVolumeRecord,
    CoverageRequirementRecord,
    HospitalRecord,
    PhysicianCredential,
    PhysicianRecord,
    ReferenceSnapshotRow,
)
from app.db.models.system import AppMeta, DatasetImport, SimulationState
from app.db.models.workflow import (
    ApprovalRecord,
    AuditLogEntry,
    InterventionRecord,
    OfferRecord,
    OfferResponseRecord,
)

__all__ = [
    "AppMeta",
    "ApprovalRecord",
    "AuditLogEntry",
    "BaselineVolumeRecord",
    "CoverageRequirementRecord",
    "DatasetImport",
    "EventLogEntry",
    "EventRejectionRecord",
    "HospitalRecord",
    "InterventionRecord",
    "OfferRecord",
    "OfferResponseRecord",
    "PhysicianCredential",
    "PhysicianRecord",
    "ReferenceSnapshotRow",
    "SimulationState",
]
