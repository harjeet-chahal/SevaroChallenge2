"""Voluntary availability from the off-shift portal: create, update, list, withdraw.

Availability is a preference the scheduling system reads, never an assignment:

- only an off-shift roster physician (``X-Demo-Role: physician`` with their own ID) can
  share or change it; coordinators and clinical leads can read it;
- every change runs in the workflow's serialized write transaction and writes an audit
  record, which bumps ``workflow_version``. The staffing optimizer's cache is keyed on that
  version and ``/api/live`` broadcasts it, so the coordinator's ranking recomputes at once;
- rows belong to the active dataset import (a re-import starts a new day) and are never
  deleted: withdrawal is a status, kept in history.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.time import utc_now
from app.db.models import AvailabilityRecord
from app.engines.optimization import load_optimization_config
from app.repositories import ReferenceRepository, SystemRepository
from app.repositories.availability import ACTIVE, WITHDRAWN, AvailabilityRepository
from app.schemas.availability import (
    AvailabilityCreate,
    AvailabilityPage,
    AvailabilityStatus,
    AvailabilityUpdate,
    PhysicianAvailabilityPage,
    VolunteerAvailability,
)
from app.schemas.common import ActorRef, UserRole
from app.schemas.physician import Physician
from app.schemas.state import ReferenceData
from app.services.simulation import SimulationService
from app.services.workflow import _WRITE_LOCK, require_role
from app.services.workflow_records import write_audit

MIN_WINDOW_MINUTES = 30
MAX_WINDOW_MINUTES = 24 * 60
MAX_DAYS_AHEAD = 14
MAX_ACTIVE_WINDOWS = 5

NOT_ASSIGNED = (
    "Shared with the coordination team. This is not a shift assignment: if a shift is "
    "needed, an offer approved by a clinical lead will appear here for you to accept or decline."
)


def _invalid(message: str, **details) -> AppError:
    return AppError(message, code="availability_invalid", status_code=422, details=details or None)


class AvailabilityService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = AvailabilityRepository(session)
        self.system = SystemRepository(session)
        self.sim = SimulationService(session, settings)
        self._reference: ReferenceData | None = None

    # ------------------------------------------------------------------ plumbing --

    @contextmanager
    def _write(self) -> Iterator[None]:
        """Same serialization as the workflow: process lock + SQLite ``BEGIN IMMEDIATE``."""
        with _WRITE_LOCK:
            self.session.rollback()
            connection = self.session.connection()
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield
                self.session.commit()
            except BaseException:
                self.session.rollback()
                raise

    def _import_id(self) -> str | None:
        state = self.system.get_simulation_state()
        return state.active_import_id if state else None

    def _ref(self) -> ReferenceData:
        if self._reference is None:
            self._reference = ReferenceRepository(self.session).load()
        return self._reference

    def _physicians(self) -> dict[str, Physician]:
        return {p.id: p for p in self._ref().physicians}

    def _timezone(self, profile: Physician | None) -> str:
        reference = self._ref()
        zones = {h.id: h.timezone for h in reference.hospitals}
        for hid in profile.credentialed_hospital_ids if profile else []:
            if hid in zones:
                return zones[hid]
        return reference.hospitals[0].timezone if reference.hospitals else "UTC"

    @staticmethod
    def _require_physician(actor: ActorRef, action: str) -> str:
        require_role(actor, UserRole.PHYSICIAN, action=action)
        if not actor.actor_id:
            raise AppError(
                "X-Demo-Actor-Id (the physician's ID) is required.",
                code="actor_required",
                status_code=401,
            )
        return actor.actor_id

    def _owned(self, availability_id: str, physician_id: str) -> AvailabilityRecord:
        rec = self.repo.get(availability_id)
        if rec is None or rec.dataset_import_id != self._import_id():
            raise NotFoundError(f"Availability {availability_id} not found")
        if rec.physician_id != physician_id:
            raise AppError(
                "A physician can only change their own availability.",
                code="permission_denied",
                status_code=403,
            )
        return rec

    def _validate(
        self,
        physician_id: str,
        start: datetime,
        end: datetime,
        now: datetime,
        *,
        current: AvailabilityRecord | None = None,
    ) -> Physician:
        profile = self._physicians().get(physician_id)
        if profile is None or profile.roster != "off_shift":
            raise _invalid(
                "Only physicians on the off-shift roster can share availability for an extra "
                "shift.",
                physician_id=physician_id,
            )
        minutes = (end - start).total_seconds() / 60
        if end <= start:
            raise _invalid("The window must end after it starts.")
        if minutes < MIN_WINDOW_MINUTES:
            raise _invalid(f"The window must be at least {MIN_WINDOW_MINUTES} minutes long.")
        if minutes > MAX_WINDOW_MINUTES:
            raise _invalid("The window can be at most 24 hours long.")
        if end <= now:
            raise _invalid(
                "The window has already ended at the current simulation time.",
                simulation_time=now.isoformat(),
            )
        keeps_start = current is not None and start == current.start_at
        if start < now and not keeps_start:
            raise _invalid(
                "The window starts before the current simulation time; choose a start from now.",
                simulation_time=now.isoformat(),
            )
        if start > now + timedelta(days=MAX_DAYS_AHEAD):
            raise _invalid(f"Availability can be shared at most {MAX_DAYS_AHEAD} days ahead.")
        others = [
            r
            for r in self.repo.list(
                self._import_id(), physician_id=physician_id, statuses=(ACTIVE,)
            )
            if r.end_at > now and (current is None or r.id != current.id)
        ]
        clash = next((r for r in others if r.start_at < end and start < r.end_at), None)
        if clash is not None:
            raise ConflictError(
                f"This overlaps your availability {clash.id}; update or withdraw that one instead.",
                code="availability_overlap",
                details={"availability_id": clash.id},
            )
        if current is None and len(others) >= MAX_ACTIVE_WINDOWS:
            raise ConflictError(
                f"At most {MAX_ACTIVE_WINDOWS} upcoming availability windows at a time.",
                code="availability_limit",
            )
        return profile

    # ------------------------------------------------------------------- render --

    def _view(
        self, rec: AvailabilityRecord, now: datetime, actor: ActorRef, tz: str
    ) -> VolunteerAvailability:
        status = AvailabilityStatus(rec.status)
        if status is AvailabilityStatus.WITHDRAWN:
            phase, message = "withdrawn", "Withdrawn — coordinators no longer see this window."
        elif rec.end_at <= now:
            phase, message = "past", "This window has ended."
        elif rec.start_at <= now:
            phase, message = "current", NOT_ASSIGNED
        else:
            phase, message = "upcoming", NOT_ASSIGNED
        mine = actor.role is UserRole.PHYSICIAN and actor.actor_id == rec.physician_id
        editable = mine and phase in ("current", "upcoming")
        return VolunteerAvailability(
            id=rec.id,
            physician_id=rec.physician_id,
            display_name=rec.display_name,
            status=status,
            start_at=rec.start_at,
            end_at=rec.end_at,
            duration_minutes=round((rec.end_at - rec.start_at).total_seconds() / 60),
            timezone=tz,
            created_at=rec.created_at,
            updated_at=rec.updated_at,
            withdrawn_at=rec.withdrawn_at,
            version=rec.version,
            phase=phase,  # type: ignore[arg-type]
            can_update=editable,
            can_withdraw=editable,
            message=message,
        )

    def _render(self, rec: AvailabilityRecord, actor: ActorRef) -> VolunteerAvailability:
        now = self.sim.current_time() or utc_now()
        return self._view(rec, now, actor, self._timezone(self._physicians().get(rec.physician_id)))

    # -------------------------------------------------------------------- reads --

    def mine(self, actor: ActorRef) -> PhysicianAvailabilityPage:
        physician_id = self._require_physician(actor, "view their availability")
        now = self.sim.require_current_time()
        profile = self._physicians().get(physician_id)
        tz = self._timezone(profile)
        cfg = load_optimization_config(self.settings.resolved_optimization_policy_file)
        online = (
            profile.schedule.minutes_to_come_online
            if profile and profile.schedule.minutes_to_come_online is not None
            else cfg.staffing.assumed_online_minutes_if_missing
        )
        min_useful = cfg.staffing.min_offer_minutes + online
        notes: list[str] = []
        if profile is None or profile.roster != "off_shift":
            notes.append(
                "Only physicians on the off-shift roster can share availability for an extra shift."
            )
        elif profile.split_shift_opt_in is not True:
            notes.append(
                "You are not opted in to split-shift offers on the roster, so the scheduling "
                "system cannot match this availability to an offer until your opt-in is updated."
            )
        notes.append(
            f"Offers are at least {cfg.staffing.min_offer_minutes // 60} h of coverage after "
            f"you come online (about {online} min for you), so a window of "
            f"{min_useful // 60} h {min_useful % 60:02d} min or more can be matched to an offer."
        )
        rows = self.repo.list(self._import_id(), physician_id=physician_id)
        return PhysicianAvailabilityPage(
            physician_id=physician_id,
            display_name=profile.display_name if profile else physician_id,
            timezone=tz,
            simulation_time=now,
            opted_in=profile.split_shift_opt_in if profile else None,
            min_useful_window_minutes=min_useful,
            max_window_minutes=MAX_WINDOW_MINUTES,
            items=[self._view(r, now, actor, tz) for r in reversed(rows)],
            notes=notes,
        )

    def list_all(self, actor: ActorRef, scope: str = "active") -> AvailabilityPage:
        require_role(
            actor, UserRole.COORDINATOR, UserRole.CLINICAL_LEAD, action="view all availability"
        )
        now = self.sim.current_time() or utc_now()
        statuses = (ACTIVE,) if scope == "active" else None
        rows = self.repo.list(self._import_id(), statuses=statuses)
        if scope == "active":
            rows = [r for r in rows if r.end_at > now]
        profiles = self._physicians()
        items = [
            self._view(r, now, actor, self._timezone(profiles.get(r.physician_id))) for r in rows
        ]
        return AvailabilityPage(total=len(items), items=items)

    def get(self, availability_id: str, actor: ActorRef) -> VolunteerAvailability:
        rec = self.repo.get(availability_id)
        if rec is None or rec.dataset_import_id != self._import_id():
            raise NotFoundError(f"Availability {availability_id} not found")
        if actor.role is UserRole.PHYSICIAN:
            self._owned(availability_id, self._require_physician(actor, "view availability"))
        else:
            require_role(
                actor, UserRole.COORDINATOR, UserRole.CLINICAL_LEAD, action="view availability"
            )
        return self._render(rec, actor)

    # ------------------------------------------------------------------- writes --

    def create(self, body: AvailabilityCreate, actor: ActorRef) -> VolunteerAvailability:
        physician_id = self._require_physician(actor, "share availability")
        with self._write():
            now = self.sim.require_current_time()
            profile = self._validate(physician_id, body.start_at, body.end_at, now)
            rec = AvailabilityRecord(
                id=self.repo.next_id(),
                physician_id=physician_id,
                display_name=profile.display_name,
                dataset_import_id=self._import_id(),
                status=ACTIVE,
                start_at=body.start_at,
                end_at=body.end_at,
                created_at=now,
                updated_at=now,
                recorded_at=utc_now(),
                version=1,
            )
            self.session.add(rec)
            self.session.flush()
            write_audit(
                self.session,
                at=now,
                actor=actor,
                action="availability_submitted",
                summary=f"{profile.display_name} shared voluntary availability {rec.id} "
                f"({rec.start_at.isoformat()} – {rec.end_at.isoformat()}). Not an assignment.",
                entity_type="availability",
                entity_id=rec.id,
                to_status=ACTIVE,
                details={"start_at": rec.start_at, "end_at": rec.end_at},
            )
            new_id = rec.id
        return self._render(self.repo.get(new_id), actor)  # type: ignore[arg-type]

    def update(
        self, availability_id: str, body: AvailabilityUpdate, actor: ActorRef
    ) -> VolunteerAvailability:
        physician_id = self._require_physician(actor, "update availability")
        with self._write():
            now = self.sim.require_current_time()
            rec = self._owned(availability_id, physician_id)
            if rec.status != ACTIVE:
                raise ConflictError(
                    f"Availability {rec.id} was withdrawn; share a new window instead.",
                    code="availability_withdrawn",
                )
            if body.expected_version is not None and body.expected_version != rec.version:
                raise ConflictError(
                    f"Availability {rec.id} changed since it was loaded.",
                    code="stale_version",
                    details={"current_version": rec.version},
                )
            if rec.end_at <= now:
                raise ConflictError(
                    f"Availability {rec.id} has already ended.", code="availability_ended"
                )
            self._validate(physician_id, body.start_at, body.end_at, now, current=rec)
            before = {"start_at": rec.start_at, "end_at": rec.end_at}
            rec.start_at, rec.end_at = body.start_at, body.end_at
            rec.updated_at, rec.recorded_at = now, utc_now()
            rec.version += 1
            write_audit(
                self.session,
                at=now,
                actor=actor,
                action="availability_updated",
                summary=f"{rec.display_name} updated voluntary availability {rec.id} to "
                f"{rec.start_at.isoformat()} – {rec.end_at.isoformat()}.",
                entity_type="availability",
                entity_id=rec.id,
                from_status=ACTIVE,
                to_status=ACTIVE,
                details={
                    "before": before,
                    "after": {"start_at": rec.start_at, "end_at": rec.end_at},
                },
            )
        return self._render(rec, actor)

    def withdraw(self, availability_id: str, actor: ActorRef) -> VolunteerAvailability:
        """Withdraw a window. Repeating it is harmless (returns the withdrawn window)."""
        physician_id = self._require_physician(actor, "withdraw availability")
        with self._write():
            now = self.sim.require_current_time()
            rec = self._owned(availability_id, physician_id)
            if rec.status == ACTIVE:
                rec.status = WITHDRAWN
                rec.withdrawn_at = now
                rec.updated_at, rec.recorded_at = now, utc_now()
                rec.version += 1
                write_audit(
                    self.session,
                    at=now,
                    actor=actor,
                    action="availability_withdrawn",
                    summary=f"{rec.display_name} withdrew voluntary availability {rec.id}; it no "
                    "longer affects recommendations.",
                    entity_type="availability",
                    entity_id=rec.id,
                    from_status=ACTIVE,
                    to_status=WITHDRAWN,
                )
        return self._render(rec, actor)
