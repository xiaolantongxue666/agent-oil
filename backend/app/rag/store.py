"""向量存储抽象（第三十二节）。

Qdrant 为首选向量库；当 Qdrant 服务不可达时回退到进程内内存存储，
保证检索/重排/引用链路在无 Docker 环境下仍可端到端运行。
内存存储仅用于开发与竞赛演示，生产以 Qdrant 为目标。
"""

from __future__ import annotations

import math
import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.core.config import get_settings
from app.core.logging import logger


class VectorStore(ABC):
    """向量存储抽象。"""

    backend: str = "abstract"

    @abstractmethod
    async def ensure_collection(self, dim: int) -> None: ...

    @abstractmethod
    async def upsert(self, points: list[dict[str, Any]]) -> int:
        """points: [{id, vector, payload}]。返回写入数。"""

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """返回 [{id, score, payload}]，按 score 降序。"""

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def delete_by_filter(self, filters: dict[str, Any]) -> None: ...

    @abstractmethod
    async def delete_collection(self) -> None: ...

    @abstractmethod
    async def health(self) -> bool: ...


class QdrantStore(VectorStore):
    """Qdrant 向量库实现。"""

    backend = "qdrant"

    def __init__(self) -> None:
        from qdrant_client import AsyncQdrantClient

        s = get_settings()
        self._client = AsyncQdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
        self._collection = s.qdrant_collection

    async def ensure_collection(self, dim: int) -> None:
        from qdrant_client import models
        from qdrant_client.http.exceptions import UnexpectedResponse

        try:
            await self._client.get_collection(self._collection)
        except (UnexpectedResponse, Exception):  # noqa: BLE001
            await self._client.recreate_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )

    async def upsert(self, points: list[dict[str, Any]]) -> int:
        from qdrant_client import models

        if not points:
            return 0
        # Qdrant 要求 point ID 为 unsigned int 或 UUID，字符串 ID 需转换为 UUID
        _ns = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
        qpoints = []
        for p in points:
            raw_id = p["id"]
            if isinstance(raw_id, int):
                pid: str | int = raw_id
            else:
                pid = str(uuid.uuid5(_ns, str(raw_id)))
            qpoints.append(
                models.PointStruct(id=pid, vector=p["vector"], payload=p.get("payload", {}))
            )
        await self._client.upsert(collection_name=self._collection, points=qpoints)
        return len(qpoints)

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        from qdrant_client import models

        flt = None
        if filters:
            flt = models.Filter(
                must=[
                    models.FieldCondition(key=k, match=models.MatchValue(value=v))
                    for k, v in filters.items()
                    if v is not None
                ]
            )
        # qdrant-client >= 1.7 使用 query_points 替代 search
        _search = getattr(self._client, "query_points", None)
        if callable(_search):
            resp = await _search(
                collection_name=self._collection,
                query=query_vector,
                limit=top_k,
                query_filter=flt,
            )
            hits = resp.points if hasattr(resp, "points") else []
        else:
            hits = await self._client.search(
                collection_name=self._collection,
                query_vector=query_vector,
                limit=top_k,
                query_filter=flt,
            )
        return [
            {"id": str(h.id), "score": float(h.score), "payload": h.payload or {}}
            for h in hits
        ]

    async def count(self) -> int:
        from qdrant_client.http.exceptions import UnexpectedResponse

        try:
            res = await self._client.count(collection_name=self._collection, exact=True)
            return res.count
        except (UnexpectedResponse, Exception):  # noqa: BLE001
            return 0

    async def delete_by_filter(self, filters: dict[str, Any]) -> None:
        from qdrant_client import models

        if not filters:
            return
        query_filter = models.Filter(
            must=[
                models.FieldCondition(key=key, match=models.MatchValue(value=value))
                for key, value in filters.items()
                if value is not None
            ]
        )
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(filter=query_filter),
            wait=True,
        )

    async def delete_collection(self) -> None:
        try:
            await self._client.delete_collection(self._collection)
        except Exception as exc:  # noqa: BLE001
            logger.debug("删除 Qdrant 集合失败：{}", exc)

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
            return True
        except Exception:  # noqa: BLE001
            return False


class InMemoryStore(VectorStore):
    """进程内向量存储（开发兜底）。余弦相似度检索。"""

    backend = "memory"

    def __init__(self) -> None:
        self._points: list[dict[str, Any]] = []

    async def ensure_collection(self, dim: int) -> None:
        return None

    async def upsert(self, points: list[dict[str, Any]]) -> int:
        n = 0
        for p in points:
            pid = str(p.get("id") or uuid.uuid4().hex)
            vec = p["vector"]
            payload = p.get("payload", {})
            # 覆盖同 id
            self._points = [x for x in self._points if str(x.get("id")) != pid]
            self._points.append({"id": pid, "vector": vec, "payload": payload})
            n += 1
        return n

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        results = []
        for pt in self._points:
            if filters and not _match_filters(pt.get("payload", {}), filters):
                continue
            score = _cosine(query_vector, pt["vector"])
            results.append({"id": pt["id"], "score": score, "payload": pt.get("payload", {})})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    async def count(self) -> int:
        return len(self._points)

    async def delete_by_filter(self, filters: dict[str, Any]) -> None:
        if filters:
            self._points = [
                point
                for point in self._points
                if not _match_filters(point.get("payload", {}), filters)
            ]

    async def delete_collection(self) -> None:
        self._points = []

    async def health(self) -> bool:
        return True


def _match_filters(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
    for k, v in filters.items():
        if v is None:
            continue
        if payload.get(k) != v:
            return False
    return True


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------- 单例 ----------
_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """返回单例向量存储：测试环境直接内存；其余惰性返回 Qdrant 实例。

    Qdrant 的可达性探测在首次使用（ensure_collection）时由 Pipeline 完成，
    失败则切换到 InMemoryStore——避免在非 async 上下文里阻塞。
    """
    global _store
    if _store is not None:
        return _store
    settings = get_settings()
    if settings.app_env == "test":
        _store = InMemoryStore()
        logger.info("VectorStore 使用内存存储（测试环境）")
        return _store
    try:
        _store = QdrantStore()
        logger.info("VectorStore 使用 Qdrant（{}）", settings.qdrant_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Qdrant 客户端初始化失败，回退内存存储: {}", exc)
        _store = InMemoryStore()
    return _store


def set_vector_store(store: VectorStore) -> None:
    """注入存储（测试用）。"""
    global _store
    _store = store


def reset_vector_store() -> None:
    global _store
    _store = None


__all__ = [
    "VectorStore",
    "QdrantStore",
    "InMemoryStore",
    "get_vector_store",
    "set_vector_store",
    "reset_vector_store",
]
