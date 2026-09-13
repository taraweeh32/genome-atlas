"""Session issuing, validation and revocation.

Server-authoritative by construction:

* the client receives an opaque token; the database stores only its keyed hash,
* every request re-reads the session row, so revocation takes effect immediately,
* a session has both an idle timeout (slid forward by activity) and an absolute
  lifetime (never extended),
* issuing a session enforces a per-user active-session ceiling by revoking the
  oldest sessions rather than refusing the new sign-in,
* the CSRF secret is bound to the session, so a stolen CSRF cookie is useless on
  another session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.application.services.context import RequestContext
from app.core.app_config import SecurityPolicySettings
from app.domain.errors import AuthenticationError
from app.domain.identity.entities import IssuedSession, Session, UserAccount
from app.domain.value_objects.enums import SessionState
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class ResolvedSession:
    session: Session
    account: UserAccount


class SessionService:
    def __init__(
        self,
        *,
        token_hasher,  # noqa: ANN001 - TokenHasher
        clock,  # noqa: ANN001 - Clock
        policy: SecurityPolicySettings,
    ) -> None:
        self._tokens = token_hasher
        self._clock = clock
        self._policy = policy

    # ------------------------------------------------------------------ #
    # Issuing                                                            #
    # ------------------------------------------------------------------ #

    async def issue(
        self,
        repositories,  # noqa: ANN001
        account: UserAccount,
        *,
        moment: datetime,
        request: RequestContext,
        mfa_satisfied: bool = False,
    ) -> IssuedSession:
        session_token, token_hash = self._tokens.mint_with_hash()
        csrf_token, csrf_hash = self._tokens.mint_with_hash()
        session = Session(
            id=new_id("ses"),
            user_id=account.id,
            state=SessionState.ACTIVE,
            issued_at=moment,
            expires_at=moment + timedelta(minutes=self._policy.session_idle_minutes),
            absolute_expires_at=moment
            + timedelta(hours=self._policy.session_absolute_hours),
            last_seen_at=moment,
            mfa_satisfied=mfa_satisfied,
            reauthenticated_at=moment,
            ip_hash=request.ip_hash,
            user_agent_summary=request.user_agent_summary,
            csrf_token_hash=csrf_hash,
        )
        await repositories.sessions.create(session, token_hash=token_hash)
        await self._enforce_session_ceiling(repositories, account.id, moment=moment)
        return IssuedSession(session=session, session_token=session_token, csrf_token=csrf_token)

    async def _enforce_session_ceiling(
        self,
        repositories,  # noqa: ANN001
        user_id: str,
        *,
        moment: datetime,
    ) -> None:
        active = await repositories.sessions.list_active_for_user(user_id)
        excess = len(active) - self._policy.max_active_sessions_per_user
        for stale in active[: max(excess, 0)]:
            await repositories.sessions.revoke(
                stale.id, reason="session_ceiling_exceeded", moment=moment
            )

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #

    async def resolve(
        self,
        repositories,  # noqa: ANN001
        raw_token: str | None,
        *,
        moment: datetime,
        slide_expiry: bool = True,
    ) -> ResolvedSession:
        """Resolve an opaque token to a live session and a usable account.

        Every failure raises the same ``AuthenticationError``: a caller must not
        be able to tell a revoked session from an unknown one.
        """
        if not raw_token:
            raise AuthenticationError("authentication is required")
        session = await repositories.sessions.get_by_token_hash(self._tokens.hash(raw_token))
        if session is None or not session.is_valid_at(moment):
            raise AuthenticationError("the session is not valid")
        account = await repositories.users.get(session.user_id)
        if account is None or not account.can_authenticate:
            # The account was suspended, deactivated or deleted after the session
            # was issued: the session dies with it, immediately.
            await repositories.sessions.revoke(
                session.id, reason="account_not_usable", moment=moment
            )
            raise AuthenticationError("the session is not valid")
        if slide_expiry:
            idle_expiry = min(
                moment + timedelta(minutes=self._policy.session_idle_minutes),
                session.absolute_expires_at,
            )
            await repositories.sessions.touch(
                session.id, last_seen_at=moment, expires_at=idle_expiry
            )
        return ResolvedSession(session=session, account=account)

    def verify_csrf(self, session: Session, provided_token: str | None) -> None:
        """Double-submit check, constant-time, bound to this session."""
        if not provided_token or not session.csrf_token_hash:
            raise AuthenticationError("a CSRF token is required for this request")
        if not self._tokens.matches(provided_token, session.csrf_token_hash):
            raise AuthenticationError("the CSRF token is not valid")

    def requires_reauthentication(self, session: Session, *, moment: datetime) -> bool:
        """True when a sensitive operation must ask for credentials again."""
        if session.reauthenticated_at is None:
            return True
        window = timedelta(minutes=self._policy.reauthentication_window_minutes)
        return session.reauthenticated_at + window <= moment

    # ------------------------------------------------------------------ #
    # Revocation                                                         #
    # ------------------------------------------------------------------ #

    async def revoke(
        self,
        repositories,  # noqa: ANN001
        session_id: str,
        *,
        reason: str,
        moment: datetime,
    ) -> None:
        await repositories.sessions.revoke(session_id, reason=reason, moment=moment)

    async def revoke_every_session(
        self,
        repositories,  # noqa: ANN001
        user_id: str,
        *,
        reason: str,
        moment: datetime,
        keep_session_id: str | None = None,
    ) -> int:
        return await repositories.sessions.revoke_all_for_user(
            user_id, reason=reason, moment=moment, keep_session_id=keep_session_id
        )


__all__ = ["ResolvedSession", "SessionService"]
