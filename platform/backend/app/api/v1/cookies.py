"""Session and CSRF cookie handling.

Two cookies, with deliberately different properties:

* the **session** cookie is ``HttpOnly`` — script must never be able to read the
  bearer of the session,
* the **CSRF** cookie is readable by the frontend on purpose: the client echoes
  it back in a request header, and the server compares the header against the
  hash bound to the session (double submit). A cookie alone therefore proves
  nothing.

Both are ``SameSite=Lax`` and ``Secure`` outside development, and both are
cleared on sign-out.
"""

from __future__ import annotations

from fastapi import Response

from app.core.app_config import SecurityPolicySettings
from app.core.environment import Environment


def set_session_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
    max_age_seconds: int,
    policy: SecurityPolicySettings,
    environment: Environment,
) -> None:
    secure = environment.is_production_like
    response.set_cookie(
        policy.session_cookie_name,
        session_token,
        max_age=max_age_seconds,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        policy.csrf_cookie_name,
        csrf_token,
        max_age=max_age_seconds,
        # Readable by the frontend by design: it must echo the value in a header.
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(
    response: Response,
    *,
    policy: SecurityPolicySettings,
) -> None:
    response.delete_cookie(policy.session_cookie_name, path="/")
    response.delete_cookie(policy.csrf_cookie_name, path="/")


__all__ = ["clear_session_cookies", "set_session_cookies"]
