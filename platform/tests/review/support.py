"""Shared arrangement for the Package 11 tests.

Nothing here evaluates a criterion or derives a classification. Every
classification named below is a *fixture-declared human decision*, recorded exactly
as a reviewer would have recorded it. No fixture claims a real clinical conclusion
about a real variant.
"""

from __future__ import annotations

from app.application.repositories import Page
from app.application.use_cases.review.adjudication import (
    AdjudicateInterpretation,
    AdjudicateInterpretationCommand,
    FinalizeInterpretation,
    FinalizeInterpretationCommand,
)
from app.application.use_cases.review.interpretations import (
    OpenInterpretation,
    OpenInterpretationCommand,
    RecordInterpretationVersion,
    RecordInterpretationVersionCommand,
)
from app.application.use_cases.review.reviews import (
    ADJUDICATOR_ROLE,
    AssignReviewer,
    AssignReviewerCommand,
    RecordReviewDecision,
    RecordReviewDecisionCommand,
    SubmitReview,
    SubmitReviewCommand,
)
from app.application.use_cases.tenancy.projects import (
    AddProjectMember,
    AddProjectMemberCommand,
    CreateProject,
    CreateProjectCommand,
)
from app.domain.value_objects.enums import Classification, ProjectRole
from tests.support.actors import actor_for, create_account
from tests.tenancy.test_organizations_and_memberships import approved_organization
from tests.tenancy.test_projects_and_isolation import add_member

PAGE = Page(number=1, size=25)

#: DEVELOPMENT ONLY identifiers. They name a fixture, not a real variant.
VARIANT_ID = "var_fixture_review_1"
CONDITION = "FIXTURE:COND"
RATIONALE = "fixture reasoning, not a clinical rationale"


async def organization_project(harness, owner_id: str, name: str = "Review Project"):
    """A project inside an organization workspace, so reviewers can be added.

    Human review needs more than one person on one project, which a personal
    workspace deliberately does not allow.
    """
    view = await approved_organization(harness, owner_id)
    return view.organization, await project_for(harness, owner_id, view.workspace_id, name)


async def project_for(harness, owner_id: str, workspace_id: str, name: str = "Review Project"):
    view = await CreateProject(harness.tenancy).execute(
        CreateProjectCommand(
            actor=await actor_for(harness, owner_id),
            workspace_id=workspace_id,
            name=name,
            description=None,
            request=harness.request,
        )
    )
    return view.project


async def project_member(
    harness, owner_id: str, organization_id: str, project_id: str, email: str, role: ProjectRole
):
    user_id = await add_member(harness, organization_id, owner_id, email)
    await AddProjectMember(harness.tenancy).execute(
        AddProjectMemberCommand(
            actor=await actor_for(harness, owner_id),
            project_id=project_id,
            user_id=user_id,
            role=role,
            request=harness.request,
        )
    )
    return user_id


async def open_interpretation(harness, actor_id: str, project_id: str, **kwargs):
    return await OpenInterpretation(harness.review).execute(
        OpenInterpretationCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            project_id=project_id,
            variant_id=kwargs.pop("variant_id", VARIANT_ID),
            condition_identifier=kwargs.pop("condition_identifier", CONDITION),
            **kwargs,
        )
    )


async def record_version(harness, actor_id: str, interpretation_id: str, **kwargs):
    return await RecordInterpretationVersion(harness.review).execute(
        RecordInterpretationVersionCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            interpretation_id=interpretation_id,
            classification=kwargs.pop("classification", Classification.UNCERTAIN_SIGNIFICANCE),
            rationale=kwargs.pop("rationale", RATIONALE),
            **kwargs,
        )
    )


async def assign(harness, actor_id: str, interpretation_id: str, reviewer_id: str, **kwargs):
    return await AssignReviewer(harness.review).execute(
        AssignReviewerCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            interpretation_id=interpretation_id,
            reviewer_user_id=reviewer_id,
            **kwargs,
        )
    )


async def decide(harness, actor_id: str, interpretation_id: str, version_id: str, **kwargs):
    return await RecordReviewDecision(harness.review).execute(
        RecordReviewDecisionCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            interpretation_id=interpretation_id,
            interpretation_version_id=version_id,
            **kwargs,
        )
    )


async def submit(harness, actor_id: str, interpretation_id: str):
    return await SubmitReview(harness.review).execute(
        SubmitReviewCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            interpretation_id=interpretation_id,
        )
    )


async def adjudicate(harness, actor_id: str, interpretation_id: str, **kwargs):
    return await AdjudicateInterpretation(harness.review).execute(
        AdjudicateInterpretationCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            interpretation_id=interpretation_id,
            classification=kwargs.pop("classification", Classification.UNCERTAIN_SIGNIFICANCE),
            rationale=kwargs.pop("rationale", RATIONALE),
            **kwargs,
        )
    )


async def finalize(harness, actor_id: str, interpretation_id: str, **kwargs):
    return await FinalizeInterpretation(harness.review).execute(
        FinalizeInterpretationCommand(
            actor=await actor_for(harness, actor_id),
            request=harness.request,
            interpretation_id=interpretation_id,
            rationale=kwargs.pop("rationale", RATIONALE),
            **kwargs,
        )
    )


__all__ = [
    "ADJUDICATOR_ROLE",
    "CONDITION",
    "PAGE",
    "RATIONALE",
    "VARIANT_ID",
    "adjudicate",
    "assign",
    "decide",
    "finalize",
    "open_interpretation",
    "organization_project",
    "project_for",
    "project_member",
    "record_version",
    "submit",
]
