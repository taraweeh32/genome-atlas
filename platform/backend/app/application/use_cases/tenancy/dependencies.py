"""The dependency bundle tenancy use cases share."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.services.authorization import AuthorizationService
from app.core.app_config import SecurityPolicySettings


@dataclass(frozen=True)
class TenancyServices:
    unit_of_work: Any
    clock: Any
    tokens: Any
    authorization: AuthorizationService
    policy: SecurityPolicySettings
    #: Non-production only: allows an invitation token to be returned in the
    #: response instead of being delivered out of band.
    expose_development_tokens: bool = False


__all__ = ["TenancyServices"]
