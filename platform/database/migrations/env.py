"""Alembic environment.

The database URL is read from EnvironmentSettings at runtime; it is never stored
in alembic.ini so no connection string or credential is ever committed.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.environment import get_environment_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_environment_settings().database.url)

# Importing the model package registers every table on Base.metadata, which is
# what autogenerate compares the live database against.
from app.infrastructure.persistence.models import Base  # noqa: E402

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    """Restrict autogenerate to the schemas this application owns."""
    if type_ == "table":
        return (obj.schema or "app") in {"app", "platform"}
    return True


_CONFIGURE_OPTIONS = {
    "target_metadata": target_metadata,
    "include_schemas": True,
    "include_object": _include_object,
    "compare_type": True,
    "compare_server_default": True,
    "version_table_schema": "platform",
}


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_CONFIGURE_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, **_CONFIGURE_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
