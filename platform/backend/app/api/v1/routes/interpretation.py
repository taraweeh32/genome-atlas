"""Ruleset, automated-evaluation and benchmark endpoints.

Thin handlers, as everywhere else: parse transport input, hand an explicit command
to a use case, shape the result. No handler evaluates a criterion, combines criteria
or decides a classification — the rules engine does that behind the existing
scientific gateway.

Three boundaries are visible in the layout:

* **Rulesets are platform-governed, evaluations are tenant content.** Registering a
  ruleset version, transitioning it and running benchmarks sit under
  ``/administration``; requesting an evaluation and reading it are authorized
  through the workspace of the variant being evaluated.
* **A delivery carries structured claims only.** The ingestion endpoint accepts
  criterion claims, a classification claim and provenance — never a command and
  never a scope. Scope comes from the evaluation row.
* **What comes back is a suggestion.** Every classification response declares its
  decision role and whether a newer suggestion has superseded it. Nothing here is a
  human or final clinical decision.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.interpretation_mapping import (
    benchmark_case_input,
    benchmark_case_response,
    benchmark_run_response,
    classification_response,
    combination_rule_from_payload,
    criterion_evaluation_response,
    criterion_from_payload,
    evaluation_response,
    finding_response,
    ingestion_payload,
    observation_input,
    ruleset_response,
)
from app.api.v1.mapping import PageDep, page_meta, parse_enum
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.interpretation import (
    BenchmarkCaseCollection,
    BenchmarkCaseResponse,
    BenchmarkRunCollection,
    BenchmarkRunResponse,
    ClassificationEvaluationCollection,
    ClassificationEvaluationDetailResponse,
    ClassificationEvaluationResponse,
    ClassificationHistoryResponse,
    IngestInterpretationPayloadBody,
    InterpretationIngestionResponse,
    RecordBenchmarkRunPayload,
    RegisterBenchmarkCasePayload,
    RegisterRulesetPayload,
    RequestEvaluationPayload,
    RulesetCollection,
    RulesetResponse,
    TransitionRulesetPayload,
)
from app.application.use_cases.interpretation.benchmarks import (
    BenchmarkReader,
    RecordBenchmarkRun,
    RecordBenchmarkRunCommand,
    RegisterBenchmarkCase,
    RegisterBenchmarkCaseCommand,
)
from app.application.use_cases.interpretation.evaluations import (
    ClassificationReader,
    RequestClassificationEvaluation,
    RequestEvaluationCommand,
)
from app.application.use_cases.interpretation.ingestion import (
    IngestInterpretationCommand,
    IngestInterpretationPayload,
)
from app.application.use_cases.interpretation.rulesets import (
    RegisterRuleset,
    RegisterRulesetCommand,
    RulesetReader,
    TransitionRuleset,
    TransitionRulesetCommand,
)
from app.domain.value_objects.enums import (
    BenchmarkValidationKind,
    ClassificationEvaluationState,
    RulesetCombinationStrategy,
    RulesetSpecificationScope,
    ScientificResourceState,
)

rulesets_router = APIRouter(prefix="/interpretation-rulesets", tags=["interpretation"])
evaluations_router = APIRouter(
    prefix="/classification-evaluations", tags=["interpretation"]
)
admin_rulesets_router = APIRouter(
    prefix="/administration/interpretation-rulesets", tags=["administration"]
)


# --------------------------------------------------------------------------- #
# Registry reads                                                              #
# --------------------------------------------------------------------------- #


@rulesets_router.get(
    "",
    response_model=RulesetCollection,
    summary="List interpretation ruleset versions",
    responses=ERROR_RESPONSES,
)
async def list_rulesets(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    ruleset_key: Annotated[str | None, Query()] = None,
    gene_symbol: Annotated[str | None, Query()] = None,
    usable_only: Annotated[bool, Query()] = True,
) -> RulesetCollection:
    paged = await RulesetReader(container.interpretation_services()).list_rulesets(
        caller.actor,
        context,
        page=page,
        ruleset_key=ruleset_key,
        gene_symbol=gene_symbol,
        usable_only=usable_only,
    )
    return RulesetCollection(
        items=[ruleset_response(item) for item in paged.items], page=page_meta(paged)
    )


@rulesets_router.get(
    "/{ruleset_id}",
    response_model=RulesetResponse,
    summary="Get one ruleset version with its criteria and combination rules",
    responses=ERROR_RESPONSES,
)
async def get_ruleset(
    ruleset_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> RulesetResponse:
    record = await RulesetReader(container.interpretation_services()).get(
        caller.actor, context, ruleset_id=ruleset_id
    )
    return ruleset_response(record)


# --------------------------------------------------------------------------- #
# Registry governance                                                         #
# --------------------------------------------------------------------------- #


@admin_rulesets_router.post(
    "",
    response_model=RulesetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new interpretation ruleset version",
    responses=ERROR_RESPONSES,
)
async def register_ruleset(
    payload: RegisterRulesetPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> RulesetResponse:
    record = await RegisterRuleset(container.interpretation_services()).execute(
        RegisterRulesetCommand(
            actor=caller.actor,
            request=context,
            ruleset_key=payload.ruleset_key,
            version=payload.version,
            display_name=payload.display_name,
            guideline_source=payload.guideline_source,
            criteria=tuple(criterion_from_payload(item) for item in payload.criteria),
            combination_rules=tuple(
                combination_rule_from_payload(item)
                for item in payload.combination_rules
            ),
            description=payload.description,
            guideline_citation=payload.guideline_citation,
            publication_reference=payload.publication_reference,
            publication_year=payload.publication_year,
            specification_scope=parse_enum(
                RulesetSpecificationScope,
                payload.specification_scope,
                field="specification_scope",
            )
            if payload.specification_scope
            else RulesetSpecificationScope.GENERAL,
            gene_symbol=payload.gene_symbol,
            condition_identifier=payload.condition_identifier,
            condition_term=payload.condition_term,
            combination_strategy=parse_enum(
                RulesetCombinationStrategy,
                payload.combination_strategy,
                field="combination_strategy",
            )
            if payload.combination_strategy
            else RulesetCombinationStrategy.CRITERIA_COMBINATION,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            capability_id=payload.capability_id,
            capability_version=payload.capability_version,
            engine_resource_id=payload.engine_resource_id,
            genome_assembly=payload.genome_assembly,
            provenance=payload.provenance,
            metadata=payload.metadata,
        )
    )
    return ruleset_response(record)


@admin_rulesets_router.post(
    "/{ruleset_id}/state",
    response_model=RulesetResponse,
    summary="Activate, deprecate, retire or invalidate a ruleset version",
    responses=ERROR_RESPONSES,
)
async def transition_ruleset(
    ruleset_id: str,
    payload: TransitionRulesetPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> RulesetResponse:
    record = await TransitionRuleset(container.interpretation_services()).execute(
        TransitionRulesetCommand(
            actor=caller.actor,
            request=context,
            ruleset_id=ruleset_id,
            state=parse_enum(ScientificResourceState, payload.state, field="state"),
            reason=payload.reason,
        )
    )
    return ruleset_response(record)


# --------------------------------------------------------------------------- #
# Automated evaluation                                                        #
# --------------------------------------------------------------------------- #


@evaluations_router.post(
    "",
    response_model=ClassificationEvaluationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request an automated classification evaluation for one variant",
    responses=ERROR_RESPONSES,
)
async def request_evaluation(
    payload: RequestEvaluationPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ClassificationEvaluationResponse:
    view = await RequestClassificationEvaluation(
        container.interpretation_services()
    ).execute(
        RequestEvaluationCommand(
            actor=caller.actor,
            request=context,
            workspace_id=payload.workspace_id,
            variant_id=payload.variant_id,
            ruleset_id=payload.ruleset_id,
            project_id=payload.project_id,
            gene_symbol=payload.gene_symbol,
            transcript_identifier=payload.transcript_identifier,
            condition_identifier=payload.condition_identifier,
            condition_term=payload.condition_term,
            inheritance=payload.inheritance,
            evidence_ids=tuple(payload.evidence_ids)
            if payload.evidence_ids is not None
            else None,
            idempotency_key=payload.idempotency_key,
            metadata=payload.metadata,
        )
    )
    return evaluation_response(view.evaluation)


@evaluations_router.get(
    "",
    response_model=ClassificationEvaluationCollection,
    summary="List classification evaluations the caller may read",
    responses=ERROR_RESPONSES,
)
async def list_evaluations(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    variant_id: Annotated[str | None, Query()] = None,
    ruleset_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> ClassificationEvaluationCollection:
    paged = await ClassificationReader(
        container.interpretation_services()
    ).list_evaluations(
        caller.actor,
        context,
        page=page,
        workspace_id=workspace_id,
        project_id=project_id,
        variant_id=variant_id,
        ruleset_id=ruleset_id,
        state=parse_enum(ClassificationEvaluationState, state, field="state")
        if state
        else None,
    )
    return ClassificationEvaluationCollection(
        items=[evaluation_response(item) for item in paged.items],
        page=page_meta(paged),
    )


@evaluations_router.get(
    "/{classification_evaluation_id}",
    response_model=ClassificationEvaluationDetailResponse,
    summary="Get one evaluation with its automated suggestion and criteria",
    responses=ERROR_RESPONSES,
)
async def get_evaluation(
    classification_evaluation_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ClassificationEvaluationDetailResponse:
    view = await ClassificationReader(container.interpretation_services()).get(
        caller.actor,
        context,
        classification_evaluation_id=classification_evaluation_id,
    )
    return ClassificationEvaluationDetailResponse(
        evaluation=evaluation_response(view.evaluation),
        classification=classification_response(view.classification)
        if view.classification
        else None,
        criteria=[criterion_evaluation_response(item) for item in view.criteria],
    )


@evaluations_router.get(
    "/variants/{variant_id}/history",
    response_model=ClassificationHistoryResponse,
    summary="Every automated suggestion recorded for one variant",
    responses=ERROR_RESPONSES,
)
async def classification_history(
    variant_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    ruleset_id: Annotated[str | None, Query()] = None,
) -> ClassificationHistoryResponse:
    records = await ClassificationReader(
        container.interpretation_services()
    ).history_for_variant(
        caller.actor, context, variant_id=variant_id, ruleset_id=ruleset_id
    )
    return ClassificationHistoryResponse(
        items=[classification_response(item) for item in records]
    )


@evaluations_router.post(
    "/{classification_evaluation_id}/interpretation",
    response_model=InterpretationIngestionResponse,
    summary="Deliver one rules-engine interpretation payload",
    responses=ERROR_RESPONSES,
)
async def ingest_interpretation(
    classification_evaluation_id: str,
    payload: IngestInterpretationPayloadBody,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InterpretationIngestionResponse:
    # The path identifies the evaluation; the body must agree with it. Scope is
    # never taken from the payload.
    body = payload.model_copy(update={"evaluation_id": classification_evaluation_id})
    result = await IngestInterpretationPayload(
        container.interpretation_services()
    ).execute(
        IngestInterpretationCommand(
            request=context,
            payload=ingestion_payload(body),
            actor=caller.actor,
        )
    )
    return InterpretationIngestionResponse(
        evaluation=evaluation_response(result.evaluation),
        classification=classification_response(result.classification)
        if result.classification
        else None,
        criteria=[criterion_evaluation_response(item) for item in result.criteria],
        findings=[finding_response(item) for item in result.findings],
        accepted=result.accepted,
    )


# --------------------------------------------------------------------------- #
# Controlled benchmark validation                                             #
# --------------------------------------------------------------------------- #


@admin_rulesets_router.post(
    "/{ruleset_id}/benchmark-cases",
    response_model=BenchmarkCaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register one controlled benchmark case for a ruleset version",
    responses=ERROR_RESPONSES,
)
async def register_benchmark_case(
    ruleset_id: str,
    payload: RegisterBenchmarkCasePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> BenchmarkCaseResponse:
    record = await RegisterBenchmarkCase(container.interpretation_services()).execute(
        RegisterBenchmarkCaseCommand(
            actor=caller.actor,
            request=context,
            ruleset_id=ruleset_id,
            **benchmark_case_input(payload),
        )
    )
    return benchmark_case_response(record)


@admin_rulesets_router.get(
    "/{ruleset_id}/benchmark-cases",
    response_model=BenchmarkCaseCollection,
    summary="List the benchmark cases registered for a ruleset version",
    responses=ERROR_RESPONSES,
)
async def list_benchmark_cases(
    ruleset_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    validation_kind: Annotated[str | None, Query()] = None,
) -> BenchmarkCaseCollection:
    records = await BenchmarkReader(container.interpretation_services()).list_cases(
        caller.actor,
        context,
        ruleset_id=ruleset_id,
        validation_kind=parse_enum(
            BenchmarkValidationKind, validation_kind, field="validation_kind"
        )
        if validation_kind
        else None,
    )
    return BenchmarkCaseCollection(
        items=[benchmark_case_response(item) for item in records]
    )


@admin_rulesets_router.post(
    "/{ruleset_id}/benchmark-runs",
    response_model=BenchmarkRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record one benchmark run against the registered cases",
    responses=ERROR_RESPONSES,
)
async def record_benchmark_run(
    ruleset_id: str,
    payload: RecordBenchmarkRunPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> BenchmarkRunResponse:
    record = await RecordBenchmarkRun(container.interpretation_services()).execute(
        RecordBenchmarkRunCommand(
            actor=caller.actor,
            request=context,
            ruleset_id=ruleset_id,
            observations=tuple(
                observation_input(item) for item in payload.observations
            ),
        )
    )
    return benchmark_run_response(record)


@admin_rulesets_router.get(
    "/{ruleset_id}/benchmark-runs",
    response_model=BenchmarkRunCollection,
    summary="List recorded benchmark runs for a ruleset version",
    responses=ERROR_RESPONSES,
)
async def list_benchmark_runs(
    ruleset_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> BenchmarkRunCollection:
    paged = await BenchmarkReader(container.interpretation_services()).list_runs(
        caller.actor, context, ruleset_id=ruleset_id, page=page
    )
    return BenchmarkRunCollection(
        items=[benchmark_run_response(item) for item in paged.items],
        page=page_meta(paged),
    )
