"""Registering and governing evidence source versions.

A registered evidence source version is a versioned scientific identity: one
release of a clinical database, a literature corpus, a population resource, a
functional-study collection, a curated knowledge base, or the platform's own
internal curation. The platform stores that identity; it never stores or
reimplements what the source concluded, and it privileges no particular source.

Three rules the use cases enforce:

* **Registration is platform governance.** No tenant role can register, activate,
  deprecate or retire a source version.
* **A version is immutable.** Registering a correction means registering a new
  version, so evidence that named release ``2024-05`` keeps naming it.
* **Activation is explicit.** A newly registered version cannot supply evidence
  until an administrator activates it, and a retired or invalidated version never
  becomes usable again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.evidence.dependencies import (
    EvidenceServices,
    require_platform_administration,
    require_platform_read,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.evidence.entities import EvidenceSourceRecord
from app.domain.value_objects.enums import (
    AuditOutcome,
    EvidenceCategory,
    EvidenceSourceCategory,
    ScientificResourceState,
)
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class RegisterSourceCommand:
    actor: ActorContext
    request: RequestContext
    source_key: str
    version: str
    display_name: str
    category: EvidenceSourceCategory
    provider: str | None = None
    description: str | None = None
    release_label: str | None = None
    released_at: datetime | None = None
    retrieved_at: datetime | None = None
    schema_version: str | None = None
    genome_assembly: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    size_bytes: int | None = None
    supplies: tuple[EvidenceCategory, ...] = ()
    supplies_strength: bool = False
    provenance: dict[str, Any] | None = None
    licensing: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class RegisterEvidenceSource:
    """Register one new evidence source version, in ``registered`` state."""

    def __init__(self, services: EvidenceServices) -> None:
        self._services = services

    async def execute(self, command: RegisterSourceCommand) -> EvidenceSourceRecord:
        now = self._services.clock.now()
        if not command.supplies:
            # A source that declares no evidence category cannot be validated
            # against and would silently accept anything.
            raise ValidationError(
                "an evidence source must declare at least one evidence category",
                details={"field": "supplies"},
            )
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await require_platform_administration(
                self._services, command.actor, recorder=recorder, occurred_at=now
            )
            existing = await repositories.evidence_sources.get_by_version(
                source_key=command.source_key.strip(), version=command.version.strip()
            )
            if existing is not None:
                from app.domain.errors import ConflictError

                raise ConflictError(
                    "this evidence source version is already registered",
                    details={
                        "source_key": existing.source_key,
                        "version": existing.version,
                    },
                )
            record = EvidenceSourceRecord(
                id=new_id("evs"),
                source_key=command.source_key.strip(),
                version=command.version.strip(),
                display_name=command.display_name.strip(),
                category=command.category,
                state=ScientificResourceState.REGISTERED,
                provider=command.provider,
                description=command.description,
                release_label=command.release_label,
                released_at=command.released_at,
                retrieved_at=command.retrieved_at,
                schema_version=command.schema_version,
                genome_assembly=command.genome_assembly,
                checksum_algorithm=command.checksum_algorithm,
                checksum_value=command.checksum_value,
                size_bytes=command.size_bytes,
                supplies=tuple(dict.fromkeys(command.supplies)),
                supplies_strength=command.supplies_strength,
                provenance=dict(command.provenance or {}),
                licensing=dict(command.licensing or {}),
                metadata=dict(command.metadata or {}),
                registered_by=command.actor.actor_id,
                created_at=now,
            )
            stored = await repositories.evidence_sources.add(record)
            await recorder.audit(
                action="evidence_source.registered",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="evidence_source",
                resource_id=stored.id,
                new_state=stored.state.value,
                detail={
                    "source_key": stored.source_key,
                    "version": stored.version,
                    "category": stored.category.value,
                    "supplies": [item.value for item in stored.supplies],
                    "checksum_value": stored.checksum_value,
                },
            )
            await recorder.event(
                event_type=EventType.EVIDENCE_SOURCE_REGISTERED,
                aggregate_type="evidence_source",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "source_key": stored.source_key,
                    "version": stored.version,
                    "category": stored.category.value,
                },
            )
        return stored


@dataclass(frozen=True, slots=True)
class TransitionSourceCommand:
    actor: ActorContext
    request: RequestContext
    source_id: str
    state: ScientificResourceState
    reason: str | None = None


class TransitionEvidenceSource:
    """Move one source version through its lifecycle, or refuse."""

    def __init__(self, services: EvidenceServices) -> None:
        self._services = services

    async def execute(self, command: TransitionSourceCommand) -> EvidenceSourceRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await require_platform_administration(
                self._services, command.actor, recorder=recorder, occurred_at=now
            )
            current = await repositories.evidence_sources.get(command.source_id)
            if current is None:
                raise NotFoundError("evidence_source", command.source_id)
            updated = current.transition_to(command.state, at=now, reason=command.reason)
            stored = await repositories.evidence_sources.save(updated)
            await recorder.audit(
                action="evidence_source.state_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="evidence_source",
                resource_id=stored.id,
                previous_state=current.state.value,
                new_state=stored.state.value,
                detail={
                    "source_key": stored.source_key,
                    "version": stored.version,
                    "reason": command.reason,
                },
            )
            await recorder.event(
                event_type=EventType.EVIDENCE_SOURCE_STATE_CHANGED,
                aggregate_type="evidence_source",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "from": current.state.value,
                    "to": stored.state.value,
                    "source_key": stored.source_key,
                    "version": stored.version,
                },
            )
        return stored


@dataclass(frozen=True, slots=True)
class ListSourcesQuery:
    actor: ActorContext
    request: RequestContext
    page: Page
    category: EvidenceSourceCategory | None = None
    source_key: str | None = None
    usable_only: bool = False


class EvidenceSourceCatalogue:
    """Reads of the source registry.

    Open to any account holding the platform evidence-read permission: a source
    version is not tenant content, and someone who cannot see which source and
    release produced a piece of evidence cannot judge that evidence at all.
    """

    def __init__(self, services: EvidenceServices) -> None:
        self._services = services

    async def list(self, query: ListSourcesQuery) -> Paged[EvidenceSourceRecord]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await require_platform_read(
                self._services, query.actor, recorder=recorder, occurred_at=now
            )
            return await repositories.evidence_sources.list_sources(
                page=query.page,
                category=query.category,
                source_key=query.source_key,
                usable_only=query.usable_only,
            )

    async def get(
        self, actor: ActorContext, request: RequestContext, source_id: str
    ) -> EvidenceSourceRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await require_platform_read(
                self._services, actor, recorder=recorder, occurred_at=now
            )
            record = await repositories.evidence_sources.get(source_id)
            if record is None:
                raise NotFoundError("evidence_source", source_id)
            return record


__all__ = [
    "EvidenceSourceCatalogue",
    "ListSourcesQuery",
    "RegisterEvidenceSource",
    "RegisterSourceCommand",
    "TransitionEvidenceSource",
    "TransitionSourceCommand",
]
