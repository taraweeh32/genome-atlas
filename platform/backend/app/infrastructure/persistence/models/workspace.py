"""Workspace persistence — the tenancy boundary.

A workspace is either *personal* (owned by exactly one user, no organization) or
an *organization* workspace. The XOR is enforced by a database check constraint,
not by frontend or service-layer convention alone.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import DeletionState, WorkspaceKind
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    RetentionMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class Workspace(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    __tablename__ = "workspaces"
    __table_args__ = (
        state_check("kind", WorkspaceKind, "kind_valid"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        CheckConstraint(
            "(kind = 'personal' AND organization_id IS NULL AND owner_user_id IS NOT NULL)"
            " OR (kind = 'organization' AND organization_id IS NOT NULL)",
            name="ck_workspaces_scope_exclusive",
        ),
        # One personal workspace per user; one workspace per organization.
        Index(
            "uq_workspaces_personal_owner",
            "owner_user_id",
            unique=True,
            postgresql_where=text("kind = 'personal'"),
        ),
        UniqueConstraint("organization_id", name="uq_workspaces_organization_id"),
    )

    id: Mapped[str] = id_column()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: Explicit ownership. For an organization workspace the owner is the
    #: accountable user; ``created_by`` records who created it (they differ).
    owner_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    organization_id: Mapped[str | None] = fk_column("app.organizations.id", nullable=True)
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    metadata_json: Mapped[dict | None] = json_column()
