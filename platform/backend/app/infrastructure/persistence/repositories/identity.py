"""Identity repositories: accounts, credentials, sessions, tokens, platform roles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import and_, insert, select, update

from app.application.repositories import Page, Paged
from app.domain.identity.entities import (
    Credentials,
    CredentialToken,
    Session,
    UserAccount,
)
from app.domain.value_objects.enums import (
    AccountState,
    CredentialTokenKind,
    CredentialTokenState,
    DeletionState,
    EmailVerificationState,
    PlatformRole,
    SessionState,
)
from app.infrastructure.persistence.models.identity import (
    PlatformRoleAssignment,
    User,
    UserAuthenticationMetadata,
)
from app.infrastructure.persistence.models.session import (
    UserCredentialToken,
    UserSession,
)
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_USERS = User.__table__
_CREDENTIALS = UserAuthenticationMetadata.__table__
_SESSIONS = UserSession.__table__
_TOKENS = UserCredentialToken.__table__
_PLATFORM_ROLES = PlatformRoleAssignment.__table__


def to_account(row: Mapping[str, Any]) -> UserAccount:
    return UserAccount(
        id=row["id"],
        email=row["email"],
        email_normalized=row["email_normalized"],
        display_name=row["display_name"],
        account_state=AccountState(row["account_state"]),
        email_verification_state=EmailVerificationState(row["email_verification_state"]),
        deletion_state=DeletionState(row["deletion_state"]),
        personal_workspace_id=row["personal_workspace_id"],
        email_verified_at=row["email_verified_at"],
        suspended_at=row["suspended_at"],
        suspension_reason=row["suspension_reason"],
        deactivated_at=row["deactivated_at"],
        last_activity_at=row["last_activity_at"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqlUserRepository(SqlRepository):
    async def get(self, user_id: str) -> UserAccount | None:
        row = await self._fetch_one(select(_USERS).where(_USERS.c.id == user_id))
        return to_account(row) if row else None

    async def get_by_email(self, email_normalized: str) -> UserAccount | None:
        row = await self._fetch_one(
            select(_USERS).where(_USERS.c.email_normalized == email_normalized)
        )
        return to_account(row) if row else None

    async def add(self, account: UserAccount) -> UserAccount:
        await self._session.execute(
            insert(_USERS).values(
                id=account.id,
                email=account.email,
                email_normalized=account.email_normalized,
                display_name=account.display_name,
                account_state=account.account_state.value,
                email_verification_state=account.email_verification_state.value,
                deletion_state=account.deletion_state.value,
                personal_workspace_id=account.personal_workspace_id,
                version=1,
            )
        )
        stored = await self.get(account.id)
        assert stored is not None
        return stored

    async def save(self, account: UserAccount) -> UserAccount:
        version = await self._versioned_update(
            _USERS,
            entity_id=account.id,
            expected_version=account.version,
            values={
                "display_name": account.display_name,
                "account_state": account.account_state.value,
                "email_verification_state": account.email_verification_state.value,
                "deletion_state": account.deletion_state.value,
                "email_verified_at": account.email_verified_at,
                "suspended_at": account.suspended_at,
                "suspension_reason": account.suspension_reason,
                "deactivated_at": account.deactivated_at,
                "personal_workspace_id": account.personal_workspace_id,
            },
        )
        return replace(account, version=version)

    async def set_personal_workspace(self, user_id: str, workspace_id: str) -> None:
        await self._session.execute(
            update(_USERS).where(_USERS.c.id == user_id).values(personal_workspace_id=workspace_id)
        )

    async def touch_activity(self, user_id: str, moment: datetime) -> None:
        # Activity tracking must not fight optimistic concurrency: it is not a
        # business state change, so it does not bump the version.
        await self._session.execute(
            update(_USERS).where(_USERS.c.id == user_id).values(last_activity_at=moment)
        )

    async def list_accounts(self, *, page: Page, query: str | None = None) -> Paged[UserAccount]:
        statement = select(_USERS).order_by(_USERS.c.created_at.desc())
        if query:
            pattern = f"%{query.strip().casefold()}%"
            statement = statement.where(_USERS.c.email_normalized.like(pattern))
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_account(row) for row in rows), total, page)


class SqlCredentialsRepository(SqlRepository):
    @staticmethod
    def _to_entity(row: Mapping[str, Any]) -> Credentials:
        return Credentials(
            user_id=row["user_id"],
            password_hash=row["password_hash"],
            password_algorithm=row["password_algorithm"],
            password_updated_at=row["password_updated_at"],
            mfa_enabled=bool(row["mfa_enabled"]),
            mfa_enrolled_at=row["mfa_enrolled_at"],
            failed_attempt_count=row["failed_attempt_count"],
            locked_until=row["locked_until"],
            last_successful_authentication_at=row["last_successful_authentication_at"],
            version=row["version"],
        )

    async def get(self, user_id: str) -> Credentials | None:
        row = await self._fetch_one(
            select(_CREDENTIALS).where(_CREDENTIALS.c.user_id == user_id)
        )
        return self._to_entity(row) if row else None

    async def create(self, credentials: Credentials) -> Credentials:
        await self._session.execute(
            insert(_CREDENTIALS).values(
                id=new_id("uam"),
                user_id=credentials.user_id,
                password_hash=credentials.password_hash,
                password_algorithm=credentials.password_algorithm,
                password_updated_at=credentials.password_updated_at,
                mfa_enabled=credentials.mfa_enabled,
                failed_attempt_count=0,
                version=1,
            )
        )
        stored = await self.get(credentials.user_id)
        assert stored is not None
        return stored

    async def replace_password(
        self, user_id: str, *, password_hash: str, algorithm: str, moment: datetime
    ) -> None:
        await self._session.execute(
            update(_CREDENTIALS)
            .where(_CREDENTIALS.c.user_id == user_id)
            .values(
                password_hash=password_hash,
                password_algorithm=algorithm,
                password_updated_at=moment,
                # A successful credential change clears the lockout counters.
                failed_attempt_count=0,
                locked_until=None,
            )
        )

    async def register_failure(
        self, user_id: str, *, moment: datetime, lock_until: datetime | None
    ) -> int:
        await self._session.execute(
            update(_CREDENTIALS)
            .where(_CREDENTIALS.c.user_id == user_id)
            .values(
                failed_attempt_count=_CREDENTIALS.c.failed_attempt_count + 1,
                locked_until=lock_until,
            )
        )
        count = await self._session.scalar(
            select(_CREDENTIALS.c.failed_attempt_count).where(_CREDENTIALS.c.user_id == user_id)
        )
        return int(count or 0)

    async def register_success(self, user_id: str, *, moment: datetime) -> None:
        await self._session.execute(
            update(_CREDENTIALS)
            .where(_CREDENTIALS.c.user_id == user_id)
            .values(
                failed_attempt_count=0,
                locked_until=None,
                last_successful_authentication_at=moment,
            )
        )


class SqlSessionRepository(SqlRepository):
    @staticmethod
    def _to_entity(row: Mapping[str, Any]) -> Session:
        return Session(
            id=row["id"],
            user_id=row["user_id"],
            state=SessionState(row["state"]),
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            absolute_expires_at=row["absolute_expires_at"],
            last_seen_at=row["last_seen_at"],
            revoked_at=row["revoked_at"],
            revocation_reason=row["revocation_reason"],
            mfa_satisfied=bool(row["mfa_satisfied"]),
            reauthenticated_at=row["reauthenticated_at"],
            ip_hash=row["ip_hash"],
            user_agent_summary=row["user_agent_summary"],
            csrf_token_hash=row["csrf_token_hash"],
        )

    async def create(self, session: Session, *, token_hash: str) -> Session:
        await self._session.execute(
            insert(_SESSIONS).values(
                id=session.id,
                user_id=session.user_id,
                token_hash=token_hash,
                csrf_token_hash=session.csrf_token_hash,
                state=session.state.value,
                issued_at=session.issued_at,
                expires_at=session.expires_at,
                absolute_expires_at=session.absolute_expires_at,
                last_seen_at=session.last_seen_at,
                mfa_satisfied=session.mfa_satisfied,
                reauthenticated_at=session.reauthenticated_at,
                ip_hash=session.ip_hash,
                user_agent_summary=session.user_agent_summary,
                version=1,
            )
        )
        return session

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        # Lookup is by hash: the raw token is never stored and never compared.
        row = await self._fetch_one(select(_SESSIONS).where(_SESSIONS.c.token_hash == token_hash))
        return self._to_entity(row) if row else None

    async def touch(
        self, session_id: str, *, last_seen_at: datetime, expires_at: datetime
    ) -> None:
        await self._session.execute(
            update(_SESSIONS)
            .where(_SESSIONS.c.id == session_id, _SESSIONS.c.state == SessionState.ACTIVE.value)
            .values(last_seen_at=last_seen_at, expires_at=expires_at)
        )

    async def revoke(self, session_id: str, *, reason: str, moment: datetime) -> None:
        await self._session.execute(
            update(_SESSIONS)
            .where(_SESSIONS.c.id == session_id)
            .values(
                state=SessionState.REVOKED.value,
                revoked_at=moment,
                revocation_reason=reason,
            )
        )

    async def revoke_all_for_user(
        self, user_id: str, *, reason: str, moment: datetime, keep_session_id: str | None = None
    ) -> int:
        conditions = [
            _SESSIONS.c.user_id == user_id,
            _SESSIONS.c.state == SessionState.ACTIVE.value,
        ]
        if keep_session_id:
            conditions.append(_SESSIONS.c.id != keep_session_id)
        result = await self._session.execute(
            update(_SESSIONS)
            .where(and_(*conditions))
            .values(
                state=SessionState.REVOKED.value,
                revoked_at=moment,
                revocation_reason=reason,
            )
        )
        return int(result.rowcount or 0)

    async def list_active_for_user(self, user_id: str) -> tuple[Session, ...]:
        rows = await self._fetch_all(
            select(_SESSIONS)
            .where(
                _SESSIONS.c.user_id == user_id,
                _SESSIONS.c.state == SessionState.ACTIVE.value,
            )
            .order_by(_SESSIONS.c.issued_at.asc())
        )
        return tuple(self._to_entity(row) for row in rows)


class SqlCredentialTokenRepository(SqlRepository):
    @staticmethod
    def _to_entity(row: Mapping[str, Any]) -> CredentialToken:
        return CredentialToken(
            id=row["id"],
            user_id=row["user_id"],
            kind=CredentialTokenKind(row["kind"]),
            state=CredentialTokenState(row["state"]),
            expires_at=row["expires_at"],
            consumed_at=row["consumed_at"],
            created_at=row["created_at"],
        )

    async def create(self, token: CredentialToken, *, token_hash: str) -> CredentialToken:
        await self._session.execute(
            insert(_TOKENS).values(
                id=token.id,
                user_id=token.user_id,
                kind=token.kind.value,
                state=token.state.value,
                token_hash=token_hash,
                expires_at=token.expires_at,
                version=1,
            )
        )
        return token

    async def get_by_token_hash(self, token_hash: str) -> CredentialToken | None:
        row = await self._fetch_one(select(_TOKENS).where(_TOKENS.c.token_hash == token_hash))
        if row is None:
            return None
        await self._session.execute(
            update(_TOKENS)
            .where(_TOKENS.c.id == row["id"])
            .values(presentation_count=_TOKENS.c.presentation_count + 1)
        )
        return self._to_entity(row)

    async def consume(self, token_id: str, *, moment: datetime) -> None:
        await self._session.execute(
            update(_TOKENS)
            .where(
                _TOKENS.c.id == token_id,
                _TOKENS.c.state == CredentialTokenState.ACTIVE.value,
            )
            .values(state=CredentialTokenState.CONSUMED.value, consumed_at=moment)
        )

    async def invalidate_active(
        self, user_id: str, kind: CredentialTokenKind, *, reason: str, moment: datetime
    ) -> int:
        """Issuing a new token invalidates the previous ones of the same kind."""
        result = await self._session.execute(
            update(_TOKENS)
            .where(
                _TOKENS.c.user_id == user_id,
                _TOKENS.c.kind == kind.value,
                _TOKENS.c.state == CredentialTokenState.ACTIVE.value,
            )
            .values(
                state=CredentialTokenState.INVALIDATED.value,
                invalidated_at=moment,
                invalidation_reason=reason,
            )
        )
        return int(result.rowcount or 0)


class SqlPlatformRoleRepository(SqlRepository):
    async def list_active_for_user(self, user_id: str) -> frozenset[PlatformRole]:
        rows = await self._fetch_all(
            select(_PLATFORM_ROLES).where(
                _PLATFORM_ROLES.c.user_id == user_id,
                _PLATFORM_ROLES.c.revoked_at.is_(None),
            )
        )
        return frozenset(PlatformRole(row["role"]) for row in rows)

    async def grant(
        self, user_id: str, role: PlatformRole, *, granted_by: str, moment: datetime
    ) -> None:
        existing = await self._fetch_one(
            select(_PLATFORM_ROLES).where(
                _PLATFORM_ROLES.c.user_id == user_id,
                _PLATFORM_ROLES.c.role == role.value,
            )
        )
        if existing is None:
            await self._session.execute(
                insert(_PLATFORM_ROLES).values(
                    id=new_id("pra"),
                    user_id=user_id,
                    role=role.value,
                    granted_by=granted_by,
                    granted_at=moment,
                )
            )
            return
        await self._session.execute(
            update(_PLATFORM_ROLES)
            .where(_PLATFORM_ROLES.c.id == existing["id"])
            .values(revoked_at=None, granted_by=granted_by, granted_at=moment)
        )

    async def revoke(self, user_id: str, role: PlatformRole, *, moment: datetime) -> None:
        await self._session.execute(
            update(_PLATFORM_ROLES)
            .where(
                _PLATFORM_ROLES.c.user_id == user_id,
                _PLATFORM_ROLES.c.role == role.value,
                _PLATFORM_ROLES.c.revoked_at.is_(None),
            )
            .values(revoked_at=moment)
        )


__all__ = [
    "SqlCredentialTokenRepository",
    "SqlCredentialsRepository",
    "SqlPlatformRoleRepository",
    "SqlSessionRepository",
    "SqlUserRepository",
    "to_account",
]
