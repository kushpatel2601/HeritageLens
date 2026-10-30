"""Alembic environment (async, PostgreSQL + pgvector).

The URL comes from `HL_DATABASE_URL` so migrations always target the same database as the app.
Custom column types are rendered as plain SQLAlchemy / pgvector types so revision files do not
import application code.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db import models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base, UTCDateTime, Vector

config = context.config
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# PostgreSQL stores expression indexes in normalised form (casts, parentheses), so autogenerate cannot compare
# them with the model definition and would report phantom drift. They are created explicitly in revisions.
EXPRESSION_INDEXES = frozenset({"ix_chunks_fts"})


def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    return not (type_ == "index" and name in EXPRESSION_INDEXES)


def _url() -> str:
    url = config.attributes.get("database_url") or get_settings().database_url
    if url.startswith("sqlite"):
        raise SystemExit("Alembic migrations target PostgreSQL; the SQLite quick-start uses `heritagelens migrate`.")
    return url


def render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    if type_ == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("import pgvector.sqlalchemy")
        return f"pgvector.sqlalchemy.Vector({obj.dim})"
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def _configure(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        render_item=render_item,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
