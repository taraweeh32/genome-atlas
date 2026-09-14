"""Analysis configurations and configuration versions.

Rules the backend owns here:

* A configuration version is **immutable**. Editing parameters always creates the
  next numbered version, so an execution that referenced version 3 stays
  reproducible after version 4 exists.
* The scientific *content* of a section is opaque here: this package validates
  structure, references and inputs — never scientific meaning. Semantic
  validation belongs to the scientific subsystem.
* Declared inputs must be dataset versions that exist, belong to the same
  workspace and were accepted. An unaccepted input is never silently used.
* Activating a version is a separate, audited decision from creating it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import (
    READ,
    UPDATE,
    AnalysisServices,
    require_analysis_access,
)
from app.application.use_cases.query.analysis_binding import validate_query_sections
from app.domain.analysis.entities import (
    AnalysisConfigurationVersion,
    ConfigurationInput,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    AuditOutcome,
    ConfigurationValidationState,
    DatasetVersionState,
)
from app.infrastructure.persistence.repositories.base import new_id

#: Input roles the orchestration layer understands. The scientific meaning of a
#: role is the subsystem's business; the application only needs to know that a
#: role is declared, unique per dataset version, and that ``primary`` exists.
KNOWN_INPUT_ROLES = ("primary", "control", "manifest", "reference", "auxiliary")
MAX_INPUTS = 50


@dataclass(frozen=True, slots=True)
class ConfigurationInputRequest:
    dataset_version_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ConfigurationView:
    configuration: AnalysisConfigurationVersion
    inputs: tuple[ConfigurationInput, ...]
    is_current: bool = False


def content_hash(sections: dict[str, dict]) -> str:
    """Digest over the scientific sections, for parameter-identity comparison.

    Never used to deduplicate or replace a version — history stays intact even
    when two versions are byte-identical.
    """
    payload = json.dumps(sections, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_inputs(requested: tuple[ConfigurationInputRequest, ...]) -> None:
    if not requested:
        raise ValidationError(
            "a configuration must declare at least one input dataset version",
            details={"field": "inputs"},
        )
    if len(requested) > MAX_INPUTS:
        raise ValidationError(
            f"a configuration may declare at most {MAX_INPUTS} inputs",
            details={"field": "inputs"},
        )
    seen: set[tuple[str, str]] = set()
    for item in requested:
        if item.role not in KNOWN_INPUT_ROLES:
            raise ValidationError(
                "unknown input role",
                details={"field": "inputs.role", "value": item.role},
            )
        key = (item.dataset_version_id, item.role)
        if key in seen:
            raise ValidationError(
                "the same dataset version is declared twice in the same role",
                details={"field": "inputs", "value": item.dataset_version_id},
            )
        seen.add(key)
    if not any(item.role == "primary" for item in requested):
        raise ValidationError(
            "a configuration must declare a primary input", details={"field": "inputs"}
        )


@dataclass(frozen=True, slots=True)
class CreateConfigurationVersionCommand:
    actor: ActorContext
    analysis_id: str
    request: RequestContext
    label: str | None = None
    inputs: tuple[ConfigurationInputRequest, ...] = ()
    filtering_configuration: dict | None = None
    ranking_configuration: dict | None = None
    annotation_configuration: dict | None = None
    evidence_configuration: dict | None = None
    interpretation_configuration: dict | None = None
    reporting_configuration: dict | None = None
    execution_parameters: dict | None = None
    pipeline_resource_id: str | None = None
    engine_resource_id: str | None = None
    reference_genome_resource_id: str | None = None
    ruleset_resource_id: str | None = None
    execution_profile_resource_id: str | None = None
    #: Make this the analysis's current configuration in the same transaction.
    activate: bool = False


class CreateConfigurationVersion:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: CreateConfigurationVersionCommand) -> ConfigurationView:
        _validate_inputs(command.inputs)
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            analysis = await repositories.analyses.get(command.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", command.analysis_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                command.actor,
                analysis,
                action=UPDATE,
                recorder=recorder,
                occurred_at=now,
            )
            # Inputs are re-resolved server-side: a request may name a dataset
            # version, it may never assert that the version is usable.
            for item in command.inputs:
                version = await repositories.dataset_versions.get(item.dataset_version_id)
                if version is None:
                    raise NotFoundError("dataset_version", item.dataset_version_id)
                dataset = await repositories.datasets.get(version.dataset_id)
                if (
                    dataset is None
                    or not dataset.is_active
                    or dataset.workspace_id != analysis.workspace_id
                ):
                    # Cross-tenant reach is refused as "not found": knowing an id
                    # never reveals a resource in another workspace.
                    raise NotFoundError("dataset_version", item.dataset_version_id)
                if version.state is not DatasetVersionState.ACCEPTED:
                    raise ValidationError(
                        "only an accepted dataset version may be used as analysis input",
                        details={
                            "field": "inputs",
                            "dataset_version_id": item.dataset_version_id,
                            "state": version.state.value,
                        },
                    )
            # Structural validation of the two sections this package owns. The
            # remaining sections stay opaque: their meaning is the scientific
            # subsystem's business.
            validate_query_sections(
                command.filtering_configuration, command.ranking_configuration
            )
            sections = {
                "filtering": command.filtering_configuration or {},
                "ranking": command.ranking_configuration or {},
                "annotation": command.annotation_configuration or {},
                "evidence": command.evidence_configuration or {},
                "interpretation": command.interpretation_configuration or {},
                "reporting": command.reporting_configuration or {},
                "execution": command.execution_parameters or {},
                "resources": {
                    "pipeline": command.pipeline_resource_id,
                    "engine": command.engine_resource_id,
                    "reference_genome": command.reference_genome_resource_id,
                    "ruleset": command.ruleset_resource_id,
                    "execution_profile": command.execution_profile_resource_id,
                },
                "inputs": [
                    {"dataset_version_id": item.dataset_version_id, "role": item.role}
                    for item in command.inputs
                ],
            }
            version_number = await repositories.analysis_configurations.next_version_number(
                analysis.id
            )
            configuration = AnalysisConfigurationVersion(
                id=new_id("acf"),
                analysis_id=analysis.id,
                version_number=version_number,
                created_by=scope.actor.actor_id,
                label=command.label,
                filtering_configuration=command.filtering_configuration or {},
                ranking_configuration=command.ranking_configuration or {},
                annotation_configuration=command.annotation_configuration or {},
                evidence_configuration=command.evidence_configuration or {},
                interpretation_configuration=command.interpretation_configuration or {},
                reporting_configuration=command.reporting_configuration or {},
                execution_parameters=command.execution_parameters or {},
                pipeline_resource_id=command.pipeline_resource_id,
                engine_resource_id=command.engine_resource_id,
                reference_genome_resource_id=command.reference_genome_resource_id,
                ruleset_resource_id=command.ruleset_resource_id,
                execution_profile_resource_id=command.execution_profile_resource_id,
                # Structurally valid is *not* scientifically validated; the state
                # says exactly what the application actually checked.
                validation_state=ConfigurationValidationState.VALID,
                validation_findings={"checked": "structure_and_inputs"},
                content_hash=content_hash(sections),
                snapshot=sections,
            )
            stored = await repositories.analysis_configurations.add(configuration)
            inputs = tuple(
                ConfigurationInput(
                    id=new_id("aci"),
                    analysis_configuration_id=stored.id,
                    dataset_version_id=item.dataset_version_id,
                    role=item.role,
                )
                for item in command.inputs
            )
            await repositories.analysis_configurations.add_inputs(inputs)
            is_current = False
            if command.activate:
                updated = analysis.with_current_configuration(stored.id)
                await repositories.analyses.save(updated)
                is_current = True
            await recorder.audit(
                action="analysis_configuration.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis_configuration",
                resource_id=stored.id,
                workspace_id=analysis.workspace_id,
                project_id=analysis.project_id,
                detail={"analysis_id": analysis.id, "version_number": stored.version_number},
            )
            await recorder.event(
                event_type=EventType.ANALYSIS_CONFIGURATION_CREATED,
                aggregate_type="analysis_configuration",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=analysis.workspace_id,
                payload={"analysis_id": analysis.id, "version_number": stored.version_number},
            )
        return ConfigurationView(configuration=stored, inputs=inputs, is_current=is_current)


@dataclass(frozen=True, slots=True)
class ActivateConfigurationCommand:
    actor: ActorContext
    analysis_id: str
    configuration_id: str
    request: RequestContext


class ActivateConfiguration:
    """Selects which existing version future executions use. Never edits one."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: ActivateConfigurationCommand) -> ConfigurationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            analysis = await repositories.analyses.get(command.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", command.analysis_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                command.actor,
                analysis,
                action=UPDATE,
                recorder=recorder,
                occurred_at=now,
            )
            configuration = await repositories.analysis_configurations.get(
                command.configuration_id
            )
            if configuration is None or configuration.analysis_id != analysis.id:
                raise NotFoundError("analysis_configuration", command.configuration_id)
            if not configuration.is_valid:
                raise ValidationError(
                    "this configuration version did not pass validation",
                    details={"field": "configuration_id"},
                )
            await repositories.analyses.save(analysis.with_current_configuration(configuration.id))
            inputs = await repositories.analysis_configurations.list_inputs(configuration.id)
            await recorder.audit(
                action="analysis_configuration.activated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis_configuration",
                resource_id=configuration.id,
                workspace_id=analysis.workspace_id,
                project_id=analysis.project_id,
                previous_state=analysis.current_configuration_id,
                new_state=configuration.id,
            )
            await recorder.event(
                event_type=EventType.ANALYSIS_CONFIGURATION_ACTIVATED,
                aggregate_type="analysis_configuration",
                aggregate_id=configuration.id,
                occurred_at=now,
                workspace_id=analysis.workspace_id,
                payload={"analysis_id": analysis.id},
            )
        return ConfigurationView(configuration=configuration, inputs=inputs, is_current=True)


@dataclass(frozen=True, slots=True)
class ListConfigurationsQuery:
    actor: ActorContext
    analysis_id: str
    page: Page
    request: RequestContext


class ListConfigurations:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListConfigurationsQuery) -> Paged[ConfigurationView]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            analysis = await repositories.analyses.get(query.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", query.analysis_id)
            await require_analysis_access(
                self._services,
                repositories,
                query.actor,
                analysis,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            page = await repositories.analysis_configurations.list_for_analysis(
                analysis.id, page=query.page
            )
            views: list[ConfigurationView] = []
            for configuration in page.items:
                inputs = await repositories.analysis_configurations.list_inputs(configuration.id)
                views.append(
                    ConfigurationView(
                        configuration=configuration,
                        inputs=inputs,
                        is_current=analysis.current_configuration_id == configuration.id,
                    )
                )
        return Paged(items=tuple(views), total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class GetConfigurationQuery:
    actor: ActorContext
    analysis_id: str
    configuration_id: str
    request: RequestContext


class GetConfiguration:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: GetConfigurationQuery) -> ConfigurationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            analysis = await repositories.analyses.get(query.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", query.analysis_id)
            await require_analysis_access(
                self._services,
                repositories,
                query.actor,
                analysis,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            configuration = await repositories.analysis_configurations.get(
                query.configuration_id
            )
            if configuration is None or configuration.analysis_id != analysis.id:
                raise NotFoundError("analysis_configuration", query.configuration_id)
            inputs = await repositories.analysis_configurations.list_inputs(configuration.id)
        return ConfigurationView(
            configuration=configuration,
            inputs=inputs,
            is_current=analysis.current_configuration_id == configuration.id,
        )


__all__ = [
    "KNOWN_INPUT_ROLES",
    "ActivateConfiguration",
    "ActivateConfigurationCommand",
    "ConfigurationInputRequest",
    "ConfigurationView",
    "CreateConfigurationVersion",
    "CreateConfigurationVersionCommand",
    "GetConfiguration",
    "GetConfigurationQuery",
    "ListConfigurations",
    "ListConfigurationsQuery",
    "content_hash",
]
