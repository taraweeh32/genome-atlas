"""Annotation execution profiles and their immutable versions.

A profile version is the reproducibility unit of this package: it states which
resource versions are used, in which reference context, through which capability,
with which parameters, and requires which provenance. A run records the profile
version it used, so re-reading a historical run tells you exactly what produced it.

Two rules:

* **A version never changes.** Editing a profile appends a version. Once any
  version has been used by a run the profile is marked referenced, and existing
  versions are frozen for good.
* **Only usable resources may be pinned.** A retired or invalidated resource
  version cannot enter a new profile version, because the platform could not
  honestly claim a new run used it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.annotation.dependencies import (
    PLATFORM_READ,
    AnnotationServices,
    require_platform_administration,
)
from app.domain.annotation.entities import (
    AnnotationProfileRecord,
    AnnotationProfileVersionRecord,
    ProfileResourceBinding,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import AuditOutcome
from app.infrastructure.persistence.repositories.base import new_id


def configuration_digest(
    *,
    capability_id: str,
    capability_version: str | None,
    resources: tuple[ProfileResourceBinding, ...],
    genome_assembly: str | None,
    parameters: dict[str, Any],
) -> str:
    """Digest of everything that decides what a run computes.

    Recorded on the version and on every run, so two runs claiming the same
    configuration can be proven to have had the same configuration.
    """
    canonical = {
        "capability_id": capability_id,
        "capability_version": capability_version,
        "genome_assembly": genome_assembly,
        "resources": sorted(
            (binding.resource_key, binding.resource_version, binding.role or "")
            for binding in resources
        ),
        "parameters": parameters,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ProfileVersionInput:
    capability_id: str
    resource_ids: tuple[str, ...]
    capability_version: str | None = None
    engine_resource_id: str | None = None
    engine_version: str | None = None
    genome_assembly: str | None = None
    reference_genome_resource_id: str | None = None
    required_inputs: tuple[str, ...] = ("result_set",)
    parameters: dict[str, Any] | None = None
    provenance_requirements: tuple[str, ...] = (
        "resource_identity",
        "engine_identity",
    )
    schema_version: str | None = None
    change_note: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CreateProfileCommand:
    actor: ActorContext
    request: RequestContext
    name: str
    version: ProfileVersionInput
    description: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AnnotationProfileView:
    profile: AnnotationProfileRecord
    versions: tuple[AnnotationProfileVersionRecord, ...] = ()


class AnnotationProfileService:
    """Create, version, publish and read annotation profiles."""

    def __init__(self, services: AnnotationServices) -> None:
        self._services = services

    # --- writes ---------------------------------------------------------- #

    async def create(self, command: CreateProfileCommand) -> AnnotationProfileView:
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
            profile = AnnotationProfileRecord(
                id=new_id("anp"),
                name=command.name.strip(),
                description=command.description,
                metadata=dict(command.metadata or {}),
                created_by=command.actor.actor_id,
                created_at=now,
            )
            stored = await repositories.annotation_profiles.add(profile)
            version = await self._append_version(
                repositories,
                recorder,
                actor=command.actor,
                profile=stored,
                payload=command.version,
                now=now,
            )
            return AnnotationProfileView(
                profile=await repositories.annotation_profiles.get(stored.id)
                or stored,
                versions=(version,),
            )

    async def add_version(
        self,
        actor: ActorContext,
        request: RequestContext,
        profile_id: str,
        payload: ProfileVersionInput,
    ) -> AnnotationProfileVersionRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await require_platform_administration(
                self._services, repositories, actor, recorder=recorder, occurred_at=now
            )
            profile = await repositories.annotation_profiles.get(profile_id)
            if profile is None:
                raise NotFoundError("annotation_profile", profile_id)
            return await self._append_version(
                repositories,
                recorder,
                actor=actor,
                profile=profile,
                payload=payload,
                now=now,
            )

    async def publish(
        self, actor: ActorContext, request: RequestContext, profile_id: str
    ) -> AnnotationProfileRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await require_platform_administration(
                self._services, repositories, actor, recorder=recorder, occurred_at=now
            )
            profile = await repositories.annotation_profiles.get(profile_id)
            if profile is None:
                raise NotFoundError("annotation_profile", profile_id)
            stored = await repositories.annotation_profiles.save(profile.published())
            await recorder.audit(
                action="annotation_profile.published",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="annotation_profile",
                resource_id=stored.id,
                previous_state=profile.state.value,
                new_state=stored.state.value,
                detail={"latest_version_number": stored.latest_version_number},
            )
            await recorder.event(
                event_type=EventType.ANNOTATION_PROFILE_PUBLISHED,
                aggregate_type="annotation_profile",
                aggregate_id=stored.id,
                occurred_at=now,
                payload={"latest_version_number": stored.latest_version_number},
            )
            return stored

    async def archive(
        self, actor: ActorContext, request: RequestContext, profile_id: str
    ) -> AnnotationProfileRecord:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await require_platform_administration(
                self._services, repositories, actor, recorder=recorder, occurred_at=now
            )
            profile = await repositories.annotation_profiles.get(profile_id)
            if profile is None:
                raise NotFoundError("annotation_profile", profile_id)
            stored = await repositories.annotation_profiles.save(profile.archived())
            await recorder.audit(
                action="annotation_profile.archived",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="annotation_profile",
                resource_id=stored.id,
                previous_state=profile.state.value,
                new_state=stored.state.value,
            )
            return stored

    # --- reads ----------------------------------------------------------- #

    async def list(
        self,
        actor: ActorContext,
        request: RequestContext,
        page: Page,
        *,
        offered_only: bool = False,
    ) -> Paged[AnnotationProfileRecord]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await self._services.authorization.require(
                actor, PLATFORM_READ, recorder=recorder, occurred_at=now
            )
            return await repositories.annotation_profiles.list_profiles(
                page=page, offered_only=offered_only
            )

    async def get(
        self, actor: ActorContext, request: RequestContext, profile_id: str
    ) -> AnnotationProfileView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            await self._services.authorization.require(
                actor, PLATFORM_READ, recorder=recorder, occurred_at=now
            )
            profile = await repositories.annotation_profiles.get(profile_id)
            if profile is None:
                raise NotFoundError("annotation_profile", profile_id)
            versions = await repositories.annotation_profiles.list_versions(
                profile_id=profile.id, page=Page(number=1, size=50)
            )
            return AnnotationProfileView(profile=profile, versions=versions.items)

    # --- internals ------------------------------------------------------- #

    async def _append_version(
        self,
        repositories: Any,
        recorder: ActivityRecorder,
        *,
        actor: ActorContext,
        profile: AnnotationProfileRecord,
        payload: ProfileVersionInput,
        now,
    ) -> AnnotationProfileVersionRecord:
        if not payload.resource_ids:
            raise ValidationError(
                "an annotation profile version must pin at least one resource",
                details={"field": "resource_ids"},
            )
        bindings: list[ProfileResourceBinding] = []
        output_fields: list[str] = []
        assemblies: set[str] = set()
        for resource_id in dict.fromkeys(payload.resource_ids):
            resource = await repositories.annotation_resources.get(resource_id)
            if resource is None:
                raise NotFoundError("annotation_resource", resource_id)
            if not resource.is_usable:
                # Pinning an unusable version would let a new run claim provenance
                # the platform has withdrawn.
                raise ConflictError(
                    "this annotation resource version is not usable",
                    details={
                        "annotation_resource_id": resource.id,
                        "state": resource.state.value,
                    },
                )
            bindings.append(
                ProfileResourceBinding(
                    resource_id=resource.id,
                    resource_key=resource.resource_key,
                    resource_version=resource.version,
                    category=resource.category,
                )
            )
            output_fields.extend(
                specification.field_key for specification in resource.fields
            )
            if resource.genome_assembly:
                assemblies.add(resource.genome_assembly)

        assembly = payload.genome_assembly
        if assembly is None and len(assemblies) == 1:
            assembly = next(iter(assemblies))
        if assembly is not None and assemblies and assembly not in assemblies:
            raise ConflictError(
                "the pinned resources do not state this reference context",
                details={
                    "genome_assembly": assembly,
                    "resource_assemblies": sorted(assemblies),
                },
            )
        if len(assemblies) > 1 and payload.genome_assembly is None:
            # Mixed reference contexts are a real configuration, but the platform
            # will not guess which one a run is stated against.
            raise ValidationError(
                "the pinned resources state different reference contexts; name one",
                details={
                    "field": "genome_assembly",
                    "resource_assemblies": sorted(assemblies),
                },
            )

        parameters = dict(payload.parameters or {})
        pinned = tuple(bindings)
        version = AnnotationProfileVersionRecord(
            id=new_id("apv"),
            profile_id=profile.id,
            version_number=profile.latest_version_number + 1,
            capability_id=payload.capability_id.strip(),
            resources=pinned,
            configuration_digest=configuration_digest(
                capability_id=payload.capability_id.strip(),
                capability_version=payload.capability_version,
                resources=pinned,
                genome_assembly=assembly,
                parameters=parameters,
            ),
            capability_version=payload.capability_version,
            engine_resource_id=payload.engine_resource_id,
            engine_version=payload.engine_version,
            genome_assembly=assembly,
            reference_genome_resource_id=payload.reference_genome_resource_id,
            required_inputs=payload.required_inputs,
            output_field_keys=tuple(dict.fromkeys(output_fields)),
            parameters=parameters,
            provenance_requirements=payload.provenance_requirements,
            schema_version=payload.schema_version,
            change_note=payload.change_note,
            metadata=dict(payload.metadata or {}),
            created_by=actor.actor_id,
            created_at=now,
        )
        stored_version = await repositories.annotation_profiles.add_version(version)
        from dataclasses import replace

        await repositories.annotation_profiles.save(
            replace(
                profile,
                latest_version_number=stored_version.version_number,
                updated_by=actor.actor_id,
            )
        )
        await recorder.audit(
            action="annotation_profile.version_added",
            outcome=AuditOutcome.SUCCESS,
            occurred_at=now,
            actor_user_id=actor.actor_id,
            resource_type="annotation_profile_version",
            resource_id=stored_version.id,
            new_state=str(stored_version.version_number),
            detail={
                "annotation_profile_id": profile.id,
                "capability_id": stored_version.capability_id,
                "configuration_digest": stored_version.configuration_digest,
                "resources": [
                    f"{binding.resource_key}:{binding.resource_version}"
                    for binding in stored_version.resources
                ],
            },
        )
        await recorder.event(
            event_type=EventType.ANNOTATION_PROFILE_VERSION_ADDED,
            aggregate_type="annotation_profile",
            aggregate_id=profile.id,
            occurred_at=now,
            payload={
                "version_number": stored_version.version_number,
                "configuration_digest": stored_version.configuration_digest,
            },
        )
        return stored_version


__all__ = [
    "AnnotationProfileService",
    "AnnotationProfileView",
    "CreateProfileCommand",
    "ProfileVersionInput",
    "configuration_digest",
]
