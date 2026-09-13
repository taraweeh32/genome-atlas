"""PostgreSQL connection lifecycle and transaction foundation.

PostgreSQL is the authoritative transactional database. Package 1 establishes
connectivity, pooling, health integration and the unit-of-work boundary only —
the domain schema arrives in Package 2.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.environment import DatabaseSettings
from app.core.logging import get_logger
from app.domain.errors import InfrastructureError

logger = get_logger(__name__)


class Database:
    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        if self._engine is not None:
            return
        self._engine = create_async_engine(
            self._settings.url,
            pool_size=self._settings.pool_max_size,
            pool_pre_ping=True,
            connect_args={
                "server_settings": {
                    "statement_timeout": str(self._settings.statement_timeout_ms),
                },
            },
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        logger.info("database engine created")

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("database engine disposed")

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[AsyncSession]:
        """Transaction boundary. Commits on success, rolls back on any error."""
        if self._session_factory is None:
            raise InfrastructureError("database is not connected")
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> None:
        if self._engine is None:
            raise InfrastructureError("database is not connected")
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
