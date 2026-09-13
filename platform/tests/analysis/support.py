"""Shared arrangement for the Package 5 tests.

Every helper drives the real use cases, so no test can arrange a state the
platform itself would refuse to produce. The capability key used here is the
development adapter's integration probe: it performs no analysis and stands in
for the independently deployed scientific subsystem.
"""

from __future__ import annotations

from app.application.repositories import Page
from app.application.use_cases.analysis.configurations import (
    ConfigurationInputRequest,
    CreateConfigurationVersion,
    CreateConfigurationVersionCommand,
)
from app.application.use_cases.analysis.definitions import (
    ChangeAnalysisState,
    ChangeAnalysisStateCommand,
    CreateAnalysis,
    CreateAnalysisCommand,
)
from app.application.use_cases.analysis.executions import (
    RequestExecution,
    RequestExecutionCommand,
)
from app.application.use_cases.analysis.nodes import RegisterNode, RegisterNodeCommand
from app.domain.value_objects.enums import AnalysisKind, AnalysisState, NodeClass
from tests.data.support import uploaded_artifact
from tests.support.actors import actor_for
from tests.tenancy.test_projects_and_isolation import personal_project

PAGE = Page(number=1, size=25)

#: DEVELOPMENT ONLY probe capability. Never a scientific computation.
PROBE_CAPABILITY = "integration.echo"


async def project_analysis(
    harness,
    user_id: str,
    *,
    project_id: str | None = None,
    name: str = "Trio Screen",
    capability_key: str = PROBE_CAPABILITY,
):
    if project_id is None:
        project = await personal_project(harness, user_id, name=f"{name} Project")
        project_id = project.project.id
    view = await CreateAnalysis(harness.analysis).execute(
        CreateAnalysisCommand(
            actor=await actor_for(harness, user_id),
            workspace_id="",
            project_id=project_id,
            name=name,
            kind=AnalysisKind.VARIANT_PRIORITIZATION,
            description=None,
            capability_key=capability_key,
            request=harness.request,
        )
    )
    return view


async def dataset_version_for(harness, user_id: str, *, name: str = "Inputs"):
    """An *accepted* dataset version: the only kind that may feed an analysis."""
    from app.application.use_cases.data.datasets import (
        DecideDatasetVersion,
        DecideDatasetVersionCommand,
    )
    from tests.data.support import draft_version, personal_dataset

    dataset = await personal_dataset(harness, user_id, name=name)
    version = await draft_version(harness, user_id, dataset.dataset.id)
    await uploaded_artifact(harness, user_id, version.version.id)
    accepted = await DecideDatasetVersion(harness.data).execute(
        DecideDatasetVersionCommand(
            actor=await actor_for(harness, user_id),
            version_id=version.version.id,
            accept=True,
            reason=None,
            request=harness.request,
        )
    )
    return accepted.version


async def configured_analysis(
    harness,
    user_id: str,
    *,
    name: str = "Trio Screen",
    with_input: bool = True,
):
    """An analysis in a state where an execution may be requested."""
    analysis = await project_analysis(harness, user_id, name=name)
    inputs: tuple[ConfigurationInputRequest, ...] = ()
    if with_input:
        version = await dataset_version_for(harness, user_id, name=f"{name} Inputs")
        inputs = (
            ConfigurationInputRequest(dataset_version_id=version.id, role="primary"),
        )
    configuration = await CreateConfigurationVersion(harness.analysis).execute(
        CreateConfigurationVersionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
            label="v1",
            inputs=inputs,
            filtering_configuration={"min_depth": 10},
            execution_parameters={"threads": 2},
            activate=True,
        )
    )
    await ChangeAnalysisState(harness.analysis).execute(
        ChangeAnalysisStateCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            target=AnalysisState.READY,
            request=harness.request,
        )
    )
    return analysis, configuration


async def queued_execution(harness, user_id: str, *, name: str = "Trio Screen"):
    analysis, configuration = await configured_analysis(harness, user_id, name=name)
    execution = await RequestExecution(harness.analysis).execute(
        RequestExecutionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
        )
    )
    return analysis, configuration, execution


async def register_scientific_node(
    harness,
    *,
    node_key: str = "sci-node-1",
    capabilities: tuple[str, ...] = (PROBE_CAPABILITY,),
    max_concurrency: int = 4,
):
    return await RegisterNode(harness.analysis).execute(
        RegisterNodeCommand(
            node_key=node_key,
            node_class=NodeClass.SCIENTIFIC_WORKER,
            queues=("scientific", "default"),
            capabilities=capabilities,
            resource_profile={"cpu_cores": 8, "memory_mib": 65536, "disk_mib": 524288},
            max_concurrency=max_concurrency,
            engine_version="0.0.0-development-only",
            environment_version="0.0.0-development-only",
        )
    )


__all__ = [
    "PAGE",
    "PROBE_CAPABILITY",
    "configured_analysis",
    "dataset_version_for",
    "project_analysis",
    "queued_execution",
    "register_scientific_node",
]
