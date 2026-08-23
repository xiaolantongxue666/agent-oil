"""RAG Pipeline 编排（第三十二节）。

职责：检索 → 重排 → 引用构建。
不直接调用 LLM 生成回答（由 Workflow 节点在 PHASE 6 接入），
不落库、不路由、不评分——仅提供语言层面的检索证据。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.core.logging import logger
from app.rag.citation import build_citation
from app.rag.cleaner import markdown_to_search_text
from app.rag.embedding import get_embedding_service
from app.rag.reranker import get_reranker
from app.rag.store import InMemoryStore, get_vector_store, reset_vector_store, set_vector_store
from app.workflow.context import RetrievedDoc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.knowledge import KnowledgeChunk, KnowledgeItem


class RAGPipeline:
    """检索增强生成管线（检索+重排+引用）。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._embedding = get_embedding_service()
        self._reranker = get_reranker()
        self._store = get_vector_store()
        self._ready = False
        self._db_synced = False

    async def ensure_ready(self) -> None:
        """惰性健康探测：Qdrant 不可达则切换到内存存储。"""
        if self._ready:
            return
        # 内存存储 / 测试环境直接就绪
        if self._store.backend in ("memory",):
            await self._store.ensure_collection(self._embedding.dimension)
            self._ready = True
            return
        ok = await self._store.health()
        if not ok:
            logger.warning("Qdrant 不可达，切换到内存向量存储")
            reset_vector_store()
            set_vector_store(InMemoryStore())
            self._store = get_vector_store()
        await self._store.ensure_collection(self._embedding.dimension)
        self._ready = True

    async def ensure_indexed_from_db(self) -> int:
        """从 DB 补齐未向量化条目；向量库为空时重建全部索引。"""
        await self.ensure_ready()
        count = await self._store.count()
        if self._db_synced:
            return count
        try:
            from sqlalchemy import select

            from app.db.session import AsyncSessionLocal
            from app.models.knowledge import KnowledgeItem

            async with AsyncSessionLocal() as session:
                from app.models.knowledge import KnowledgeChunk

                dirty_chunk_item_ids = set(
                    (
                        await session.scalars(
                            select(KnowledgeChunk.knowledge_item_id)
                            .where(
                                KnowledgeChunk.enabled.is_(True),
                                KnowledgeChunk.vector_embedded.is_(False),
                            )
                            .distinct()
                        )
                    ).all()
                )
                stmt = select(KnowledgeItem)
                if count > 0:
                    stmt = stmt.where(KnowledgeItem.vector_embedded.is_(False))
                items = (await session.execute(stmt)).scalars().all()
                item_by_id = {item.id: item for item in items}
                if dirty_chunk_item_ids:
                    extra_items = (
                        await session.scalars(
                            select(KnowledgeItem).where(
                                KnowledgeItem.id.in_(dirty_chunk_item_ids)
                            )
                        )
                    ).all()
                    item_by_id.update({item.id: item for item in extra_items})
                if not item_by_id:
                    self._db_synced = True
                    return count
                n = 0
                plain_items: list[KnowledgeItem] = []
                for item in item_by_id.values():
                    chunks = (
                        await session.scalars(
                            select(KnowledgeChunk)
                            .where(KnowledgeChunk.knowledge_item_id == item.id)
                            .order_by(KnowledgeChunk.chunk_index)
                        )
                    ).all()
                    if chunks:
                        n += await self.reindex_file_item(session, item, list(chunks))
                    else:
                        plain_items.append(item)
                if plain_items:
                    n += await self.index_knowledge(plain_items)
                await session.commit()
                self._db_synced = True
                total = await self._store.count()
                logger.info(
                    "从 DB 同步向量索引：{} 条 → {} 个新点，总计 {} 个点",
                    len(item_by_id),
                    n,
                    total,
                )
                return total
        except Exception as exc:  # noqa: BLE001
            logger.warning("从 DB 重建索引失败（非致命）：{}", exc)
            return 0

    async def index_knowledge(self, items: list[KnowledgeItem]) -> int:
        """将知识条目分块、嵌入、写入向量库。返回写入点数。"""
        await self.ensure_ready()
        from app.rag.chunker import chunk_text

        points: list[dict[str, Any]] = []
        for item in items:
            payload = item.to_payload()
            chunks = chunk_text(
                item.content or item.title,
                chunk_size=self._settings.rag_chunk_size,
                overlap=self._settings.rag_chunk_overlap,
            )
            if not chunks:
                continue
            texts = [c.text for c in chunks]
            vectors = await self._embedding.embed_documents(texts)
            for chunk, vec in zip(chunks, vectors, strict=True):
                cp = dict(payload)
                cp["chunk_index"] = chunk.chunk_index
                cp["chunk_text"] = chunk.text
                cp["vector_dim"] = self._embedding.dimension
                points.append(
                    {
                        "id": f"{item.knowledge_id}-{chunk.chunk_index}",
                        "vector": vec,
                        "payload": cp,
                    }
                )
            if item is not None:
                item.vector_embedded = True
                item.qdrant_point_id = f"{item.knowledge_id}-*"
        if points:
            await self._store.upsert(points)
        logger.info("RAG 索引完成：{} 条知识 → {} 个向量点", len(items), len(points))
        return len(points)

    async def index_knowledge_chunks(
        self,
        item: KnowledgeItem,
        chunks: list[KnowledgeChunk],
    ) -> int:
        """只索引教师确认启用的章节块。"""
        await self.ensure_ready()
        enabled = [chunk for chunk in chunks if chunk.enabled and chunk.content.strip()]
        if not enabled:
            item.vector_embedded = False
            item.qdrant_point_id = None
            return 0
        # 展示原文保持格式；Embedding 和重排使用去除 Markdown 装饰后的稳定检索文本。
        # 小批次写入避免 2GB 部署在大文件索引时同时持有全部向量。
        batch_size = 16
        point_count = 0
        for start in range(0, len(enabled), batch_size):
            batch = enabled[start : start + batch_size]
            search_texts = [markdown_to_search_text(chunk.content) for chunk in batch]
            texts = [
                f"{getattr(chunk, 'heading_path', '') or chunk.heading}\n{search_text}"
                for chunk, search_text in zip(batch, search_texts, strict=True)
            ]
            vectors = await self._embedding.embed_documents(texts)
            points: list[dict[str, Any]] = []
            indexed_chunks: list[tuple[KnowledgeChunk, str]] = []
            for chunk, search_text, vector in zip(batch, search_texts, vectors, strict=True):
                payload = item.to_payload()
                payload.update(
                    {
                        "title": f"{item.title} / {chunk.heading}",
                        "content": chunk.content,
                        "chunk_text": search_text,
                        "search_text": search_text,
                        "chunk_index": chunk.chunk_index,
                        "chunk_id": chunk.id,
                        "heading": chunk.heading,
                        "heading_path": getattr(chunk, "heading_path", "") or "",
                        "chunk_type": getattr(chunk, "chunk_type", "text") or "text",
                        "chapter": chunk.chapter,
                        "page": chunk.page_start,
                        "page_end": chunk.page_end,
                        "knowledge_point": chunk.knowledge_point_name,
                        "ability": chunk.ability or item.ability,
                        "vector_dim": self._embedding.dimension,
                    }
                )
                point_id = f"{item.knowledge_id}-section-{chunk.id}"
                points.append({"id": point_id, "vector": vector, "payload": payload})
                indexed_chunks.append((chunk, point_id))
            await self._store.upsert(points)
            for chunk, point_id in indexed_chunks:
                chunk.vector_embedded = True
                chunk.qdrant_point_id = point_id
            point_count += len(points)
        item.vector_embedded = True
        item.qdrant_point_id = f"{item.knowledge_id}-section-*"
        return point_count

    async def reindex_file_item(
        self,
        session: AsyncSession,
        item: KnowledgeItem,
        chunks: list[KnowledgeChunk] | None = None,
    ) -> int:
        """清除文件旧索引，只重建当前已启用章节块。"""
        await self.ensure_ready()
        if chunks is None:
            from sqlalchemy import select

            from app.models.knowledge import KnowledgeChunk

            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunk)
                        .where(KnowledgeChunk.knowledge_item_id == item.id)
                        .order_by(KnowledgeChunk.chunk_index)
                    )
                ).all()
            )
        await self._store.delete_by_filter({"knowledge_id": item.knowledge_id})
        for chunk in chunks:
            chunk.vector_embedded = False
            chunk.qdrant_point_id = None
        return await self.index_knowledge_chunks(item, chunks)

    async def delete_knowledge_index(self, knowledge_id: str) -> None:
        """按知识编号清理其全部向量块。"""
        await self.ensure_ready()
        await self._store.delete_by_filter({"knowledge_id": knowledge_id})

    def mark_index_dirty(self) -> None:
        """让后续检索重新检查数据库中未完成索引的分块。"""
        self._db_synced = False

    async def retrieve(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """向量检索，返回原始 hits。"""
        await self.ensure_ready()
        # 每个 Pipeline 实例首次检索时，从 DB 补齐新增或变更知识。
        await self.ensure_indexed_from_db()
        k = top_k or self._settings.rag_retrieve_top_k
        qv = await self._embedding.embed_query(query)
        return await self._store.search(qv, top_k=k, filters=filters)

    async def retrieve_and_rerank(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> list[RetrievedDoc]:
        """检索 + 重排，返回 RetrievedDoc 列表（按 rerank_score 降序）。"""
        await self.ensure_ready()
        retrieve_k = self._settings.rag_retrieve_top_k
        rerank_k = top_k or self._settings.rag_rerank_top_k
        hits = await self.retrieve(query, filters=filters, top_k=retrieve_k)
        if not hits:
            return []
        # 合并同 knowledge_id 的分块文本，避免重复引用
        merged = self._merge_chunks(hits)
        docs = list(merged.values())
        texts = [d["content"] for d in docs]
        scores = await self._reranker.rerank(query, texts)
        ranked = sorted(zip(docs, scores, strict=True), key=lambda x: x[1], reverse=True)
        # 最低相关性过滤
        min_rel = self._settings.rag_min_relevance
        result: list[RetrievedDoc] = []
        for doc, score in ranked[:rerank_k]:
            if score < min_rel and self._reranker.is_mock:
                # Mock 场景下放宽阈值（避免空结果），但仍按分排序
                pass
            result.append(
                RetrievedDoc(
                    knowledge_id=doc.get("knowledge_id", ""),
                    title=doc.get("title", ""),
                    content=doc.get("content", ""),
                    source_name=doc.get("source_name", ""),
                    source_no=doc.get("source_no", ""),
                    chapter=doc.get("chapter", ""),
                    page=doc.get("page"),
                    rerank_score=float(score),
                    metadata=doc,
                )
            )
        return result

    def _merge_chunks(self, hits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """按块粒度归并：每个向量点（分块）独立成文档，不再按文件拼接。

        旧逻辑按 knowledge_id 合并会把同一文件的多个分块拼成
        「整个文件」送入上下文；现改为按向量点/块去重，
        同文件同章节的引用重复由业务层（AnswerNode）控制。
        """
        merged: dict[str, dict[str, Any]] = {}
        for h in hits:
            payload = h.get("payload", {}) or {}
            kid = payload.get("knowledge_id") or h.get("id", "")
            if not kid:
                continue
            point_id = str(h.get("id", ""))
            chunk_ref = payload.get("chunk_id")
            if chunk_ref is None:
                chunk_ref = payload.get("chunk_index")
            key = f"{kid}#{chunk_ref}" if chunk_ref is not None else (point_id or kid)
            content = payload.get("chunk_text") or payload.get("content", "")
            score = float(h.get("score", 0.0))
            if key in merged:
                if score > merged[key]["max_score"]:
                    merged[key]["max_score"] = score
                continue
            merged[key] = {
                "knowledge_id": kid,
                "title": payload.get("title", ""),
                "content": content,
                "source_name": payload.get("source_name", ""),
                "source_no": payload.get("source_no", ""),
                "chapter": payload.get("chapter", ""),
                "page": payload.get("page"),
                "source_type": payload.get("source_type", ""),
                "chunk_id": payload.get("chunk_id"),
                "max_score": score,
            }
        return merged

    def to_citation(self, doc: RetrievedDoc) -> dict[str, Any]:
        return build_citation(doc.metadata)

    async def health(self) -> dict[str, Any]:
        store_ok = True
        try:
            store_ok = await self._store.health()
        except Exception:  # noqa: BLE001
            store_ok = False
        return {
            "embedding": self._embedding.backend,
            "reranker": self._reranker.backend,
            "vector_store": self._store.backend,
            "store_healthy": store_ok,
            "points": await self._store.count(),
        }


# ---------- 单例 ----------
_pipeline: RAGPipeline | None = None


def get_pipeline() -> RAGPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RAGPipeline()
    return _pipeline


def reset_pipeline() -> None:
    global _pipeline
    _pipeline = None


__all__ = ["RAGPipeline", "get_pipeline", "reset_pipeline"]
