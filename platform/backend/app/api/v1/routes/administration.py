"""Platform administration endpoints.

Platform administration is distinct from organization administration: only a
platform administrator may approve organizations, change account states or grant
platform roles. An organization administrator reaching these routes is refused by
the same policy that guards every other operation — the namespace itself grants
nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.mapping import (
    PageDep,
    organization_response,
    organization_review_response,
    page_meta,
    parse_enum,
)
from app.api.v1.schemas.common import ERROR_RESPONSES, ApiModel
from app.api.v1.schemas.identity import (
    AccountAdministrationResponse,
    AccountLifecycleRequest,
    PlatformRoleRequest,
)
from app.api.v1.schemas.tenancy import (
    OrganizationDecisionPayload,
    OrganizationLifecyclePayload,
    OrganizationResponse,
    OrganizationReviewCollection,
    PageMeta,
)
from app.application.use_cases.identity.administration import (
    ChangeAccountLifecycle,
    ChangeAccountLifecycleCommand,
    ChangePlatformRole,
    ChangePlatformRoleCommand,
    ListAccounts,
    ListAccountsQuery,
)
from app.application.use_cases.tenancy.organizations import (
    ChangeOrganizationLifecycle,
    ChangeOrganizationLifecycleCommand,
    DecideOrganizationRequest,
    DecideOrganizationRequestCommand,
    ListOrganizationRequests,
    ListOrganizationRequestsQuery,
)
from app.domain.identity.entities import UserAccount
from app.domain.value_objects.enums import AccountState, OrganizationState, PlatformRole

router = APIRouter(prefix="/admin", tags=["administration"])


class AccountAdministrationCollection(ApiModel):
    items: list[AccountAdministrationResponse]
    page: PageMeta


def _account(account: UserAccount) -> AccountAdministrationResponse:
    return AccountAdministrationResponse(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
        account_state=account.account_state.value,
        email_verification_state=account.email_verification_state.value,
        deletion_state=account.deletion_state.value,
        last_activity_at=account.last_activity_at,
        created_at=account.created_at,
    )


@router.get(
    "/users",
    response_model=AccountAdministrationCollection,
    summary="List accounts",
    responses=ERROR_RESPONSES,
)
async def list_accounts(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    query: Annotated[str | None, Query(max_length=320)] = None,
) -> AccountAdministrationCollection:
    result = await ListAccounts(container.identity_services()).execute(
        ListAccountsQuery(actor=caller.actor, page=page, request=context, query=query)
    )
    return AccountAdministrationCollection(
        items=[_account(account) for account in result.items],
        page=page_meta(result),
    )


@router.post(
    "/users/{user_id}/state",
    response_model=AccountAdministrationResponse,
    summary="Suspend, reactivate or deactivate an account",
    description="Suspension requires a reason and revokes the account's sessions "
    "immediately. Administrators cannot change their own account state.",
    responses=ERROR_RESPONSES,
)
async def change_account_state(
    user_id: str,
    payload: AccountLifecycleRequest,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> AccountAdministrationResponse:
    account = await ChangeAccountLifecycle(container.identity_services()).execute(
        ChangeAccountLifecycleCommand(
            actor=caller.actor,
            user_id=user_id,
            target_state=parse_enum(AccountState, payload.state, field="state"),
            reason=payload.reason,
            request=context,
        )
    )
    return _account(account)


@router.post(
    "/users/{user_id}/platform-roles",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Grant or revoke a platform role",
    description="The most privileged operation in the platform. Recorded as a "
    "security event, and an administrator may not change their own roles.",
    responses=ERROR_RESPONSES,
)
async def change_platform_role(
    user_id: str,
    payload: PlatformRoleRequest,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await ChangePlatformRole(container.identity_services()).execute(
        ChangePlatformRoleCommand(
            actor=caller.actor,
            user_id=user_id,
            role=parse_enum(PlatformRole, payload.role, field="role"),
            grant=payload.grant,
            request=context,
        )
    )


@router.get(
    "/organization-requests",
    response_model=OrganizationReviewCollection,
    summary="Organizations awaiting approval",
    responses=ERROR_RESPONSES,
)
async def list_organization_requests(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> OrganizationReviewCollection:
    result = await ListOrganizationRequests(container.tenancy_services()).execute(
        ListOrganizationRequestsQuery(actor=caller.actor, page=page, request=context)
    )
    return OrganizationReviewCollection(
        items=[organization_review_response(item) for item in result.items],
        page=page_meta(result),
    )


@router.post(
    "/organization-requests/{organization_id}/decision",
    response_model=OrganizationResponse,
    summary="Approve or reject an organization request",
    description="Approval provisions the organization workspace and the owner "
    "membership in one transaction. Rejection requires a reason.",
    responses=ERROR_RESPONSES,
)
async def decide_organization_request(
    organization_id: str,
    payload: OrganizationDecisionPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> OrganizationResponse:
    view = await DecideOrganizationRequest(container.tenancy_services()).execute(
        DecideOrganizationRequestCommand(
            actor=caller.actor,
            organization_id=organization_id,
            approve=payload.approve,
            reason=payload.reason,
            request=context,
        )
    )
    return organization_response(view)


@router.post(
    "/organizations/{organization_id}/state",
    response_model=OrganizationResponse,
    summary="Suspend, reactivate or deactivate an organization",
    description="A lifecycle change only: no resource is deleted or transferred.",
    responses=ERROR_RESPONSES,
)
async def change_organization_state(
    organization_id: str,
    payload: OrganizationLifecyclePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> OrganizationResponse:
    view = await ChangeOrganizationLifecycle(container.tenancy_services()).execute(
        ChangeOrganizationLifecycleCommand(
            actor=caller.actor,
            organization_id=organization_id,
            target_state=parse_enum(OrganizationState, payload.state, field="state"),
            reason=payload.reason,
            request=context,
        )
    )
    return organization_response(view)


__all__ = ["router"]
