"""Persistence for annotation resources, profiles, runs and result versions.

Properties enforced by the statements themselves:

* **One registry.** An annotation resource version is a ``scientific_resources``
  row of kind ``annotation_resource``; the fields it declares are child rows. No
  second resource registry exists, so annotation resources inherit the platform's
  existing resource lifecycle and governance.
* **Profiles are append-only.** There is no UPDATE against
  ``annotation_profile_versions`` except flipping ``is_referenced``, which records
  a fact instead of altering content. A run therefore keeps referring to exactly
  the configuration it used.
* **Results are versioned, never replaced.** ``latest_version_number`` reads the
  highest version for one annotated surface and resource key; ingestion writes
  the next one. Nothing UPDATEs a previous result's content.
* **Concurrent edits are detected.** Mutable rows use ``UPDATE ... WHERE version =
  :expected``, so the loser of a race is told to re-read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, func, insert, select, update

from app.application.repositories import Page, Paged
from app.domain.errors import NotFoundError
from app.domain.annotation.entities import (
    AnnotationFieldSpec,
    AnnotationProfileRecord,
    AnnotationProfileVersionRecord,
    AnnotationResourceRecord,
    AnnotationResultVersionRecord,
    AnnotationRunRecord,
    AnnotationValidationFinding,
    ProfileResourceBinding,
)
from app.domain.value_objects.enums import (
    AnnotationResourceCategory,
    AnnotationResultState,
    AnnotationRunState,
    AnnotationValueType,
    QueryDefinitionState,
    ScientificResourceKind,
    ScientificResourceState,
    ValidationSeverity,
    ValueSemantics,
)
from app.infrastructure.persistence.models.annotation_registry import (
    AnnotationProfile,
    AnnotationProfileVersion,
    AnnotationResourceProfileField,
    AnnotationResultVersion,
    AnnotationRun,
    AnnotationValidationFindingRow,
)
from app.infrastructure.persistence.models.scientific import ScientificResource
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_RESOURCES = ScientificResource.__table__
_FIELDS = AnnotationResourceProfileField.__table__
_PROFILES = AnnotationProfile.__table__
_PROFILE_VERSIONS = AnnotationProfileVersion.__table__
_RUNS = AnnotationRun.__table__
_RESULTS = AnnotationResultVersion.__table__
_FINDINGS = AnnotationValidationFindingRow.__table__

#: Annotation-specific attributes that have no dedicated column on the shared
#: resource table. Kept in the resource's metadata rather than by widening the
#: shared registry, which every other resource kind would then have to carry.
_METADATA_KEYS = (
    "category",
    "provider",
    "genome_assembly",
    "reference_genome_resource_id",
    "release_label",
    "released_at",
    "schema_version",
)


def _field_spec(row: Mapping[str, Any]) -> AnnotationFieldSpec:
    raw_missing = row["missing_semantics"] or []
    raw_allowed = row["allowed_values"]
    return AnnotationFieldSpec(
        field_key=row["field_key"],
        label=row["label"],
        value_type=AnnotationValueType(row["value_type"]),
        description=row["description"],
        missing_semantics=tuple(ValueSemantics(item) for item in raw_missing),
        allowed_values=tuple(raw_allowed) if raw_allowed else None,
        unit=row["unit"],
        high_cardinality=bool(row["high_cardinality"]),
        filterable=bool(row["filterable"]),
        sortable=bool(row["sortable"]),
        scientific_category=row["scientific_category"],
        column=row["column_name"],
        metadata=dict(row["metadata_json"] or {}),
    )


def _field_values(resource_id: str, specification: AnnotationFieldSpec) -> dict[str, Any]:
    return {
        "id": new_id("anfd"),
        "scientific_resource_id": resource_id,
        "field_key": specification.field_key,
        "label": specification.label,
        "value_type": specification.value_type.value,
        "description": specification.description,
        "column_name": specification.column,
        "unit": specification.unit,
        "scientific_category": specification.scientific_category,
        "missing_semantics": [item.value for item in specification.missing_semantics],
        "allowed_values": list(specification.allowed_values)
        if specification.allowed_values
        else None,
        "high_cardinality": specification.high_cardinality,
        "filterable": specification.filterable,
        "sortable": specification.sortable,
        "metadata_json": specification.metadata or None,
    }


class SqlAnnotationResourceRepository(SqlRepository):
    """Annotation resource versions, stored in the scientific resource registry."""

    async def add(self, resource: AnnotationResourceRecord) -> AnnotationResourceRecord:
        metadata = dict(resource.metadata)
        metadata.update(
            {
                "category": resource.category.value,
                "provider": resource.provider,
                "genome_assembly": resource.genome_assembly,
                "reference_genome_resource_id": resource.reference_genome_resource_id,
                "release_label": resource.release_label,
                "released_at": resource.released_at.isoformat()
                if resource.released_at
                else None,
                "schema_version": resource.schema_version,
            }
        )
        await self._session.execute(
            insert(_RESOURCES).values(
                id=resource.id,
                kind=ScientificResourceKind.ANNOTATION_RESOURCE.value,
                resource_key=resource.resource_key,
                version=resource.version,
                display_name=resource.display_name,
                description=resource.description,
                state=resource.state.value,
                activated_at=resource.activated_at,
                deprecated_at=resource.deprecated_at,
                retired_at=resource.retired_at,
                invalidated_at=resource.invalidated_at,
                invalidation_reason=resource.invalidation_reason,
                checksum_algorithm=resource.checksum_algorithm,
                checksum_value=resource.checksum_value,
                size_bytes=resource.size_bytes,
                provenance=resource.provenance or None,
                licensing=resource.licensing or None,
                metadata_json=metadata,
                registered_by=resource.registered_by,
            )
        )
        if resource.fields:
            await self._session.execute(
                insert(_FIELDS),
                [
                    _field_values(resource.id, specification)
                    for specification in resource.fields
                ],
            )
        return resource

    async def get(self, resource_id: str) -> AnnotationResourceRecord | None:
        row = await self._fetch_one(
            select(_RESOURCES).where(
                _RESOURCES.c.id == resource_id,
                _RESOURCES.c.kind == ScientificResourceKind.ANNOTATION_RESOURCE.value,
            )
        )
        return await self._hydrate(row) if row else None

    async def get_by_version(
        self, *, resource_key: str, version: str
    ) -> AnnotationResourceRecord | None:
        row = await self._fetch_one(
            select(_RESOURCES).where(
                _RESOURCES.c.kind == ScientificResourceKind.ANNOTATION_RESOURCE.value,
                _RESOURCES.c.resource_key == resource_key,
                _RESOURCES.c.version == version,
            )
        )
        return await self._hydrate(row) if row else None

    async def save(self, resource: AnnotationResourceRecord) -> AnnotationResourceRecord:
        """Persist lifecycle state only.

        Content — key, version, checksum, declared fields — is immutable once
        registered: a corrected resource is a new version, so a run's identity
        never changes underneath it. The shared resource table carries no
        optimistic-concurrency counter (its ``version`` column is the *resource*
        version), so the guard here is the state itself: the update only applies
        while the row still holds a different state, and the domain has already
        refused any illegal transition.
        """
        result = await self._session.execute(
            update(_RESOURCES)
            .where(_RESOURCES.c.id == resource.id, _RESOURCES.c.state != resource.state.value)
            .values(
                state=resource.state.value,
                activated_at=resource.activated_at,
                deprecated_at=resource.deprecated_at,
                retired_at=resource.retired_at,
                invalidated_at=resource.invalidated_at,
                invalidation_reason=resource.invalidation_reason,
            )
        )
        if result.rowcount == 0:
            existing = await self._fetch_one(
                select(_RESOURCES.c.id).where(_RESOURCES.c.id == resource.id)
            )
            if existing is None:
                raise NotFoundError("annotation resource", resource.id)
        return resource

    async def list_resources(
        self,
        *,
        page: Page,
        category: AnnotationResourceCategory | None = None,
        resource_key: str | None = None,
        usable_only: bool = False,
    ) -> Paged[AnnotationResourceRecord]:
        statement: Select = select(_RESOURCES).where(
            _RESOURCES.c.kind == ScientificResourceKind.ANNOTATION_RESOURCE.value
        )
        if category is not None:
            statement = statement.where(
                _RESOURCES.c.metadata_json["category"].astext == category.value
            )
        if resource_key is not None:
            statement = statement.where(_RESOURCES.c.resource_key == resource_key)
        if usable_only:
            statement = statement.where(
                _RESOURCES.c.state.in_(
                    (
                        ScientificResourceState.ACTIVE.value,
                        ScientificResourceState.DEPRECATED.value,
                    )
                )
            )
        statement = statement.order_by(
            _RESOURCES.c.resource_key.asc(), _RESOURCES.c.version.desc()
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        items = tuple([await self._hydrate(row) for row in rows])
        return Paged(items=items, total=total, page=page)

    async def list_field_sources(self) -> tuple[AnnotationResourceRecord, ...]:
        statement: Select = (
            select(_RESOURCES)
            .where(
                _RESOURCES.c.kind == ScientificResourceKind.ANNOTATION_RESOURCE.value,
                _RESOURCES.c.state.in_(
                    (
                        ScientificResourceState.ACTIVE.value,
                        ScientificResourceState.DEPRECATED.value,
                    )
                ),
            )
            .order_by(_RESOURCES.c.resource_key.asc(), _RESOURCES.c.version.asc())
        )
        rows = await self._fetch_all(statement)
        return tuple([await self._hydrate(row) for row in rows])

    async def _hydrate(self, row: Mapping[str, Any]) -> AnnotationResourceRecord:
        field_rows = await self._fetch_all(
            select(_FIELDS)
            .where(_FIELDS.c.scientific_resource_id == row["id"])
            .order_by(_FIELDS.c.field_key.asc())
        )
        metadata = dict(row["metadata_json"] or {})
        released = metadata.get("released_at")
        extra = {key: value for key, value in metadata.items() if key not in _METADATA_KEYS}
        from datetime import datetime

        return AnnotationResourceRecord(
            id=row["id"],
            resource_key=row["resource_key"],
            version=row["version"],
            display_name=row["display_name"],
            category=AnnotationResourceCategory(
                metadata.get("category") or AnnotationResourceCategory.OTHER.value
            ),
            state=ScientificResourceState(row["state"]),
            provider=metadata.get("provider"),
            description=row["description"],
            genome_assembly=metadata.get("genome_assembly"),
            reference_genome_resource_id=metadata.get("reference_genome_resource_id"),
            release_label=metadata.get("release_label"),
            released_at=datetime.fromisoformat(released) if released else None,
            schema_version=metadata.get("schema_version"),
            checksum_algorithm=row["checksum_algorithm"],
            checksum_value=row["checksum_value"],
            size_bytes=row["size_bytes"],
            fields=tuple(_field_spec(item) for item in field_rows),
            provenance=dict(row["provenance"] or {}),
            licensing=dict(row["licensing"] or {}),
            metadata=extra,
            registered_by=row["registered_by"],
            activated_at=row["activated_at"],
            deprecated_at=row["deprecated_at"],
            retired_at=row["retired_at"],
            invalidated_at=row["invalidated_at"],
            invalidation_reason=row["invalidation_reason"],
            created_at=row["created_at"],
            # The shared resource table has no concurrency counter; lifecycle
            # transitions are guarded by the state instead.
            record_version=1,
        )


def _to_profile(row: Mapping[str, Any]) -> AnnotationProfileRecord:
    return AnnotationProfileRecord(
        id=row["id"],
        name=row["name"],
        state=QueryDefinitionState(row["state"]),
        description=row["description"],
        latest_version_number=row["latest_version_number"],
        is_referenced=bool(row["is_referenced"]),
        metadata=dict(row["metadata_json"] or {}),
        created_by=row["created_by"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        record_version=row["version"],
    )


def _to_profile_version(row: Mapping[str, Any]) -> AnnotationProfileVersionRecord:
    return AnnotationProfileVersionRecord(
        id=row["id"],
        profile_id=row["profile_id"],
        version_number=row["version_number"],
        capability_id=row["capability_id"],
        resources=tuple(
            ProfileResourceBinding(
                resource_id=item["resource_id"],
                resource_key=item["resource_key"],
                resource_version=item["resource_version"],
                category=AnnotationResourceCategory(item["category"])
                if item.get("category")
                else None,
                role=item.get("role"),
            )
            for item in (row["resources"] or [])
        ),
        configuration_digest=row["configuration_digest"],
        capability_version=row["capability_version"],
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        genome_assembly=row["genome_assembly"],
        reference_genome_resource_id=row["reference_genome_resource_id"],
        required_inputs=tuple(row["required_inputs"] or ()),
        output_field_keys=tuple(row["output_field_keys"] or ()),
        parameters=dict(row["parameters"] or {}),
        provenance_requirements=tuple(row["provenance_requirements"] or ()),
        schema_version=row["schema_version"],
        change_note=row["change_note"],
        is_referenced=bool(row["is_referenced"]),
        metadata=dict(row["metadata_json"] or {}),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


class SqlAnnotationProfileRepository(SqlRepository):
    """Annotation profiles and their append-only versions."""

    async def add(self, profile: AnnotationProfileRecord) -> AnnotationProfileRecord:
        await self._session.execute(
            insert(_PROFILES).values(
                id=profile.id,
                name=profile.name,
                description=profile.description,
                state=profile.state.value,
                latest_version_number=profile.latest_version_number,
                is_referenced=profile.is_referenced,
                metadata_json=profile.metadata or None,
                created_by=profile.created_by,
                updated_by=profile.updated_by,
            )
        )
        return profile

    async def get(self, profile_id: str) -> AnnotationProfileRecord | None:
        row = await self._fetch_one(select(_PROFILES).where(_PROFILES.c.id == profile_id))
        return _to_profile(row) if row else None

    async def get_by_name(self, name: str) -> AnnotationProfileRecord | None:
        row = await self._fetch_one(select(_PROFILES).where(_PROFILES.c.name == name))
        return _to_profile(row) if row else None

    async def save(self, profile: AnnotationProfileRecord) -> AnnotationProfileRecord:
        next_version = await self._versioned_update(
            _PROFILES,
            entity_id=profile.id,
            expected_version=profile.record_version,
            values={
                "name": profile.name,
                "description": profile.description,
                "state": profile.state.value,
                "latest_version_number": profile.latest_version_number,
                "is_referenced": profile.is_referenced,
                "metadata_json": profile.metadata or None,
                "updated_by": profile.updated_by,
            },
        )
        from dataclasses import replace

        return replace(profile, record_version=next_version)

    async def list_profiles(
        self, *, page: Page, offered_only: bool = False
    ) -> Paged[AnnotationProfileRecord]:
        statement: Select = select(_PROFILES)
        if offered_only:
            statement = statement.where(
                _PROFILES.c.state == QueryDefinitionState.PUBLISHED.value
            )
        statement = statement.order_by(_PROFILES.c.name.asc(), _PROFILES.c.id.asc())
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(
            items=tuple(_to_profile(row) for row in rows), total=total, page=page
        )

    async def add_version(
        self, version: AnnotationProfileVersionRecord
    ) -> AnnotationProfileVersionRecord:
        await self._session.execute(
            insert(_PROFILE_VERSIONS).values(
                id=version.id,
                profile_id=version.profile_id,
                version_number=version.version_number,
                capability_id=version.capability_id,
                capability_version=version.capability_version,
                engine_resource_id=version.engine_resource_id,
                engine_version=version.engine_version,
                genome_assembly=version.genome_assembly,
                reference_genome_resource_id=version.reference_genome_resource_id,
                resources=[
                    {
                        "resource_id": binding.resource_id,
                        "resource_key": binding.resource_key,
                        "resource_version": binding.resource_version,
                        "category": binding.category.value if binding.category else None,
                        "role": binding.role,
                    }
                    for binding in version.resources
                ],
                required_inputs=list(version.required_inputs),
                output_field_keys=list(version.output_field_keys),
                parameters=version.parameters or None,
                provenance_requirements=list(version.provenance_requirements),
                configuration_digest=version.configuration_digest,
                schema_version=version.schema_version,
                change_note=version.change_note,
                is_referenced=version.is_referenced,
                metadata_json=version.metadata or None,
                created_by=version.created_by,
            )
        )
        return version

    async def get_version(
        self, version_id: str
    ) -> AnnotationProfileVersionRecord | None:
        row = await self._fetch_one(
            select(_PROFILE_VERSIONS).where(_PROFILE_VERSIONS.c.id == version_id)
        )
        return _to_profile_version(row) if row else None

    async def get_version_number(
        self, *, profile_id: str, version_number: int
    ) -> AnnotationProfileVersionRecord | None:
        row = await self._fetch_one(
            select(_PROFILE_VERSIONS).where(
                _PROFILE_VERSIONS.c.profile_id == profile_id,
                _PROFILE_VERSIONS.c.version_number == version_number,
            )
        )
        return _to_profile_version(row) if row else None

    async def mark_version_referenced(self, version_id: str) -> None:
        """Record that a run used this version. Content stays untouched."""
        await self._session.execute(
            update(_PROFILE_VERSIONS)
            .where(_PROFILE_VERSIONS.c.id == version_id)
            .values(is_referenced=True)
        )
        row = await self._fetch_one(
            select(_PROFILE_VERSIONS.c.profile_id).where(
                _PROFILE_VERSIONS.c.id == version_id
            )
        )
        if row is not None:
            await self._session.execute(
                update(_PROFILES)
                .where(_PROFILES.c.id == row["profile_id"])
                .values(is_referenced=True)
            )

    async def list_versions(
        self, *, profile_id: str, page: Page
    ) -> Paged[AnnotationProfileVersionRecord]:
        statement: Select = (
            select(_PROFILE_VERSIONS)
            .where(_PROFILE_VERSIONS.c.profile_id == profile_id)
            .order_by(_PROFILE_VERSIONS.c.version_number.desc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(
            items=tuple(_to_profile_version(row) for row in rows), total=total, page=page
        )


def _to_run(row: Mapping[str, Any]) -> AnnotationRunRecord:
    return AnnotationRunRecord(
        id=row["id"],
        workspace_id=row["workspace_id"],
        profile_id=row["profile_id"],
        profile_version_id=row["profile_version_id"],
        profile_version_number=row["profile_version_number"],
        state=AnnotationRunState(row["state"]),
        project_id=row["project_id"],
        result_set_id=row["result_set_id"],
        dataset_version_id=row["dataset_version_id"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
        submitted_at=row["submitted_at"],
        completed_at=row["completed_at"],
        job_id=row["job_id"],
        scientific_execution_id=row["scientific_execution_id"],
        external_execution_id=row["external_execution_id"],
        capability_id=row["capability_id"],
        capability_version=row["capability_version"],
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        environment_version=row["environment_version"],
        container_image_digest=row["container_image_digest"],
        node_identity=row["node_identity"],
        genome_assembly=row["genome_assembly"],
        configuration_snapshot=dict(row["configuration_snapshot"] or {}),
        configuration_digest=row["configuration_digest"],
        correlation_id=row["correlation_id"],
        idempotency_key=row["idempotency_key"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        record_count=row["record_count"],
        metadata=dict(row["metadata_json"] or {}),
        created_at=row["created_at"],
        record_version=row["version"],
    )


class SqlAnnotationRunRepository(SqlRepository):
    async def add(self, run: AnnotationRunRecord) -> AnnotationRunRecord:
        await self._session.execute(
            insert(_RUNS).values(
                id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                profile_id=run.profile_id,
                profile_version_id=run.profile_version_id,
                profile_version_number=run.profile_version_number,
                result_set_id=run.result_set_id,
                dataset_version_id=run.dataset_version_id,
                state=run.state.value,
                requested_by=run.requested_by,
                requested_at=run.requested_at,
                capability_id=run.capability_id,
                capability_version=run.capability_version,
                engine_resource_id=run.engine_resource_id,
                engine_version=run.engine_version,
                genome_assembly=run.genome_assembly,
                configuration_snapshot=run.configuration_snapshot or None,
                configuration_digest=run.configuration_digest,
                correlation_id=run.correlation_id,
                idempotency_key=run.idempotency_key,
                job_id=run.job_id,
                metadata_json=run.metadata or None,
            )
        )
        return run

    async def get(self, run_id: str) -> AnnotationRunRecord | None:
        row = await self._fetch_one(select(_RUNS).where(_RUNS.c.id == run_id))
        return _to_run(row) if row else None

    async def save(self, run: AnnotationRunRecord) -> AnnotationRunRecord:
        next_version = await self._versioned_update(
            _RUNS,
            entity_id=run.id,
            expected_version=run.record_version,
            values={
                "state": run.state.value,
                "submitted_at": run.submitted_at,
                "completed_at": run.completed_at,
                "job_id": run.job_id,
                "scientific_execution_id": run.scientific_execution_id,
                "external_execution_id": run.external_execution_id,
                "engine_resource_id": run.engine_resource_id,
                "engine_version": run.engine_version,
                "environment_version": run.environment_version,
                "container_image_digest": run.container_image_digest,
                "node_identity": run.node_identity,
                "failure_code": run.failure_code,
                "failure_message": run.failure_message,
                "record_count": run.record_count,
                "metadata_json": run.metadata or None,
            },
        )
        from dataclasses import replace

        return replace(run, record_version=next_version)

    async def get_by_idempotency_key(
        self, *, workspace_id: str, idempotency_key: str
    ) -> AnnotationRunRecord | None:
        row = await self._fetch_one(
            select(_RUNS).where(
                _RUNS.c.workspace_id == workspace_id,
                _RUNS.c.idempotency_key == idempotency_key,
            )
        )
        return _to_run(row) if row else None

    async def list_runs(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        project_id: str | None = None,
        result_set_id: str | None = None,
        state: AnnotationRunState | None = None,
    ) -> Paged[AnnotationRunRecord]:
        statement: Select = select(_RUNS)
        if workspace_ids is not None:
            # No code path lists runs across tenants for a tenant caller.
            statement = statement.where(_RUNS.c.workspace_id.in_(tuple(workspace_ids)))
        if project_id is not None:
            statement = statement.where(_RUNS.c.project_id == project_id)
        if result_set_id is not None:
            statement = statement.where(_RUNS.c.result_set_id == result_set_id)
        if state is not None:
            statement = statement.where(_RUNS.c.state == state.value)
        statement = statement.order_by(_RUNS.c.created_at.desc(), _RUNS.c.id.desc())
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_run(row) for row in rows), total=total, page=page)


def _to_result(row: Mapping[str, Any]) -> AnnotationResultVersionRecord:
    return AnnotationResultVersionRecord(
        id=row["id"],
        annotation_run_id=row["annotation_run_id"],
        workspace_id=row["workspace_id"],
        resource_id=row["resource_id"],
        resource_key=row["resource_key"],
        resource_version=row["resource_version"],
        version_number=row["version_number"],
        state=AnnotationResultState(row["state"]),
        project_id=row["project_id"],
        result_set_id=row["result_set_id"],
        dataset_version_id=row["dataset_version_id"],
        profile_version_id=row["profile_version_id"],
        scientific_execution_id=row["scientific_execution_id"],
        engine_resource_id=row["engine_resource_id"],
        engine_version=row["engine_version"],
        environment_version=row["environment_version"],
        container_image_digest=row["container_image_digest"],
        node_identity=row["node_identity"],
        genome_assembly=row["genome_assembly"],
        analytical_location=row["analytical_location"],
        storage_uri=row["storage_uri"],
        checksum_algorithm=row["checksum_algorithm"],
        checksum_value=row["checksum_value"],
        row_count=row["row_count"],
        stored_record_count=row["stored_record_count"],
        declared_record_count=row["declared_record_count"],
        rejected_record_count=row["rejected_record_count"],
        field_keys=tuple(row["field_keys"] or ()),
        contract_version=row["contract_version"],
        payload_digest=row["payload_digest"],
        parameters_digest=row["parameters_digest"],
        completeness=row["completeness"],
        is_development_payload=bool(row["is_development_payload"]),
        supersedes_id=row["supersedes_id"],
        superseded_by_id=row["superseded_by_id"],
        provenance=dict(row["provenance"] or {}),
        metadata=dict(row["metadata_json"] or {}),
        ingested_at=row["ingested_at"],
        created_at=row["created_at"],
        record_version=row["version"],
    )


def _to_finding(row: Mapping[str, Any]) -> AnnotationValidationFinding:
    return AnnotationValidationFinding(
        id=row["id"],
        annotation_run_id=row["annotation_run_id"],
        code=row["code"],
        message=row["message"],
        severity=ValidationSeverity(row["severity"]),
        annotation_result_version_id=row["annotation_result_version_id"],
        field_key=row["field_key"],
        variant_id=row["variant_id"],
        record_index=row["record_index"],
        detail=dict(row["detail"] or {}),
        created_at=row["created_at"],
    )


class SqlAnnotationResultRepository(SqlRepository):
    async def add(
        self, result: AnnotationResultVersionRecord
    ) -> AnnotationResultVersionRecord:
        await self._session.execute(
            insert(_RESULTS).values(
                id=result.id,
                annotation_run_id=result.annotation_run_id,
                workspace_id=result.workspace_id,
                project_id=result.project_id,
                resource_id=result.resource_id,
                resource_key=result.resource_key,
                resource_version=result.resource_version,
                version_number=result.version_number,
                state=result.state.value,
                result_set_id=result.result_set_id,
                dataset_version_id=result.dataset_version_id,
                profile_version_id=result.profile_version_id,
                scientific_execution_id=result.scientific_execution_id,
                engine_resource_id=result.engine_resource_id,
                engine_version=result.engine_version,
                environment_version=result.environment_version,
                container_image_digest=result.container_image_digest,
                node_identity=result.node_identity,
                genome_assembly=result.genome_assembly,
                analytical_location=result.analytical_location,
                storage_uri=result.storage_uri,
                checksum_algorithm=result.checksum_algorithm,
                checksum_value=result.checksum_value,
                row_count=result.row_count,
                stored_record_count=result.stored_record_count,
                declared_record_count=result.declared_record_count,
                rejected_record_count=result.rejected_record_count,
                field_keys=list(result.field_keys),
                contract_version=result.contract_version,
                payload_digest=result.payload_digest,
                parameters_digest=result.parameters_digest,
                completeness=result.completeness,
                is_development_payload=result.is_development_payload,
                supersedes_id=result.supersedes_id,
                provenance=result.provenance or None,
                metadata_json=result.metadata or None,
                ingested_at=result.ingested_at,
            )
        )
        return result

    async def get(self, result_id: str) -> AnnotationResultVersionRecord | None:
        row = await self._fetch_one(select(_RESULTS).where(_RESULTS.c.id == result_id))
        return _to_result(row) if row else None

    async def save(
        self, result: AnnotationResultVersionRecord
    ) -> AnnotationResultVersionRecord:
        """Only lifecycle and supersession pointers are mutable.

        Counts, checksums, locations and provenance are written once at ingestion:
        a historical annotation result is never rewritten.
        """
        next_version = await self._versioned_update(
            _RESULTS,
            entity_id=result.id,
            expected_version=result.record_version,
            values={
                "state": result.state.value,
                "superseded_by_id": result.superseded_by_id,
            },
        )
        from dataclasses import replace

        return replace(result, record_version=next_version)

    async def get_by_payload_digest(
        self, *, annotation_run_id: str, payload_digest: str
    ) -> AnnotationResultVersionRecord | None:
        row = await self._fetch_one(
            select(_RESULTS).where(
                _RESULTS.c.annotation_run_id == annotation_run_id,
                _RESULTS.c.payload_digest == payload_digest,
            )
        )
        return _to_result(row) if row else None

    def _surface_clause(
        self, statement: Select, *, result_set_id: str | None, dataset_version_id: str | None
    ) -> Select:
        if result_set_id is not None:
            return statement.where(_RESULTS.c.result_set_id == result_set_id)
        if dataset_version_id is not None:
            return statement.where(_RESULTS.c.dataset_version_id == dataset_version_id)
        return statement

    async def latest_version_number(
        self,
        *,
        resource_key: str,
        result_set_id: str | None = None,
        dataset_version_id: str | None = None,
    ) -> int:
        statement: Select = select(
            func.coalesce(func.max(_RESULTS.c.version_number), 0)
        ).where(_RESULTS.c.resource_key == resource_key)
        statement = self._surface_clause(
            statement, result_set_id=result_set_id, dataset_version_id=dataset_version_id
        )
        return int(await self._session.scalar(statement) or 0)

    async def latest_for_surface(
        self,
        *,
        resource_key: str,
        result_set_id: str | None = None,
        dataset_version_id: str | None = None,
    ) -> AnnotationResultVersionRecord | None:
        statement: Select = select(_RESULTS).where(_RESULTS.c.resource_key == resource_key)
        statement = self._surface_clause(
            statement, result_set_id=result_set_id, dataset_version_id=dataset_version_id
        )
        statement = statement.order_by(_RESULTS.c.version_number.desc()).limit(1)
        row = await self._fetch_one(statement)
        return _to_result(row) if row else None

    async def list_results(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        result_set_id: str | None = None,
        annotation_run_id: str | None = None,
    ) -> Paged[AnnotationResultVersionRecord]:
        statement: Select = select(_RESULTS)
        if workspace_ids is not None:
            statement = statement.where(
                _RESULTS.c.workspace_id.in_(tuple(workspace_ids))
            )
        if result_set_id is not None:
            statement = statement.where(_RESULTS.c.result_set_id == result_set_id)
        if annotation_run_id is not None:
            statement = statement.where(
                _RESULTS.c.annotation_run_id == annotation_run_id
            )
        statement = statement.order_by(
            _RESULTS.c.created_at.desc(), _RESULTS.c.id.desc()
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_result(row) for row in rows), total=total, page=page)

    async def add_findings(
        self, findings: tuple[AnnotationValidationFinding, ...]
    ) -> None:
        if not findings:
            return
        await self._session.execute(
            insert(_FINDINGS),
            [
                {
                    "id": finding.id,
                    "annotation_run_id": finding.annotation_run_id,
                    "annotation_result_version_id": finding.annotation_result_version_id,
                    "code": finding.code,
                    "message": finding.message,
                    "severity": finding.severity.value,
                    "field_key": finding.field_key,
                    "variant_id": finding.variant_id,
                    "record_index": finding.record_index,
                    "detail": finding.detail or None,
                }
                for finding in findings
            ],
        )

    async def list_findings(
        self, *, annotation_run_id: str, page: Page
    ) -> Paged[AnnotationValidationFinding]:
        statement: Select = (
            select(_FINDINGS)
            .where(_FINDINGS.c.annotation_run_id == annotation_run_id)
            .order_by(_FINDINGS.c.created_at.asc(), _FINDINGS.c.id.asc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(items=tuple(_to_finding(row) for row in rows), total=total, page=page)


__all__ = [
    "SqlAnnotationProfileRepository",
    "SqlAnnotationResourceRepository",
    "SqlAnnotationResultRepository",
    "SqlAnnotationRunRepository",
]
