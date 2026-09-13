"""Request/response schemas for identity and session endpoints.

No schema here ever carries a password hash, a token hash, a session token or
any other secret. Tokens appear in a response only in a non-production
environment, and then under an unmistakably named field.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel

PASSWORD_FIELD = Field(min_length=12, max_length=128)


class RegistrationRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = PASSWORD_FIELD
    display_name: str = Field(min_length=1, max_length=255)


class AcknowledgementResponse(ApiModel):
    """Deliberately uninformative acknowledgement.

    Registration, verification-resend and password-reset requests all return this
    shape whether or not the address exists, so the endpoint cannot be used to
    discover accounts.
    """

    accepted: bool = True
    message: str
    development_only_token: str | None = Field(
        default=None,
        description="Present only in non-production environments, where no mail "
        "transport is configured. Never returned in production.",
    )


class VerifyEmailRequest(ApiModel):
    token: str = Field(min_length=8, max_length=512)


class VerifyEmailResponse(ApiModel):
    verified: bool
    pending_invitation_count: int


class ResendVerificationRequest(ApiModel):
    email: str = Field(max_length=320)


class SignInRequest(ApiModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(ApiModel):
    email: str = Field(max_length=320)


class PasswordResetCompletionRequest(ApiModel):
    token: str = Field(min_length=8, max_length=512)
    new_password: str = PASSWORD_FIELD


class PasswordChangeRequest(ApiModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = PASSWORD_FIELD


class SignOutRequest(ApiModel):
    all_sessions: bool = False


class SessionSummary(ApiModel):
    id: str
    issued_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime
    last_seen_at: datetime | None
    user_agent_summary: str | None


class AccountResponse(ApiModel):
    id: str
    email: str
    display_name: str
    account_state: str
    email_verification_state: str
    personal_workspace_id: str | None
    created_at: datetime | None


class IdentityResponse(ApiModel):
    """What the frontend may know about the caller.

    ``platform_roles`` and ``capabilities`` are advisory: they let the UI hide
    controls the caller cannot use. Every request is still authorized on the
    server, so a modified response cannot grant anything.
    """

    account: AccountResponse
    session: SessionSummary
    platform_roles: list[str]
    capabilities: list[str]
    requires_reauthentication: bool


class AccountAdministrationResponse(ApiModel):
    id: str
    email: str
    display_name: str
    account_state: str
    email_verification_state: str
    deletion_state: str
    last_activity_at: datetime | None
    created_at: datetime | None


class AccountLifecycleRequest(ApiModel):
    state: str = Field(description="Target account state: active, suspended or deactivated.")
    reason: str | None = Field(default=None, max_length=1000)


class PlatformRoleRequest(ApiModel):
    role: str
    grant: bool


__all__ = [
    "AccountAdministrationResponse",
    "AccountLifecycleRequest",
    "AccountResponse",
    "AcknowledgementResponse",
    "IdentityResponse",
    "PasswordChangeRequest",
    "PasswordResetCompletionRequest",
    "PasswordResetRequest",
    "PlatformRoleRequest",
    "RegistrationRequest",
    "ResendVerificationRequest",
    "SessionSummary",
    "SignInRequest",
    "SignOutRequest",
    "VerifyEmailRequest",
    "VerifyEmailResponse",
]
