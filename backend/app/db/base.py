from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import JSON, DateTime, LargeBinary, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, TypeEngine

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetimes on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Vector(TypeDecorator[np.ndarray]):
    """Embedding column: native `pgvector` on PostgreSQL (HNSW-indexable), float32 blob on SQLite."""

    impl = LargeBinary
    cache_ok = True

    def __init__(self, dim: int) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector as PgVector

            return dialect.type_descriptor(PgVector(self.dim))
        return dialect.type_descriptor(LargeBinary())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        arr = np.asarray(value, dtype=np.float32).reshape(-1)
        if arr.shape[0] != self.dim:
            raise ValueError(f"expected vector of dim {self.dim}, got {arr.shape[0]}")
        if dialect.name == "postgresql":
            return arr.tolist()
        return arr.tobytes()

    def process_result_value(self, value: Any, dialect: Dialect) -> np.ndarray | None:
        if value is None:
            return None
        if isinstance(value, bytes | bytearray | memoryview):
            return np.frombuffer(bytes(value), dtype=np.float32)
        return np.asarray(value, dtype=np.float32)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False, index=True
    )
