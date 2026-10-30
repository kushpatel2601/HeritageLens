from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def build_engine(settings: Settings) -> AsyncEngine:
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "pool_pre_ping": True}
    if settings.is_sqlite:
        path = settings.database_url.split("///", 1)[-1]
        if path and path != ":memory:":
            from pathlib import Path

            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"timeout": 30}
    else:
        kwargs.update(pool_size=10, max_overflow=20)
    engine = create_async_engine(settings.database_url, **kwargs)
    if settings.is_sqlite:
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
    return engine


class Database:
    """Owns the engine + session factory; one instance per process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.engine = build_engine(self.settings)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as s:
            yield s

    async def create_all(self) -> None:
        """Used by tests and the SQLite quick-start. Production uses Alembic migrations."""
        from app.db import models  # noqa: F401  (register models)
        from app.db.base import Base

        async with self.engine.begin() as conn:
            if self.dialect == "postgresql":
                from sqlalchemy import text

                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
