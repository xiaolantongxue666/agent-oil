"""SQLAlchemy 2.x 声明式 Base 与异步引擎/会话。

正式启动使用 Alembic 迁移，禁止依赖 Base.metadata.create_all() 取代 migration。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.app_debug and _settings.app_env == "development",
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：提供数据库会话，请求结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


__all__ = ["Base", "engine", "AsyncSessionLocal", "get_db"]
