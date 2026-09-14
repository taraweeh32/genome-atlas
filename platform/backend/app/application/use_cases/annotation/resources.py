"""Registering and governing annotation resource versions.

A registered annotation resource version is a versioned scientific identity: a
release of a consequence, transcript, gene, functional or external-database
resource, with the fields it declares it produces. The platform stores that
identity and the declaration; it never stores or reimplements the resource's
algorithm.

Three rules the use cases enforce:

* **Registration is platform governance.** No tenant role can register, activate,
  deprecate or retire a resource version.
* **A version is immutable.** Registering a correction means registering a new
  version. Nothing rewrites the identity a historical run already named.
* **Activation is explicit.** A newly registered version is not usable until an
  administrator activates it, and a retired or invalidated version never becomes
  usable again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.annotation.dependencies import (
    AnnotationServices,
    require_platform_administration,
)
from app.domain.annotation.entities import AnnotationFieldSpec, AnnotationResourceRecord
from app.domain.annotation.fields import annotation_field_definitions
from app.domain.authorization.context import ActorContext
from app.domain.errors import NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.query.fields import FilterFieldDefinition
from app.domain.value_objects.enums import (
    AnnotationResourceCategory,
    AuditOutcome,
    ScientificResourceState,
)
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class RegisterResourceCommand:
    actor: ActorContext
    request: RequestContext
    resource_key: str
    version: str
    display_name: str
    category: AnnotationResourceCategory
    provider: str | None = None
    description: str | None = None
    genome_assembly: str | None = None
    reference_genome_resource_id: str | None = None
    release_label: str | None = None
    released_at: datetime | None = None
    schema_version: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    size_bytes: int | None = None
    fields: tuple[AnnotationFieldSpec, ...] = ()
    provenance: dict[str, Any] | None = None
    licensing: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class RegisterAnnotationResource:
    """Register one new annotation resource version, in ``registered`` state."""

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    async def execute(
        self, command: RegisterResourceCommand
    ) -> AnnotationResourceRecord:
        now = self._services.clock.now()
        if not command.fields:
            # A resource that declares no field can never be validated against and
            # would silently accept anything. Refusing keeps ingestion meaningful.
            raise ValidationError(
                "an annotation resource must declare at least one field",
                details={"field": "fields"},
            )
        seen: set[str] = set()
        for specification in command.fields:
            if specification.field_key in seen:
                raise ValidationError(
                    "a field key is declared twice",
                    details={"field": "fields", "field_key": specification.field_key},
                )
            seen.add(specification.field_key)

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await require_platform_administration(
                self._services,
                repositories,
                command.actor,
                recorder=recorder,
                occurred_at=now,
            )
            record = AnnotationResourceRecord(
                id=new_id("anr"),
                resource_key=command.resource_key.strip(),
                version=command.version.strip(),
                display_name=command.display_name.strip(),
                category=command.category,
                state=ScientificResourceState.REGISTERED,
                provider=command.provider,
                description=command.description,
                genome_assembly=command.genome_assembly,
                reference_genome_resource_id=command.reference_genome_resource_id,
                release_label=command.release_label,
                released_at=command.released_at,
                schema_version=command.schema_version,
                checksum_algorithm=command.checksum_algorithm,
                checksum_value=command.checksum_value,
                size_bytes=command.size_bytes,
                fields=command.fields,
                provenance=dict(command.provenance or {}),
                licensing=dict(command.licensing or {}),
                metadata=dict(command.metadata or {}),
                registered_by=command.actor.actor_id,
                created_at=now,
            )
            stored = await repositories.annotation_resources.add(record)
            await recorder.audit(
                action="annotation_resource.registered",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="annotation_resource",
                resource_id=stored.id,
                new_state=stored.state.value,
                detail={
                    "resource_key": stored.resource_key,
                    "version": stored.version,
                    "category": stored.category.value,
                    "field_count": len(stored.fields),
                    "checksum_value": stored.checksum_value,
                },
            )
            await recorder.event(
                event_type=EventType.ANNOTATION_RESOURCE_REGISTERED,
                aggregate_type="annotation_resource",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "resource_key": stored.resource_key,
                    "version": stored.version,
                    "category": stored.category.value,
                },
            )
        if self._services.dictionary is not None:
            # The dictionary composition changes as soon as this becomes usable;
            # invalidating now means an administrator sees their own change.
            self._services.dictionary.invalidate()
        return stored


@dataclass(frozen=True, slots=True)
class TransitionResourceCommand:
    actor: ActorContext
    request: RequestContext
    resource_id: str
    state: ScientificResourceState
    reason: str | None = None


class TransitionAnnotationResource:
    """Move one resource version through its lifecycle, or refuse."""

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    async def execute(
        self, command: TransitionResourceCommand
    ) -> AnnotationResourceRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await require_platform_administration(
                self._services,
                repositories,
                command.actor,
                recorder=recorder,
                occurred_at=now,
            )
            current = await repositories.annotation_resources.get(command.resource_id)
            if current is None:
                raise NotFoundError("annotation_resource", command.resource_id)
            # The entity owns which transitions exist; a rejected transition raises
            # a conflict rather than being silently ignored.
            updated = current.transition_to(
                command.state, at=now, reason=command.reason
            )
            stored = await repositories.annotation_resources.save(updated)
            await recorder.audit(
                action="annotation_resource.state_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="annotation_resource",
                resource_id=stored.id,
                previous_state=current.state.value,
                new_state=stored.state.value,
                detail={
                    "resource_key": stored.resource_key,
                    "version": stored.version,
                    "reason": command.reason,
                },
            )
            await recorder.event(
                event_type=EventType.ANNOTATION_RESOURCE_STATE_CHANGED,
                aggregate_type="annotation_resource",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={
                    "from": current.state.value,
                    "to": stored.state.value,
                    "resource_key": stored.resource_key,
                    "version": stored.version,
                },
            )
        if self._services.dictionary is not None:
            self._services.dictionary.invalidate()
        return stored


@dataclass(frozen=True, slots=True)
class ListResourcesQuery:
    actor: ActorContext
    request: RequestContext
    page: Page
    category: AnnotationResourceCategory | None = None
    resource_key: str | None = None
    usable_only: bool = False


class AnnotationResourceCatalogue:
    """Reads of the registry.

    Reads are open to any account holding the platform annotation-read permission:
    a resource version is not tenant content, and a user who cannot see which
    resource produced a value cannot judge that value at all.
    """

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    async def _require_read(
        self, repositories: Any, actor: ActorContext, recorder: ActivityRecorder, now
    ) -> None:
        from app.application.use_cases.annotation.dependencies import PLATFORM_READ

        await self._services.authorization.require(
            actor, PLATFORM_READ, recorder=recorder, occurred_at=now
        )

    async def list(self, query: ListResourcesQuery) -> Paged[AnnotationResourceRecord]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._require_read(repositories, query.actor, recorder, now)
            return await repositories.annotation_resources.list_resources(
                page=query.page,
                category=query.category,
                resource_key=query.resource_key,
                usable_only=query.usable_only,
            )

    async def get(
        self, actor: ActorContext, request: RequestContext, resource_id: str
    ) -> AnnotationResourceRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await self._require_read(repositories, actor, recorder, now)
            record = await repositories.annotation_resources.get(resource_id)
            if record is None:
                raise NotFoundError("annotation_resource", resource_id)
            return record

    async def fields(
        self, actor: ActorContext, request: RequestContext
    ) -> tuple[FilterFieldDefinition, ...]:
        """The annotation fields currently projected into the field dictionary.

        Returned as ordinary field definitions, so the frontend renders them with
        the same code that renders platform fields and hardcodes nothing.
        """
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await self._require_read(repositories, actor, recorder, now)
            resources = await repositories.annotation_resources.list_field_sources()
        return annotation_field_definitions(tuple(resources))


__all__ = [
    "AnnotationResourceCatalogue",
    "ListResourcesQuery",
    "RegisterAnnotationResource",
    "RegisterResourceCommand",
    "TransitionAnnotationResource",
    "TransitionResourceCommand",
]
