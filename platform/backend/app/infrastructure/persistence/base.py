"""Declarative base, naming conventions and reusable column mixins.

Conventions established here and relied on by every model module:

* **Schemas.** ``app`` holds domain state; ``platform`` holds operational
  bookkeeping (audit trail, domain-event outbox, job/worker bookkeeping).
* **Identifiers.** Every primary key is an opaque, prefixed, application
  generated string (``prj_<32 hex>``) — never a client-supplied value and never
  a guessable sequence. See ``domain/value_objects/identifiers.py``.
* **Timestamps.** ``timestamptz`` only, defaulted by the database (``now()``)
  so that a clock skewed application node cannot write naive local time.
* **State fields.** Persisted as ``VARCHAR`` plus a ``CHECK`` constraint
  generated from the domain vocabulary (``state_enum``). Native PostgreSQL
  enums were deliberately not used: extending a vocabulary must not require
  a non-transactional ``ALTER TYPE`` in the middle of a migration chain.
* **Concurrency.** ``ConcurrencyMixin`` adds an integer ``version`` mapped as
  SQLAlchemy's ``version_id_col``, giving optimistic concurrency on mutable
  resources without pessimistic locking.
* **Retention.** ``RetentionMixin`` adds the soft-delete/retention lifecycle.
  Soft deletion never implies physical object-storage deletion.

These models are *persistence* models. They are not the domain model: domain
entities live in ``app/domain`` and repositories translate between the two.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.domain.value_objects.enums import DeletionState, StrEnum

DOMAIN_SCHEMA = "app"
OPERATIONAL_SCHEMA = "platform"

#: Deterministic constraint/index names, so migrations and drops are stable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

ID_LENGTH = 64
SHORT_TEXT = 255


class Base(DeclarativeBase):
    """Declarative base for all persistence models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION, schema=DOMAIN_SCHEMA)

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier!r}>"


def state_enum(vocabulary: type[StrEnum], constraint_name: str) -> String:
    """A state column type constrained to a domain vocabulary.

    Rendered as ``VARCHAR`` with a ``CHECK ... IN (...)`` constraint attached to
    the owning table, so an invalid state cannot enter the database.
    """
    return String(length=64)


def state_check(column: str, vocabulary: type[StrEnum], name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in vocabulary)
    return CheckConstraint(f"{column} IN ({values})", name=name)


def id_column(*, primary_key: bool = True) -> Mapped[str]:
    return mapped_column(String(ID_LENGTH), primary_key=primary_key)


def fk_column(
    target: str,
    *,
    nullable: bool = False,
    ondelete: str = "RESTRICT",
    index: bool = True,
) -> Mapped[Any]:
    """A foreign key to another prefixed-identifier primary key.

    ``ondelete`` defaults to ``RESTRICT``: dependency integrity is preserved and
    removal always goes through the retention/deletion lifecycle rather than a
    silent cascade that would destroy scientific lineage.
    """
    return mapped_column(
        String(ID_LENGTH),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


def json_column(*, nullable: bool = True) -> Mapped[Any]:
    """Structured metadata payload (``jsonb``).

    Used for genuinely open-ended metadata and for immutable configuration
    snapshots. Never used as a substitute for a modelled relationship, and never
    for large genomic payloads — those live in object storage / Parquet.
    """
    return mapped_column(JSONB, nullable=nullable)


class TimestampMixin:
    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        )


class ConcurrencyMixin:
    """Optimistic concurrency for mutable resources."""

    @declared_attr
    def version(cls) -> Mapped[int]:
        return mapped_column(Integer, nullable=False, server_default="1")

    @declared_attr
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.__table__.c.version}  # type: ignore[attr-defined]


class RetentionMixin:
    """Soft deletion, retention window and deletion holds."""

    @declared_attr
    def deletion_state(cls) -> Mapped[str]:
        return mapped_column(
            String(64), nullable=False, server_default=DeletionState.ACTIVE.value
        )

    @declared_attr
    def deleted_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def deleted_by(cls) -> Mapped[str | None]:
        return mapped_column(String(ID_LENGTH), nullable=True)

    @declared_attr
    def retention_expires_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def deletion_hold_reason(cls) -> Mapped[str | None]:
        return mapped_column(Text, nullable=True)

    @declared_attr
    def permanently_deleted_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(timezone=True), nullable=True)

    @classmethod
    def retention_constraints(cls, table_name: str) -> tuple[CheckConstraint, ...]:
        return (state_check("deletion_state", DeletionState, "deletion_state_valid"),)


__all__ = [
    "Base",
    "ConcurrencyMixin",
    "DOMAIN_SCHEMA",
    "ID_LENGTH",
    "OPERATIONAL_SCHEMA",
    "RetentionMixin",
    "SHORT_TEXT",
    "TimestampMixin",
    "fk_column",
    "id_column",
    "json_column",
    "state_check",
    "state_enum",
]
