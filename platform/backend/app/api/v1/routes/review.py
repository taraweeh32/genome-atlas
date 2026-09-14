"""Interpretation, human review and adjudication endpoints.

Thin handlers: parse transport input, hand an explicit command to a use case, shape
the result. No handler evaluates a criterion, combines criteria or decides a
classification.

Boundaries visible in the layout:

* **Reviewing, adjudicating and finalizing are three operations with three
  permissions.** They are separate endpoints because they are separate authorities:
  a reviewer who disagreed does not adjudicate their own disagreement, and closing
  the record is its own act.
* **Scope never comes from the request.** Every path takes an interpretation
  identifier and authorization is resolved from the stored row's workspace and
  project, so a known identifier cannot become a cross-tenant read or write.
* **A correction is a new record.** There is no update endpoint for a finalized
  interpretation; ``/reclassify`` supersedes it and opens a successor.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.mapping import PageDep, page_meta, parse_enum
from app.api.v1.review_mapping import (
    assignment_response,
    decision_response,
    detail_response,
    interpretation_response,
    version_response,
)
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.review import (
    AdjudicatePayload,
    AssignReviewerPayload,
    FinalizePayload,
    InterpretationCollection,
    InterpretationDetailResponse,
    InterpretationResponse,
    InterpretationVersionResponse,
    OpenInterpretationPayload,
    ReclassifyPayload,
    RecordVersionPayload,
    ReviewAssignmentResponse,
    ReviewDecisionPayload,
    ReviewDecisionResponse,
)
from app.application.use_cases.review import (
    AdjudicateInterpretation,
    AdjudicateInterpretationCommand,
    AssignReviewer,
    AssignReviewerCommand,
    FinalizeInterpretation,
    FinalizeInterpretationCommand,
    InterpretationReader,
    OpenInterpretation,
    OpenInterpretationCommand,
    ReclassifyInterpretation,
    ReclassifyInterpretationCommand,
    RecordInterpretationVersion,
    RecordInterpretationVersionCommand,
    RecordReviewDecision,
    RecordReviewDecisionCommand,
    SubmitReview,
    SubmitReviewCommand,
)
from app.domain.value_objects.enums import (
    Classification,
    InterpretationState,
    ReviewDecision,
)

router = APIRouter(prefix="/interpretations", tags=["interpretation-review"])


@router.get(
    "",
    response_model=InterpretationCollection,
    summary="List interpretations the caller may read",
    responses=ERROR_RESPONSES,
)
async def list_interpretations(
    caller: CallerDep,
    container: ContainerDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    variant_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    assigned_to_me: Annotated[bool, Query()] = False,
) -> InterpretationCollection:
    paged = await InterpretationReader(
        container.review_services()
    ).list_interpretations(
        caller.actor,
        page=page,
        workspace_id=workspace_id,
        project_id=project_id,
        variant_id=variant_id,
        state=parse_enum(InterpretationState, state, field="state") if state else None,
        assigned_to_me=assigned_to_me,
    )
    return InterpretationCollection(
        items=[interpretation_response(item) for item in paged.items],
        page=page_meta(paged),
    )


@router.post(
    "",
    response_model=InterpretationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open an interpretation for a variant",
    responses=ERROR_RESPONSES,
)
async def open_interpretation(
    payload: OpenInterpretationPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InterpretationResponse:
    record = await OpenInterpretation(container.review_services()).execute(
        OpenInterpretationCommand(
            actor=caller.actor,
            request=context,
            project_id=payload.project_id,
            variant_id=payload.variant_id,
            sample_id=payload.sample_id,
            condition_identifier=payload.condition_identifier,
            condition_term=payload.condition_term,
        )
    )
    return interpretation_response(record)


@router.get(
    "/{interpretation_id}",
    response_model=InterpretationDetailResponse,
    summary="Get an interpretation with its versions, reviewers and decisions",
    responses=ERROR_RESPONSES,
)
async def get_interpretation(
    interpretation_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InterpretationDetailResponse:
    detail = await InterpretationReader(container.review_services()).detail(
        caller.actor, interpretation_id=interpretation_id, request=context
    )
    return detail_response(detail)


@router.post(
    "/{interpretation_id}/versions",
    response_model=InterpretationVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record an interpretation version",
    responses=ERROR_RESPONSES,
)
async def record_version(
    interpretation_id: str,
    payload: RecordVersionPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InterpretationVersionResponse:
    record = await RecordInterpretationVersion(container.review_services()).execute(
        RecordInterpretationVersionCommand(
            actor=caller.actor,
            request=context,
            interpretation_id=interpretation_id,
            classification=parse_enum(
                Classification, payload.classification, field="classification"
            ),
            rationale=payload.rationale,
            classification_evaluation_id=payload.classification_evaluation_id,
            automated_classification_id=payload.automated_classification_id,
            ruleset_id=payload.ruleset_id,
            ruleset_version=payload.ruleset_version,
            suggested_classification=parse_enum(
                Classification,
                payload.suggested_classification,
                field="suggested_classification",
            )
            if payload.suggested_classification
            else None,
            clinical_significance_statement=payload.clinical_significance_statement,
            criterion_evaluation_ids=tuple(payload.criterion_evaluation_ids),
            evidence_item_ids=tuple(payload.evidence_item_ids),
            metadata=dict(payload.metadata or {}),
        )
    )
    return version_response(record)


@router.post(
    "/{interpretation_id}/reviewers",
    response_model=ReviewAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a reviewer or adjudicator",
    responses=ERROR_RESPONSES,
)
async def assign_reviewer(
    interpretation_id: str,
    payload: AssignReviewerPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ReviewAssignmentResponse:
    record = await AssignReviewer(container.review_services()).execute(
        AssignReviewerCommand(
            actor=caller.actor,
            request=context,
            interpretation_id=interpretation_id,
            reviewer_user_id=payload.reviewer_user_id,
            review_role=payload.review_role,
            due_at=payload.due_at,
        )
    )
    return assignment_response(record)


@router.post(
    "/{interpretation_id}/decisions",
    response_model=ReviewDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a reviewer decision",
    responses=ERROR_RESPONSES,
)
async def record_decision(
    interpretation_id: str,
    payload: ReviewDecisionPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ReviewDecisionResponse:
    record = await RecordReviewDecision(container.review_services()).execute(
        RecordReviewDecisionCommand(
            actor=caller.actor,
            request=context,
            interpretation_id=interpretation_id,
            interpretation_version_id=payload.interpretation_version_id,
            decision=parse_enum(ReviewDecision, payload.decision, field="decision"),
            rationale=payload.rationale,
            criterion_evaluation_id=payload.criterion_evaluation_id,
            proposed_classification=parse_enum(
                Classification,
                payload.proposed_classification,
                field="proposed_classification",
            )
            if payload.proposed_classification
            else None,
            details=dict(payload.details or {}),
            expected_current_version_number=payload.expected_current_version_number,
        )
    )
    return decision_response(record)


@router.post(
    "/{interpretation_id}/submit-review",
    response_model=ReviewAssignmentResponse,
    summary="Submit the caller's own review",
    responses=ERROR_RESPONSES,
)
async def submit_review(
    interpretation_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ReviewAssignmentResponse:
    record = await SubmitReview(container.review_services()).execute(
        SubmitReviewCommand(
            actor=caller.actor, request=context, interpretation_id=interpretation_id
        )
    )
    return assignment_response(record)


@router.post(
    "/{interpretation_id}/adjudicate",
    response_model=InterpretationVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Adjudicate reviewer disagreement",
    responses=ERROR_RESPONSES,
)
async def adjudicate(
    interpretation_id: str,
    payload: AdjudicatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InterpretationVersionResponse:
    record = await AdjudicateInterpretation(container.review_services()).execute(
        AdjudicateInterpretationCommand(
            actor=caller.actor,
            request=context,
            interpretation_id=interpretation_id,
            classification=parse_enum(
                Classification, payload.classification, field="classification"
            ),
            rationale=payload.rationale,
            clinical_significance_statement=payload.clinical_significance_statement,
            details=dict(payload.details or {}),
        )
    )
    return version_response(record)


@router.post(
    "/{interpretation_id}/finalize",
    response_model=InterpretationVersionResponse,
    summary="Finalize an approved interpretation",
    responses=ERROR_RESPONSES,
)
async def finalize(
    interpretation_id: str,
    payload: FinalizePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InterpretationVersionResponse:
    record = await FinalizeInterpretation(container.review_services()).execute(
        FinalizeInterpretationCommand(
            actor=caller.actor,
            request=context,
            interpretation_id=interpretation_id,
            rationale=payload.rationale,
            expected_version_number=payload.expected_version_number,
        )
    )
    return version_response(record)


@router.post(
    "/{interpretation_id}/reclassify",
    response_model=InterpretationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Supersede a finalized interpretation and open its successor",
    responses=ERROR_RESPONSES,
)
async def reclassify(
    interpretation_id: str,
    payload: ReclassifyPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InterpretationResponse:
    record = await ReclassifyInterpretation(container.review_services()).execute(
        ReclassifyInterpretationCommand(
            actor=caller.actor,
            request=context,
            interpretation_id=interpretation_id,
            reason=payload.reason,
        )
    )
    return interpretation_response(record)
