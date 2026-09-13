"""The dependency bundle identity use cases share.

A single explicit bundle keeps use-case constructors readable while remaining
plain data: it holds ports and configuration, never request state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.services.authorization import AuthorizationService
from app.application.services.sessions import SessionService
from app.core.app_config import SecurityPolicySettings
from app.domain.identity.passwords import PasswordPolicy


@dataclass(frozen=True)
class IdentityServices:
    #: Opens a transaction and yields the repository set bound to it.
    unit_of_work: Any
    clock: Any
    passwords: Any
    tokens: Any
    sessions: SessionService
    authorization: AuthorizationService
    rate_limiter: Any
    policy: SecurityPolicySettings
    password_policy: PasswordPolicy
    #: True only in non-production-like environments; controls whether a
    #: verification/reset token may be returned in an API response instead of
    #: being delivered out of band.
    expose_development_tokens: bool = False


__all__ = ["IdentityServices"]
