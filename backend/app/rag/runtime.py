"""RAG 模型服务（向量 / 重排）运行时配置加载与单例重置。"""

from __future__ import annotations

from app.core.logging import logger
from app.rag.embedding import apply_runtime_overrides as apply_embedding
from app.rag.embedding import reset_embedding_service
from app.rag.reranker import apply_runtime_overrides as apply_reranker
from app.rag.reranker import reset_reranker

_SERVICE_CATEGORIES = ("embedding", "reranker")


async def refresh_runtime_rag_config(session) -> dict[str, int]:
    """从 system_settings 读取向量/重排配置到模块级内存覆盖。

    由应用启动 lifespan 与管理员保存配置时调用；失败时保留 env 默认。
    """

    from sqlalchemy import select

    from app.models.admin import SystemSetting

    loaded: dict[str, int] = {}
    try:
        for category in _SERVICE_CATEGORIES:
            rows = (
                await session.scalars(
                    select(SystemSetting).where(SystemSetting.category == category)
                )
            ).all()
            values = {row.key: row.value for row in rows if row.value != ""}
            if category == "embedding":
                apply_embedding(values)
            else:
                apply_reranker(values)
            loaded[category] = len(values)
        if any(loaded.values()):
            reset_embedding_service()
            reset_reranker()
        logger.info("RAG 运行时配置已加载：{}", loaded)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG 运行时配置加载失败，回退环境变量：{}", exc)
    return loaded


__all__ = ["refresh_runtime_rag_config"]
