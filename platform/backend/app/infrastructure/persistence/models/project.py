"""Project, project membership and collaboration persistence.

Project membership is a separate relationship from organization membership: a
project role is never derived from an organization role at the schema level.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    DeletionState,
    InvitationState,
    MembershipState,
    ProjectRole,
    ProjectState,
)
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


class Project(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    __tablename__ = "projects"
    __table_args__ = (
        # A project belongs to exactly one workspace (NOT NULL FK) and its
        # name is unique inside that workspace.
        UniqueConstraint("workspace_id", "name", name="uq_projects_workspace_id_name"),
        state_check("state", ProjectState, "state_valid"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        Index("ix_projects_workspace_id_state_deletion_state", "workspace_id", "state",
              "deletion_state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ProjectState.DRAFT.value
    )
    created_by: Mapped[str] = fk_column("app.users.id")
    #: Owner is accountable for the project and is distinct from its creator.
    owner_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    #: Active hierarchical configuration document for this project.
    configuration_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    configuration_version: Mapped[int | None] = mapped_column(nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class ProjectMembership(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_memberships_project_id_user_id"),
        state_check("role", ProjectRole, "role_valid"),
        state_check("state", MembershipState, "state_valid"),
        Index("ix_project_memberships_user_id_state", "user_id", "state"),
    )

    id: Mapped[str] = id_column()
    project_id: Mapped[str] = fk_column("app.projects.id")
    user_id: Mapped[str] = fk_column("app.users.id")
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=MembershipState.ACTIVE.value
    )
    granted_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectInvitation(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "project_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_project_invitations_token_hash"),
        state_check("role", ProjectRole, "role_valid"),
        state_check("state", InvitationState, "state_valid"),
        Index("ix_project_invitations_project_id_state", "project_id", "state"),
    )

    id: Mapped[str] = id_column()
    project_id: Mapped[str] = fk_column("app.projects.id", ondelete="CASCADE")
    invited_email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InvitationState.PENDING.value
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    invited_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResourceAssignment(Base, TimestampMixin, ConcurrencyMixin):
    """Assignment of a project resource (analysis, review, report) to a user."""

    __tablename__ = "resource_assignments"
    __table_args__ = (
        Index("ix_resource_assignments_assignee_state", "assignee_user_id", "state"),
        Index("ix_resource_assignments_resource", "resource_type", "resource_id"),
        state_check("state", MembershipState, "state_valid"),
    )

    id: Mapped[str] = id_column()
    project_id: Mapped[str] = fk_column("app.projects.id")
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assignee_user_id: Mapped[str] = fk_column("app.users.id")
    assigned_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=MembershipState.ACTIVE.value
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class DiscussionComment(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """Collaboration comment attached to any project-scoped resource."""

    __tablename__ = "discussion_comments"
    __table_args__ = (
        Index("ix_discussion_comments_resource", "resource_type", "resource_id"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
    )

    id: Mapped[str] = id_column()
    project_id: Mapped[str] = fk_column("app.projects.id")
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_comment_id: Mapped[str | None] = fk_column(
        "app.discussion_comments.id", nullable=True
    )
    author_user_id: Mapped[str] = fk_column("app.users.id")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
