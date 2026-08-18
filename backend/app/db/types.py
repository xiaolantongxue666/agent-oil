"""跨方言 JSON 类型：PostgreSQL 上使用 JSONB，其他方言（如 SQLite）回退通用 JSON。

使数据层在无 Docker/PG 时可降级到 SQLite 进行开发与单元测试，
生产环境仍以 PostgreSQL + JSONB 为目标。
"""

from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator, TypeEngine


class JSONBType(TypeDecorator):
    """PG → JSONB；其他方言 → 通用 JSON。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect) -> TypeEngine:  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


__all__ = ["JSONBType"]
