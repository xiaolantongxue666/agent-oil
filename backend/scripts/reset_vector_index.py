"""向量索引清洗脚本：清除 Mock 假向量污染并强制全量重建。

背景：
- 历史 Embedding 批量失败曾被静默回退为 Mock 哈希向量，并随索引管线
  以 vector_embedded=True 持久化，导致检索质量劣化且难以察觉。
- 该回退已移除（Embedding API 失败会直接抛错），本脚本用于一次性清洗存量数据。

用法（在 backend/ 目录，或后端容器内）：
    python -m scripts.reset_vector_index            # 清空 Qdrant 集合 + 重置全部索引标记
    python -m scripts.reset_vector_index --dry-run  # 仅统计，不执行任何写入/删除

执行后：
- Qdrant 集合被整体删除（下次检索时按当前向量维度自动重建）；
- knowledge_chunks / knowledge_items 的 vector_embedded 全部重置为 False，
  下一次检索或知识库操作会以修复后的 Embedding 重新索引。
- 运行中的后端进程持有“已同步”内存标记，需重启后端容器后生效：
    docker compose restart backend
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

# 允许直接 python scripts/reset_vector_index.py 运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, update  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.logging import logger  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.knowledge import KnowledgeChunk, KnowledgeItem  # noqa: E402


async def _counts(session: Any) -> tuple[int, int, int, int]:
    chunk_total = await session.scalar(select(func.count()).select_from(KnowledgeChunk)) or 0
    chunk_embedded = (
        await session.scalar(
            select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.vector_embedded.is_(True))
        )
        or 0
    )
    item_total = await session.scalar(select(func.count()).select_from(KnowledgeItem)) or 0
    item_embedded = (
        await session.scalar(
            select(func.count()).select_from(KnowledgeItem).where(KnowledgeItem.vector_embedded.is_(True))
        )
        or 0
    )
    return chunk_total, chunk_embedded, item_total, item_embedded


async def _reset_db(session: Any) -> None:
    await session.execute(update(KnowledgeChunk).values(vector_embedded=False, qdrant_point_id=None))
    await session.execute(update(KnowledgeItem).values(vector_embedded=False, qdrant_point_id=None))
    await session.commit()


async def main() -> int:
    parser = argparse.ArgumentParser(description="重置向量索引：清空 Qdrant 集合并重置索引标记")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不执行任何写入/删除")
    parser.add_argument("--keep-collection", action="store_true", help="仅重置 DB 标记，不删除 Qdrant 集合")
    args = parser.parse_args()

    settings = get_settings()
    async with AsyncSessionLocal() as session:
        chunk_total, chunk_embedded, item_total, item_embedded = await _counts(session)
        logger.info(
            "当前状态：knowledge_chunks {} 条（已向量化 {}），knowledge_items {} 条（已向量化 {}）",
            chunk_total,
            chunk_embedded,
            item_total,
            item_embedded,
        )
        if args.dry_run:
            logger.info("dry-run：未做任何更改")
            return 0

        logger.info("重置 DB 索引标记：knowledge_chunks / knowledge_items → vector_embedded=False")
        await _reset_db(session)

    if not args.keep_collection:
        from app.rag.store import QdrantStore

        store = QdrantStore()
        if await store.health():
            logger.info("删除 Qdrant 集合 {}（假向量随集合一并清除）", settings.qdrant_collection)
            await store.delete_collection()
        else:
            logger.warning("Qdrant 不可达，跳过集合删除；DB 标记已重置")

    logger.info("完成。请重启后端使内存同步标记失效：docker compose restart backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
