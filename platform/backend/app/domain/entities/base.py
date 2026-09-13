"""Entity conventions shared by the domain model.

Package 2 adds the concrete entities (users, organizations, projects, datasets,
analyses, ...). Only the conventions belong to Package 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects.identifiers import EntityId


def utc_now() -> datetime:
    """All domain timestamps are timezone-aware UTC."""
    return datetime.now(UTC)


@dataclass(kw_only=True)
class Entity:
    """An object with identity and a lifecycle timeline."""

    id: EntityId
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, type(self)) and other.id == self.id

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.id))
