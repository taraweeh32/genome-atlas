"""Managing saved filters, filter presets, saved rankings and ranking presets.

All four are governed by one implementation because they are governed by one set
of rules — and by four separate bindings because holding a filter permission must
never confer a ranking permission.

Two invariants are enforced here rather than left to callers:

* **Metadata is mutable, content is not.** Renaming, publishing or archiving edits
  the definition row under an optimistic-concurrency check. Changing a single
  condition or weight appends the next version and leaves every earlier version
  byte-identical, so an analysis that referenced version 3 keeps resolving to
  version 3 after ten further edits.
* **Content is validated before it is stored.** A definition that could not be
  executed is never persisted, so "saved" cannot mean "saved but broken". A filter
  is validated against the field dictionary; a ranking against the method registry
  *and* the field dictionary, because a ranking may only consume fields the
  platform already records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.query.dependencies import (
    FILTER_PRESET,
    RANKING_PRESET,
    SAVED_FILTER,
    SAVED_RANKING,
    ConfigurationKind,
    QueryServices,
    authorized_scopes,
    configuration_capabilities,
    require_configuration_access,
    require_creation_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.query.entities import (
    FilterDefinitionRecord,
    FilterPresetRecord,
    FilterPresetVersionRecord,
    FilterVersionRecord,
    RankingDefinitionRecord,
    RankingPresetRecord,
    RankingPresetVersionRecord,
    RankingVersionRecord,
)
from app.domain.query.expressions import group_from_payload
from app.domain.query.ranking import spec_from_payload, validate_ranking
from app.domain.query.validation import validate_filter
from app.domain.value_objects.enums import AuditOutcome, QueryDefinitionState, QueryScope
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class ValidatedContent:
    """Validated, canonical content plus the kind-specific columns it implies."""

    canonical: dict[str, Any]
    canonical_hash: str
    field_dictionary_version: str
    required_field_ids: tuple[str, ...]
    extra: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ConfigurationView:
    """A definition with its resolved latest version and server-granted actions."""

    definition: Any
    latest_version: Any | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CreateConfigurationCommand:
    actor: ActorContext
    request: RequestContext
    name: str
    scope: QueryScope
    content: dict[str, Any]
    description: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    organization_id: str | None = None
    applicable_contexts: tuple[str, ...] = ("result_set",)
    method_id: str | None = None
    change_note: str | None = None
    #: Publish immediately. A draft is offered to nobody, so a caller creating a
    #: preset for use normally publishes in the same step.
    publish: bool = True
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class UpdateMetadataCommand:
    actor: ActorContext
    request: RequestContext
    definition_id: str
    expected_version: int
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class AddVersionCommand:
    actor: ActorContext
    request: RequestContext
    definition_id: str
    expected_version: int
    content: dict[str, Any]
    change_note: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleCommand:
    actor: ActorContext
    request: RequestContext
    definition_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class ListConfigurationsQuery:
    actor: ActorContext
    request: RequestContext
    page: Page


@dataclass(frozen=True, slots=True)
class GetConfigurationQuery:
    actor: ActorContext
    request: RequestContext
    definition_id: str
    version_number: int | None = None


class ConfigurationService:
    """One governed lifecycle, bound to a specific configuration kind."""

    kind: ConfigurationKind
    repository: str
    id_prefix: str
    version_prefix: str
    record_type: Any
    version_type: Any
    #: True when the kind is a preset, which additionally carries applicable
    #: contexts and is offered rather than owned.
    is_preset: bool = False
    #: True when content is a ranking configuration rather than a filter
    #: expression, which changes only how content is validated.
    is_ranking: bool = False

    def __init__(self, services: QueryServices) -> None:
        self._services = services

    # -- content validation ------------------------------------------------ #

    def validate_content(self, content: dict[str, Any]) -> ValidatedContent:
        if self.is_ranking:
            spec = spec_from_payload(content)
            validated = validate_ranking(
                spec,
                methods=self._services.methods,
                registry=self._services.fields,
            )
            return ValidatedContent(
                canonical=validated.canonical,
                canonical_hash=validated.canonical_hash,
                field_dictionary_version=validated.field_dictionary_version,
                required_field_ids=validated.field_ids,
                extra={
                    "method_id": validated.method.id,
                    "method_version": validated.method.version,
                    "component_count": len(validated.spec.components),
                },
            )
        expression = group_from_payload(content)
        validated = validate_filter(
            expression,
            registry=self._services.fields,
            limits=self._services.limits,
            # A saved filter with no conditions would be a filter that selects
            # everything while claiming to be a selection. Refused.
            allow_empty=False,
        )
        return ValidatedContent(
            canonical=validated.canonical,
            canonical_hash=validated.canonical_hash,
            field_dictionary_version=validated.field_dictionary_version,
            required_field_ids=validated.field_ids,
            extra={
                "condition_count": validated.condition_count,
                "depth": validated.depth,
            },
        )

    # -- construction ------------------------------------------------------ #

    def _new_definition(
        self, command: CreateConfigurationCommand, *, at: datetime, content: ValidatedContent
    ) -> Any:
        common: dict[str, Any] = {
            "id": new_id(self.id_prefix),
            "name": command.name,
            "scope": command.scope,
            "created_by": command.actor.actor_id,
            "at": at,
            "description": command.description,
            "owner_user_id": command.actor.actor_id,
            "workspace_id": command.workspace_id,
            "project_id": command.project_id,
            "organization_id": command.organization_id,
            "metadata": command.metadata,
        }
        if self.is_ranking:
            common["method_id"] = str(content.extra["method_id"])
        if self.is_preset:
            common["applicable_contexts"] = command.applicable_contexts
        return self.record_type.create(**common)

    def _new_version(
        self,
        definition: Any,
        *,
        number: int,
        content: ValidatedContent,
        actor_id: str,
        at: datetime,
        change_note: str | None,
    ) -> Any:
        return self.version_type(
            id=new_id(self.version_prefix),
            definition_id=definition.id,
            version_number=number,
            canonical=content.canonical,
            canonical_hash=content.canonical_hash,
            field_dictionary_version=content.field_dictionary_version,
            created_by=actor_id,
            created_at=at,
            required_field_ids=content.required_field_ids,
            change_note=change_note,
            **content.extra,
        )

    # -- operations -------------------------------------------------------- #

    async def create(self, command: CreateConfigurationCommand) -> ConfigurationView:
        now = self._services.clock.now()
        content = self.validate_content(command.content)
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            actor = await require_creation_scope(
                self._services,
                repositories,
                command.actor,
                kind=self.kind,
                scope=command.scope,
                workspace_id=command.workspace_id,
                project_id=command.project_id,
                organization_id=command.organization_id,
                recorder=recorder,
                occurred_at=now,
            )
            definition = self._new_definition(command, at=now, content=content)
            version = self._new_version(
                definition,
                number=1,
                content=content,
                actor_id=actor.actor_id,
                at=now,
                change_note=command.change_note,
            )
            definition = definition.with_new_version(number=1, at=now)
            if command.publish:
                definition = definition.publish(at=now)
            repository = getattr(repositories, self.repository)
            await repository.add(definition)
            await repository.add_version(version)
            await self._audit(
                recorder,
                definition,
                action=f"{self.kind.name}.created",
                at=now,
                actor_id=actor.actor_id,
                detail={
                    "scope": definition.scope.value,
                    "version_number": 1,
                    "canonical_hash": content.canonical_hash,
                    "field_dictionary_version": content.field_dictionary_version,
                },
            )
        return ConfigurationView(
            definition=definition,
            latest_version=version,
            capabilities=configuration_capabilities(actor, definition, kind=self.kind),
        )

    async def get(self, query: GetConfigurationQuery) -> ConfigurationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            repository = getattr(repositories, self.repository)
            definition = await repository.get(query.definition_id)
            if definition is None:
                raise NotFoundError(self.kind.name, query.definition_id)
            scope = await require_configuration_access(
                self._services,
                repositories,
                query.actor,
                definition,
                kind=self.kind,
                manage=False,
                recorder=recorder,
                occurred_at=now,
            )
            if query.version_number is None:
                version = await repository.latest_version(definition.id)
            else:
                version = await repository.find_version(
                    definition_id=definition.id, version_number=query.version_number
                )
                if version is None:
                    raise NotFoundError(
                        f"{self.kind.name}_version", str(query.version_number)
                    )
        return ConfigurationView(
            definition=definition,
            latest_version=version,
            capabilities=configuration_capabilities(
                scope.actor, definition, kind=self.kind
            ),
        )

    async def list_versions(self, query: GetConfigurationQuery) -> tuple[Any, ...]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            repository = getattr(repositories, self.repository)
            definition = await repository.get(query.definition_id)
            if definition is None:
                raise NotFoundError(self.kind.name, query.definition_id)
            await require_configuration_access(
                self._services,
                repositories,
                query.actor,
                definition,
                kind=self.kind,
                manage=False,
                recorder=recorder,
                occurred_at=now,
            )
            return await repository.list_versions(definition.id)

    async def list(self, query: ListConfigurationsQuery) -> Paged:
        async with self._services.unit_of_work.begin() as repositories:
            repository = getattr(repositories, self.repository)
            return await repository.list_for_scope(
                scopes=authorized_scopes(query.actor, kind=self.kind), page=query.page
            )

    async def update_metadata(self, command: UpdateMetadataCommand) -> ConfigurationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            repository = getattr(repositories, self.repository)
            definition = await self._for_write(
                repositories, repository, command, recorder=recorder, at=now
            )
            updated = definition.rename(
                name=command.name if command.name is not None else definition.name,
                description=(
                    command.description
                    if command.description is not None
                    else definition.description
                ),
                at=now,
            )
            updated = await repository.save(updated)
            version = await repository.latest_version(updated.id)
            await self._audit(
                recorder,
                updated,
                action=f"{self.kind.name}.metadata_updated",
                at=now,
                actor_id=command.actor.actor_id,
                detail={"name": updated.name},
            )
        return ConfigurationView(
            definition=updated,
            latest_version=version,
            capabilities=configuration_capabilities(
                command.actor, updated, kind=self.kind
            ),
        )

    async def add_version(self, command: AddVersionCommand) -> ConfigurationView:
        """Append the next content version. Nothing existing is rewritten."""
        now = self._services.clock.now()
        content = self.validate_content(command.content)
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            repository = getattr(repositories, self.repository)
            definition = await self._for_write(
                repositories, repository, command, recorder=recorder, at=now
            )
            latest = await repository.latest_version(definition.id)
            if latest is not None and latest.canonical_hash == content.canonical_hash:
                # Identical content is not a new version: issuing one would make the
                # history claim a change that did not happen.
                raise ConflictError(
                    "this content is identical to the current version",
                    details={"version_number": latest.version_number},
                )
            number = definition.latest_version_number + 1
            version = self._new_version(
                definition,
                number=number,
                content=content,
                actor_id=command.actor.actor_id,
                at=now,
                change_note=command.change_note,
            )
            updated = definition.with_new_version(number=number, at=now)
            if updated.state is QueryDefinitionState.DRAFT:
                updated = updated.publish(at=now)
            updated = await repository.save(updated)
            await repository.add_version(version)
            await self._audit(
                recorder,
                updated,
                action=f"{self.kind.name}.version_created",
                at=now,
                actor_id=command.actor.actor_id,
                detail={
                    "version_number": number,
                    "canonical_hash": content.canonical_hash,
                    "field_dictionary_version": content.field_dictionary_version,
                    "previous_version_number": latest.version_number if latest else None,
                },
            )
        return ConfigurationView(
            definition=updated,
            latest_version=version,
            capabilities=configuration_capabilities(
                command.actor, updated, kind=self.kind
            ),
        )

    async def publish(self, command: LifecycleCommand) -> ConfigurationView:
        return await self._transition(command, move="publish")

    async def archive(self, command: LifecycleCommand) -> ConfigurationView:
        return await self._transition(command, move="archive")

    async def restore(self, command: LifecycleCommand) -> ConfigurationView:
        return await self._transition(command, move="restore")

    async def soft_delete(self, command: LifecycleCommand) -> ConfigurationView:
        """Withdraw the definition without touching its version history.

        Historical executions keep resolving the versions they referenced: a
        deleted saved filter must not make a past result unexplainable.
        """
        return await self._transition(command, move="soft_delete")

    async def _transition(
        self, command: LifecycleCommand, *, move: str
    ) -> ConfigurationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            repository = getattr(repositories, self.repository)
            definition = await self._for_write(
                repositories, repository, command, recorder=recorder, at=now
            )
            previous = definition.state.value
            updated = getattr(definition, move)(at=now)
            updated = await repository.save(updated)
            version = await repository.latest_version(updated.id)
            await self._audit(
                recorder,
                updated,
                action=f"{self.kind.name}.{move}",
                at=now,
                actor_id=command.actor.actor_id,
                previous_state=previous,
                new_state=updated.state.value,
            )
        return ConfigurationView(
            definition=updated,
            latest_version=version,
            capabilities=configuration_capabilities(
                command.actor, updated, kind=self.kind
            ),
        )

    # -- helpers ----------------------------------------------------------- #

    async def _for_write(
        self,
        repositories: Any,
        repository: Any,
        command: Any,
        *,
        recorder: ActivityRecorder,
        at: datetime,
    ) -> Any:
        definition = await repository.get(command.definition_id)
        if definition is None:
            raise NotFoundError(self.kind.name, command.definition_id)
        await require_configuration_access(
            self._services,
            repositories,
            command.actor,
            definition,
            kind=self.kind,
            manage=True,
            recorder=recorder,
            occurred_at=at,
        )
        if definition.version != command.expected_version:
            # Reported before any change is attempted so the caller re-reads rather
            # than overwriting an edit they never saw.
            raise ConflictError(
                "this configuration was modified by someone else",
                details={
                    "expected_version": command.expected_version,
                    "current_version": definition.version,
                },
            )
        return definition

    async def _audit(
        self,
        recorder: ActivityRecorder,
        definition: Any,
        *,
        action: str,
        at: datetime,
        actor_id: str,
        previous_state: str | None = None,
        new_state: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await recorder.audit(
            action=action,
            outcome=AuditOutcome.SUCCESS,
            occurred_at=at,
            actor_user_id=actor_id,
            resource_type=self.kind.name,
            resource_id=definition.id,
            organization_id=definition.organization_id,
            workspace_id=definition.workspace_id,
            project_id=definition.project_id,
            previous_state=previous_state,
            new_state=new_state,
            detail=detail or {},
        )


class SavedFilterService(ConfigurationService):
    kind = SAVED_FILTER
    repository = "filter_definitions"
    id_prefix = "fil"
    version_prefix = "filv"
    record_type = FilterDefinitionRecord
    version_type = FilterVersionRecord


class FilterPresetService(ConfigurationService):
    kind = FILTER_PRESET
    repository = "filter_presets"
    id_prefix = "fpr"
    version_prefix = "fprv"
    record_type = FilterPresetRecord
    version_type = FilterPresetVersionRecord
    is_preset = True


class SavedRankingService(ConfigurationService):
    kind = SAVED_RANKING
    repository = "ranking_definitions"
    id_prefix = "rnk"
    version_prefix = "rnkv"
    record_type = RankingDefinitionRecord
    version_type = RankingVersionRecord
    is_ranking = True


class RankingPresetService(ConfigurationService):
    kind = RANKING_PRESET
    repository = "ranking_presets"
    id_prefix = "rpr"
    version_prefix = "rprv"
    record_type = RankingPresetRecord
    version_type = RankingPresetVersionRecord
    is_preset = True
    is_ranking = True


@dataclass(frozen=True, slots=True)
class ValidateFilterQuery:
    """Validation without persistence, for the builder's inline feedback."""

    actor: ActorContext
    request: RequestContext
    content: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FilterValidationView:
    valid: bool
    canonical: dict[str, Any] | None
    canonical_hash: str | None
    field_dictionary_version: str
    condition_count: int
    depth: int
    field_ids: tuple[str, ...]
    issues: tuple[dict[str, Any], ...] = ()


class ValidateFilterExpression:
    """Reports what the server would accept, with every finding.

    Deliberately never repairs anything: a builder that silently corrected a
    condition would apply a filter the user did not write.
    """

    def __init__(self, services: QueryServices) -> None:
        self._services = services

    async def execute(self, query: ValidateFilterQuery) -> FilterValidationView:
        registry = self._services.fields
        try:
            expression = group_from_payload(query.content)
            validated = validate_filter(
                expression,
                registry=registry,
                limits=self._services.limits,
                allow_empty=True,
            )
        except ValidationError as error:
            issues = error.details.get("issues") if error.details else None
            return FilterValidationView(
                valid=False,
                canonical=None,
                canonical_hash=None,
                field_dictionary_version=registry.version,
                condition_count=0,
                depth=0,
                field_ids=(),
                issues=tuple(issues or ({"path": "$", "message": str(error)},)),
            )
        return FilterValidationView(
            valid=True,
            canonical=validated.canonical,
            canonical_hash=validated.canonical_hash,
            field_dictionary_version=validated.field_dictionary_version,
            condition_count=validated.condition_count,
            depth=validated.depth,
            field_ids=validated.field_ids,
        )


__all__ = [
    "AddVersionCommand",
    "ConfigurationService",
    "ConfigurationView",
    "CreateConfigurationCommand",
    "FilterPresetService",
    "FilterValidationView",
    "GetConfigurationQuery",
    "LifecycleCommand",
    "ListConfigurationsQuery",
    "RankingPresetService",
    "SavedFilterService",
    "SavedRankingService",
    "UpdateMetadataCommand",
    "ValidateFilterExpression",
    "ValidateFilterQuery",
    "ValidatedContent",
]
