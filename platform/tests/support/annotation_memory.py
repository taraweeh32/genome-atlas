"""In-memory doubles for the annotation repositories.

They mirror the SQL repositories' *semantics*, which for this package means:

* a resource version is identified by ``(resource_key, version)`` and its content
  is never rewritten — only lifecycle state moves;
* profile versions are append-only, and the only mutation is flipping
  ``is_referenced``;
* result versions increment per annotated surface and resource key, so an updated
  resource adds a version rather than overwriting one;
* listings are tenant-filtered exactly as the SQL clause is, so a test that leaks
  across workspaces in memory would leak in PostgreSQL too.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from app.application.repositories import Page, Paged
from app.domain.annotation.entities import (
    AnnotationProfileRecord,
    AnnotationProfileVersionRecord,
    AnnotationResourceRecord,
    AnnotationResultVersionRecord,
    AnnotationRunRecord,
    AnnotationValidationFinding,
)
from app.domain.errors import ConcurrencyConflictError, ConflictError
from app.domain.value_objects.enums import (
    AnnotationResourceCategory,
    AnnotationRunState,
    QueryDefinitionState,
)


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


def _bump(entity, expected: int):
    if entity.record_version != expected:
        raise ConcurrencyConflictError(
            f"{type(entity).__name__} {entity.id} was modified concurrently"
        )
    return replace(entity, record_version=expected + 1)


@dataclass
class MemoryAnnotationResources:
    items: dict[str, AnnotationResourceRecord] = field(default_factory=dict)

    async def add(self, resource: AnnotationResourceRecord) -> AnnotationResourceRecord:
        for existing in self.items.values():
            if (
                existing.resource_key == resource.resource_key
                and existing.version == resource.version
            ):
                raise ConflictError("this annotation resource version already exists")
        self.items[resource.id] = resource
        return resource

    async def get(self, resource_id: str) -> AnnotationResourceRecord | None:
        return self.items.get(resource_id)

    async def get_by_version(
        self, *, resource_key: str, version: str
    ) -> AnnotationResourceRecord | None:
        for resource in self.items.values():
            if resource.resource_key == resource_key and resource.version == version:
                return resource
        return None

    async def save(self, resource: AnnotationResourceRecord) -> AnnotationResourceRecord:
        current = self.items[resource.id]
        # Content is immutable; only the lifecycle fields are carried over.
        self.items[resource.id] = replace(
            current,
            state=resource.state,
            activated_at=resource.activated_at,
            deprecated_at=resource.deprecated_at,
            retired_at=resource.retired_at,
            invalidated_at=resource.invalidated_at,
            invalidation_reason=resource.invalidation_reason,
        )
        return self.items[resource.id]

    async def list_resources(
        self,
        *,
        page: Page,
        category: AnnotationResourceCategory | None = None,
        resource_key: str | None = None,
        usable_only: bool = False,
    ) -> Paged[AnnotationResourceRecord]:
        items = [
            resource
            for resource in self.items.values()
            if (category is None or resource.category is category)
            and (resource_key is None or resource.resource_key == resource_key)
            and (not usable_only or resource.is_usable)
        ]
        items.sort(key=lambda resource: (resource.resource_key, resource.version))
        return _paged(items, page)

    async def list_field_sources(self) -> tuple[AnnotationResourceRecord, ...]:
        return tuple(
            sorted(
                (resource for resource in self.items.values() if resource.is_usable),
                key=lambda resource: (resource.resource_key, resource.version),
            )
        )


@dataclass
class MemoryAnnotationProfiles:
    items: dict[str, AnnotationProfileRecord] = field(default_factory=dict)
    versions: dict[str, AnnotationProfileVersionRecord] = field(default_factory=dict)

    async def add(self, profile: AnnotationProfileRecord) -> AnnotationProfileRecord:
        if any(existing.name == profile.name for existing in self.items.values()):
            raise ConflictError("an annotation profile with this name already exists")
        self.items[profile.id] = profile
        return profile

    async def get(self, profile_id: str) -> AnnotationProfileRecord | None:
        return self.items.get(profile_id)

    async def get_by_name(self, name: str) -> AnnotationProfileRecord | None:
        for profile in self.items.values():
            if profile.name == name:
                return profile
        return None

    async def save(self, profile: AnnotationProfileRecord) -> AnnotationProfileRecord:
        current = self.items[profile.id]
        updated = _bump(profile, current.record_version)
        self.items[profile.id] = updated
        return updated

    async def list_profiles(
        self, *, page: Page, offered_only: bool = False
    ) -> Paged[AnnotationProfileRecord]:
        items = [
            profile
            for profile in self.items.values()
            if not offered_only or profile.state is QueryDefinitionState.PUBLISHED
        ]
        items.sort(key=lambda profile: profile.name)
        return _paged(items, page)

    async def add_version(
        self, version: AnnotationProfileVersionRecord
    ) -> AnnotationProfileVersionRecord:
        for existing in self.versions.values():
            if (
                existing.profile_id == version.profile_id
                and existing.version_number == version.version_number
            ):
                raise ConflictError("this profile version already exists")
        self.versions[version.id] = version
        return version

    async def get_version(
        self, version_id: str
    ) -> AnnotationProfileVersionRecord | None:
        return self.versions.get(version_id)

    async def get_version_number(
        self, *, profile_id: str, version_number: int
    ) -> AnnotationProfileVersionRecord | None:
        for version in self.versions.values():
            if (
                version.profile_id == profile_id
                and version.version_number == version_number
            ):
                return version
        return None

    async def mark_version_referenced(self, version_id: str) -> None:
        version = self.versions[version_id]
        self.versions[version_id] = version.referenced()
        profile = self.items.get(version.profile_id)
        if profile is not None:
            self.items[profile.id] = replace(profile, is_referenced=True)

    async def list_versions(
        self, *, profile_id: str, page: Page
    ) -> Paged[AnnotationProfileVersionRecord]:
        items = [
            version
            for version in self.versions.values()
            if version.profile_id == profile_id
        ]
        items.sort(key=lambda version: version.version_number, reverse=True)
        return _paged(items, page)


@dataclass
class MemoryAnnotationRuns:
    items: dict[str, AnnotationRunRecord] = field(default_factory=dict)

    async def add(self, run: AnnotationRunRecord) -> AnnotationRunRecord:
        self.items[run.id] = run
        return run

    async def get(self, run_id: str) -> AnnotationRunRecord | None:
        return self.items.get(run_id)

    async def save(self, run: AnnotationRunRecord) -> AnnotationRunRecord:
        current = self.items[run.id]
        updated = _bump(run, current.record_version)
        self.items[run.id] = updated
        return updated

    async def get_by_idempotency_key(
        self, *, workspace_id: str, idempotency_key: str
    ) -> AnnotationRunRecord | None:
        for run in self.items.values():
            if (
                run.workspace_id == workspace_id
                and run.idempotency_key == idempotency_key
            ):
                return run
        return None

    async def list_runs(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        project_id: str | None = None,
        result_set_id: str | None = None,
        state: AnnotationRunState | None = None,
    ) -> Paged[AnnotationRunRecord]:
        items = [
            run
            for run in self.items.values()
            if (workspace_ids is None or run.workspace_id in workspace_ids)
            and (project_id is None or run.project_id == project_id)
            and (result_set_id is None or run.result_set_id == result_set_id)
            and (state is None or run.state is state)
        ]
        items.sort(key=lambda run: run.id, reverse=True)
        return _paged(items, page)


@dataclass
class MemoryAnnotationResults:
    items: dict[str, AnnotationResultVersionRecord] = field(default_factory=dict)
    findings: list[AnnotationValidationFinding] = field(default_factory=list)

    async def add(
        self, result: AnnotationResultVersionRecord
    ) -> AnnotationResultVersionRecord:
        self.items[result.id] = result
        return result

    async def get(self, result_id: str) -> AnnotationResultVersionRecord | None:
        return self.items.get(result_id)

    async def save(
        self, result: AnnotationResultVersionRecord
    ) -> AnnotationResultVersionRecord:
        current = self.items[result.id]
        # Only lifecycle and supersession move; content stays as ingested.
        updated = replace(
            current,
            state=result.state,
            superseded_by_id=result.superseded_by_id,
            record_version=current.record_version + 1,
        )
        self.items[result.id] = updated
        return updated

    async def get_by_payload_digest(
        self, *, annotation_run_id: str, payload_digest: str
    ) -> AnnotationResultVersionRecord | None:
        for result in self.items.values():
            if (
                result.annotation_run_id == annotation_run_id
                and result.payload_digest == payload_digest
            ):
                return result
        return None

    def _surface(
        self,
        result: AnnotationResultVersionRecord,
        *,
        result_set_id: str | None,
        dataset_version_id: str | None,
    ) -> bool:
        if result_set_id is not None:
            return result.result_set_id == result_set_id
        if dataset_version_id is not None:
            return result.dataset_version_id == dataset_version_id
        return True

    async def latest_version_number(
        self,
        *,
        resource_key: str,
        result_set_id: str | None = None,
        dataset_version_id: str | None = None,
    ) -> int:
        numbers = [
            result.version_number
            for result in self.items.values()
            if result.resource_key == resource_key
            and self._surface(
                result,
                result_set_id=result_set_id,
                dataset_version_id=dataset_version_id,
            )
        ]
        return max(numbers, default=0)

    async def latest_for_surface(
        self,
        *,
        resource_key: str,
        result_set_id: str | None = None,
        dataset_version_id: str | None = None,
    ) -> AnnotationResultVersionRecord | None:
        candidates = [
            result
            for result in self.items.values()
            if result.resource_key == resource_key
            and self._surface(
                result,
                result_set_id=result_set_id,
                dataset_version_id=dataset_version_id,
            )
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda result: result.version_number)

    async def list_results(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        result_set_id: str | None = None,
        annotation_run_id: str | None = None,
    ) -> Paged[AnnotationResultVersionRecord]:
        items = [
            result
            for result in self.items.values()
            if (workspace_ids is None or result.workspace_id in workspace_ids)
            and (result_set_id is None or result.result_set_id == result_set_id)
            and (
                annotation_run_id is None
                or result.annotation_run_id == annotation_run_id
            )
        ]
        items.sort(key=lambda result: (result.resource_key, result.version_number))
        return _paged(items, page)

    async def add_findings(
        self, findings: tuple[AnnotationValidationFinding, ...]
    ) -> None:
        self.findings.extend(findings)

    async def list_findings(
        self, *, annotation_run_id: str, page: Page
    ) -> Paged[AnnotationValidationFinding]:
        items = [
            finding
            for finding in self.findings
            if finding.annotation_run_id == annotation_run_id
        ]
        return _paged(items, page)


__all__ = [
    "MemoryAnnotationProfiles",
    "MemoryAnnotationResources",
    "MemoryAnnotationResults",
    "MemoryAnnotationRuns",
]
