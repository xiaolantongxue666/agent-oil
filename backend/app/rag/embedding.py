"""Embedding 服务（第三十二节）。

支持三种后端：
- api: 调用阿里云百炼（DashScope）OpenAI 兼容接口，推荐 text-embedding-v3
- local: 本地 sentence-transformers（BGE-M3）
- mock: 确定性词袋哈希向量（离线兜底）

未安装本地依赖或 API Key 缺失时自动降级。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from app.core.config import get_settings
from app.core.logging import logger

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[一-鿿]")


def _tokenize(text: str) -> list[str]:
    """简易分词：拉丁词 + 中文字符。"""
    return _TOKEN_RE.findall(text.lower())


class EmbeddingService:
    """Embedding 服务：自动选择 API / 本地 / Mock 后端。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._backend = "mock"
        self._model: Any = None
        self._api_client: Any = None
        self._dim = self._settings.embedding_dim
        self._init()

    def _init(self) -> None:
        # 1) API 模式优先
        if self._settings.embedding_backend == "api":
            self._init_api()
            if self._backend == "api":
                return
        # 2) 本地模式
        if self._settings.embedding_backend == "local":
            self._init_local()
            if self._backend == "local":
                return
        # 3) 都没成功 → mock
        self._backend = "mock"

    def _init_api(self) -> None:
        api_key = self._settings.embedding_api_key or self._settings.bailian_api_key
        base_url = self._settings.embedding_base_url or self._settings.bailian_base_url
        if not api_key:
            logger.warning("Embedding API 模式：缺少 API Key，跳过")
            return
        try:
            from openai import AsyncOpenAI

            self._api_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self._backend = "api"
            logger.info(
                "Embedding API 后端就绪: model={}, base={}",
                self._settings.embedding_model,
                base_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding API 客户端初始化失败: {}", exc)

    def _init_local(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self._settings.embedding_model)
            self._dim = self._model.get_sentence_embedding_dimension()
            self._backend = "local"
            logger.info("Embedding 本地模型已加载: {} (dim={})", self._settings.embedding_model, self._dim)
        except Exception as exc:  # noqa: BLE001
            logger.warning("本地 Embedding 模型不可用: {}", exc)

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def is_mock(self) -> bool:
        return self._backend == "mock"

    async def embed_query(self, text: str) -> list[float]:
        if self._backend == "api" and self._api_client is not None:
            try:
                return await self._api_embed(text)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding API 调用失败，临时回退 Mock: {}", exc)
        return self._embed_sync(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._backend == "api" and self._api_client is not None:
            try:
                return await self._api_embed_batch(texts)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Embedding API 批量调用失败，临时回退 Mock: {}", exc)
        return [self._embed_sync(t) for t in texts]

    # ---- API 调用 ----

    async def _api_embed(self, text: str) -> list[float]:
        model = self._settings.embedding_model
        resp = await self._api_client.embeddings.create(
            model=model,
            input=text,
        )
        vec = resp.data[0].embedding
        if self._dim != len(vec):
            self._dim = len(vec)
        return [float(x) for x in vec]

    async def _api_embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._settings.embedding_model
        # 百炼 API 单次最多 25 条，分批处理
        batch_size = 25
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await self._api_client.embeddings.create(
                model=model,
                input=batch,
            )
            # 按 index 排序确保顺序正确
            sorted_data = sorted(resp.data, key=lambda d: d.index)
            for d in sorted_data:
                all_vecs.append([float(x) for x in d.embedding])
        if all_vecs and self._dim != len(all_vecs[0]):
            self._dim = len(all_vecs[0])
        return all_vecs

    # ---- 本地 / Mock ----

    def _embed_sync(self, text: str) -> list[float]:
        if self._backend == "local" and self._model is not None:
            try:
                vec = self._model.encode(text, normalize_embeddings=True)
                return [float(x) for x in vec.tolist()]
            except Exception as exc:  # noqa: BLE001
                logger.warning("本地 Embedding 编码失败，临时回退 Mock: {}", exc)
        return self._mock_embed(text)

    def _mock_embed(self, text: str) -> list[float]:
        """确定性词袋哈希向量，L2 归一化。"""
        vec = [0.0] * self._dim
        tokens = _tokenize(text)
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# ---------- 单例 ----------
_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service


def reset_embedding_service() -> None:
    global _service
    _service = None


__all__ = ["EmbeddingService", "get_embedding_service", "reset_embedding_service"]
