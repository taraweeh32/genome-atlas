"""Authentication endpoints.

Thin transport: each handler builds a command, calls one use case and shapes the
response. Every security rule (uniform failures, lockout, rate limiting, token
single-use, session revocation) lives in the application and domain layers, so
these handlers cannot weaken it.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.cookies import clear_session_cookies, set_session_cookies
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.identity import (
    AccountResponse,
    AcknowledgementResponse,
    IdentityResponse,
    PasswordChangeRequest,
    PasswordResetCompletionRequest,
    PasswordResetRequest,
    RegistrationRequest,
    ResendVerificationRequest,
    SessionSummary,
    SignInRequest,
    SignOutRequest,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.application.use_cases.identity.authentication import (
    AuthenticateUser,
    AuthenticateUserCommand,
    ChangePassword,
    ChangePasswordCommand,
    CompletePasswordReset,
    CompletePasswordResetCommand,
    RequestPasswordReset,
    RequestPasswordResetCommand,
    SignOut,
    SignOutCommand,
)
from app.application.use_cases.identity.registration import (
    RegisterUser,
    RegisterUserCommand,
    ResendVerification,
    ResendVerificationCommand,
    VerifyEmail,
    VerifyEmailCommand,
)
from app.domain.identity.entities import Session, UserAccount

router = APIRouter(prefix="/auth", tags=["authentication"])

#: The same wording for every uninformative acknowledgement.
_ACKNOWLEDGEMENT = (
    "If the details correspond to an account, the next step has been sent to that "
    "email address."
)


def account_response(account: UserAccount) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        email=account.email,
        display_name=account.display_name,
        account_state=account.account_state.value,
        email_verification_state=account.email_verification_state.value,
        personal_workspace_id=account.personal_workspace_id,
        created_at=account.created_at,
    )


def session_summary(session: Session) -> SessionSummary:
    return SessionSummary(
        id=session.id,
        issued_at=session.issued_at,
        expires_at=session.expires_at,
        absolute_expires_at=session.absolute_expires_at,
        last_seen_at=session.last_seen_at,
        user_agent_summary=session.user_agent_summary,
    )


@router.post(
    "/register",
    response_model=AcknowledgementResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Register an account",
    description="Creates an unverified account and its personal workspace, and "
    "issues an email-verification token. The response is identical whether or "
    "not the address already exists, and never establishes a session.",
    responses=ERROR_RESPONSES,
)
async def register(
    payload: RegistrationRequest,
    container: ContainerDep,
    context: RequestContextDep,
) -> AcknowledgementResponse:
    result = await RegisterUser(container.identity_services()).execute(
        RegisterUserCommand(
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            request=context,
        )
    )
    return AcknowledgementResponse(
        message=_ACKNOWLEDGEMENT,
        development_only_token=result.development_only_verification_token,
    )


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    summary="Verify an email address",
    responses=ERROR_RESPONSES,
)
async def verify_email(
    payload: VerifyEmailRequest,
    container: ContainerDep,
    context: RequestContextDep,
) -> VerifyEmailResponse:
    result = await VerifyEmail(container.identity_services()).execute(
        VerifyEmailCommand(token=payload.token, request=context)
    )
    return VerifyEmailResponse(
        verified=result.verified, pending_invitation_count=result.pending_invitation_count
    )


@router.post(
    "/resend-verification",
    response_model=AcknowledgementResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-send an email verification",
    responses=ERROR_RESPONSES,
)
async def resend_verification(
    payload: ResendVerificationRequest,
    container: ContainerDep,
    context: RequestContextDep,
) -> AcknowledgementResponse:
    result = await ResendVerification(container.identity_services()).execute(
        ResendVerificationCommand(email=payload.email, request=context)
    )
    return AcknowledgementResponse(
        message=_ACKNOWLEDGEMENT,
        development_only_token=result.development_only_verification_token,
    )


@router.post(
    "/sign-in",
    response_model=IdentityResponse,
    summary="Sign in",
    description="Establishes an opaque server-side session delivered as an "
    "HttpOnly cookie, plus a CSRF cookie the client must echo in a header on "
    "unsafe requests.",
    responses=ERROR_RESPONSES,
)
async def sign_in(
    payload: SignInRequest,
    response: Response,
    container: ContainerDep,
    context: RequestContextDep,
) -> IdentityResponse:
    result = await AuthenticateUser(container.identity_services()).execute(
        AuthenticateUserCommand(
            email=payload.email, password=payload.password, request=context
        )
    )
    policy = container.application.security
    set_session_cookies(
        response,
        session_token=result.issued.session_token,
        csrf_token=result.issued.csrf_token,
        max_age_seconds=policy.session_absolute_hours * 3600,
        policy=policy,
        environment=container.environment.environment,
    )
    async with container.unit_of_work.begin() as repositories:
        actor = await container.authorization.resolve(
            repositories, result.account, session=result.issued.session
        )
    return IdentityResponse(
        account=account_response(result.account),
        session=session_summary(result.issued.session),
        platform_roles=sorted(role.value for role in actor.platform_roles),
        capabilities=sorted(p.value for p in actor.platform_capabilities()),
        requires_reauthentication=False,
    )


@router.post(
    "/sign-out",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    responses=ERROR_RESPONSES,
)
async def sign_out(
    payload: SignOutRequest,
    response: Response,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await SignOut(container.identity_services()).execute(
        SignOutCommand(
            session_id=caller.session.id,
            user_id=caller.account.id,
            request=context,
            all_sessions=payload.all_sessions,
        )
    )
    clear_session_cookies(response, policy=container.application.security)


@router.post(
    "/password-reset",
    response_model=AcknowledgementResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password reset",
    responses=ERROR_RESPONSES,
)
async def request_password_reset(
    payload: PasswordResetRequest,
    container: ContainerDep,
    context: RequestContextDep,
) -> AcknowledgementResponse:
    result = await RequestPasswordReset(container.identity_services()).execute(
        RequestPasswordResetCommand(email=payload.email, request=context)
    )
    return AcknowledgementResponse(
        message=_ACKNOWLEDGEMENT, development_only_token=result.development_only_reset_token
    )


@router.post(
    "/password-reset/complete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Complete a password reset",
    description="Consumes the single-use token, replaces the password and revokes "
    "every existing session for that account.",
    responses=ERROR_RESPONSES,
)
async def complete_password_reset(
    payload: PasswordResetCompletionRequest,
    response: Response,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await CompletePasswordReset(container.identity_services()).execute(
        CompletePasswordResetCommand(
            token=payload.token, new_password=payload.new_password, request=context
        )
    )
    clear_session_cookies(response, policy=container.application.security)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change your password",
    description="Requires the current password. Every other session is revoked; "
    "the session performing the change keeps working.",
    responses=ERROR_RESPONSES,
)
async def change_password(
    payload: PasswordChangeRequest,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await ChangePassword(container.identity_services()).execute(
        ChangePasswordCommand(
            user_id=caller.account.id,
            session_id=caller.session.id,
            current_password=payload.current_password,
            new_password=payload.new_password,
            request=context,
        )
    )


__all__ = ["account_response", "router", "session_summary"]
