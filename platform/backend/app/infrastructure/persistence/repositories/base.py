"""Shared repository helpers: identifiers, version-checked updates, paging."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, Table, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ConcurrencyConflictError


def new_id(prefix: str) -> str:
    """Opaque, prefixed, application-generated identifier (never client supplied)."""
    return f"{prefix}_{uuid.uuid4().hex}"


class SqlRepository:
    """Base for Core-statement repositories bound to one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _fetch_one(self, statement: Select) -> Mapping[str, Any] | None:
        result = await self._session.execute(statement)
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def _fetch_all(self, statement: Select) -> list[Mapping[str, Any]]:
        result = await self._session.execute(statement)
        return [dict(row) for row in result.mappings().all()]

    async def _count(self, statement: Select) -> int:
        subquery = statement.order_by(None).subquery()
        total = await self._session.scalar(select(func.count()).select_from(subquery))
        return int(total or 0)

    async def _versioned_update(
        self,
        table: Table,
        *,
        entity_id: str,
        expected_version: int,
        values: dict[str, Any],
    ) -> int:
        """Apply an update only if nobody changed the row since it was read."""
        statement = (
            update(table)
            .where(table.c.id == entity_id, table.c.version == expected_version)
            .values(**values, version=expected_version + 1)
        )
        result = await self._session.execute(statement)
        if result.rowcount == 0:
            raise ConcurrencyConflictError(
                "the resource changed since it was read; re-read and retry",
                details={"resource_id": entity_id},
            )
        return expected_version + 1


__all__ = ["SqlRepository", "new_id"]
