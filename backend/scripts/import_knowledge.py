"""知识库导入脚本（第三十二节）。

用法（在 backend/ 目录下）：
    .venv/Scripts/python.exe -m scripts.import_knowledge            # 导入 data/knowledge
    .venv/Scripts/python.exe -m scripts.import_knowledge --dir ../data/textbooks --source-type textbook
    .venv/Scripts/python.exe -m scripts.import_knowledge --reindex  # 仅对已入库条目重建向量索引

说明：
- 解析 → 清洗 → 入库 KnowledgeItem → 分块 → Embedding → Qdrant（或内存兜底）
- 所有资料统一标注"教学模拟/脱敏"，不编造标准条文
- 无 API Key / 无本地模型时使用 Mock，链路仍完整可运行
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# 允许直接 python scripts/import_knowledge.py 运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import logger  # noqa: E402
from app.db.session import AsyncSessionLocal, Base  # noqa: E402
from app.models.knowledge import KnowledgeItem  # noqa: E402
from app.rag.parser import parse_document  # noqa: E402
from app.rag.pipeline import get_pipeline, reset_pipeline  # noqa: E402

from sqlalchemy import select  # noqa: E402


SUPPORTED_EXT = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def _parse_filename(fn: str) -> tuple[str, str]:
    """从 'K-INSPECT-01_标题.md' 解析 (knowledge_id, title)。"""
    stem = Path(fn).stem
    if "_" in stem:
        kid, title = stem.split("_", 1)
        return kid.strip(), title.strip()
    return stem, stem


def _scan(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    files = []
    for p in directory.iterdir():
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
            files.append(p)
    return sorted(files)


async def _import_file(
    session: Any,
    pipeline: Any,
    path: Path,
    *,
    source_type: str,
) -> KnowledgeItem | None:
    kid, title = _parse_filename(path.name)
    parsed = parse_document(path)
    if parsed.error:
        logger.error("解析失败 {}: {}", path.name, parsed.error)
        return None
    if not parsed.text:
        logger.warning("空文本：{}", path.name)
        return None
    # upsert
    stmt = select(KnowledgeItem).where(KnowledgeItem.knowledge_id == kid)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        item = KnowledgeItem(knowledge_id=kid)
        session.add(item)
    item.title = title
    item.content = parsed.text
    item.source_type = source_type
    item.source_name = path.name
    item.major = "油气储运工程"
    item.position = "油气管道站场运行岗位"
    item.safety_level = "教学模拟"
    item.tags = ["教学模拟", "脱敏"]
    item.vector_embedded = False
    await session.flush()
    logger.info("入库：{} ({}, {} 字符)", kid, title, len(parsed.text))
    return item


async def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="知识库导入")
    parser.add_argument("--dir", default=None, help="导入目录（默认 data/knowledge）")
    parser.add_argument("--source-type", default="knowledge", help="来源类型")
    parser.add_argument("--reindex", action="store_true", help="仅重建向量索引（不入库新文件）")
    parsed_args = parser.parse_args(args)

    settings = get_settings()
    project_root = Path(__file__).resolve().parent.parent.parent
    directory = Path(parsed_args.dir) if parsed_args.dir else project_root / "data" / "knowledge"

    # 建表（开发兜底；生产用 alembic）
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    reset_pipeline()
    pipeline = get_pipeline()

    async with AsyncSessionLocal() as session:
        if parsed_args.reindex:
            items = (await session.execute(select(KnowledgeItem))).scalars().all()
            logger.info("重建索引：{} 条已入库知识", len(items))
        else:
            files = _scan(directory)
            if not files:
                logger.warning("目录无可用文件：{}", directory)
                return 0
            logger.info("扫描到 {} 个文件：{}", len(files), directory)
            items: list[KnowledgeItem] = []
            for f in files:
                item = await _import_file(
                    session, pipeline, f, source_type=parsed_args.source_type
                )
                if item:
                    items.append(item)
            await session.commit()
        # 索引
        if items:
            n = await pipeline.index_knowledge(items)
            await session.commit()  # 持久化 vector_embedded 标记
            logger.info("向量索引完成：{} 个点", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
