"""健康检查路由 GET /api/health。

检测 Backend / PostgreSQL / Qdrant / Embedding / Reranker / Bailian。
每个服务独立检测，单点失败不影响整体响应。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import text

from app.api import ok
from app.api.deps import DBSession
from app.core.config import get_settings
from app.core.logging import logger

router = APIRouter(prefix="/health", tags=["health"])

settings = get_settings()


async def _check_database(session: DBSession) -> str:
    try:
        await session.execute(text("SELECT 1"))
        return "healthy"
    except Exception as exc:  # noqa: BLE001
        logger.debug("DB health check failed: {}", exc)
        return "unhealthy"


async def _check_qdrant() -> str:
    try:
        from qdrant_client import AsyncQdrantClient

        client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
        await client.get_collections()
        await client.close()
        return "healthy"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Qdrant health check failed: {}", exc)
        return "unavailable"


async def _check_embedding() -> str:
    try:
        # 延迟导入，避免未安装本地模型时整包失败
        from app.rag.embedding import get_embedding_service

        svc = get_embedding_service()
        await svc.embed_query("health")
        return "healthy"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Embedding health check failed: {}", exc)
        return "unavailable"


async def _check_reranker() -> str:
    try:
        from app.rag.reranker import get_reranker

        r = get_reranker()
        await r.rerank("health", ["health check doc"])
        return "healthy"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Reranker health check failed: {}", exc)
        return "unavailable"


async def _check_bailian() -> str:
    try:
        from app.llm import get_gateway

        gw = get_gateway()
        report = await gw.health()
        if report.get("available"):
            return "mock" if report.get("use_mock") else "healthy"
        return "unavailable"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Bailian health check failed: {}", exc)
        return "unavailable"


@router.get("", summary="健康检查")
async def health(session: DBSession) -> dict[str, Any]:
    services = {
        "backend": "healthy",
        "database": await _check_database(session),
        "qdrant": await _check_qdrant(),
        "embedding": await _check_embedding(),
        "reranker": await _check_reranker(),
        "bailian": await _check_bailian(),
    }
    overall = "healthy" if all(
        v in ("healthy", "mock") for v in services.values()
    ) else "degraded"
    return ok({"status": overall, "services": services})


@router.get("/live", summary="存活探针", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, Any]:
    return ok({"status": "alive"})
