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

# 单条输入安全长度：远小于 text-embedding-v3 的 8192 token 上限，
# 按“1 个中文字符 ≈ 1 token”的保守估算再留余量，避免超长分块导致整批 400。
_MAX_EMBED_CHARS = 6000

# 治理台发布的运行时配置覆盖（键为 Settings 字段名），优先于 .env。
_RUNTIME_OVERRIDES: dict[str, str] = {}
_RUNTIME_KEYS = ("embedding_backend", "embedding_model", "embedding_base_url", "embedding_api_key")


def apply_runtime_overrides(values: dict[str, str]) -> None:
    """全量替换运行时覆盖：治理台配置（DB）是当前事实来源。

    合并语义会让管理员清空某项后，旧内存覆盖永久残留；
    因此以本次传入的完整字典为准，空值/缺失键一律视为无覆盖。
    """
    new = {
        k: str(v)
        for k, v in values.items()
        if k in _RUNTIME_KEYS and str(v) != ""
    }
    _RUNTIME_OVERRIDES.clear()
    _RUNTIME_OVERRIDES.update(new)


def reset_embedding_service() -> None:
    """丢弃当前单例，下一次获取时按最新配置重建。"""

    global _service
    _service = None


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

    def _get(self, attr: str):
        """治理台运行时配置优先，其次 .env 设置。"""

        value = _RUNTIME_OVERRIDES.get(attr, "")
        return value if value != "" else getattr(self._settings, attr)

    def _init(self) -> None:
        # 1) API 模式优先
        if self._get("embedding_backend") == "api":
            self._init_api()
            if self._backend == "api":
                return
        # 2) 本地模式
        if self._get("embedding_backend") == "local":
            self._init_local()
            if self._backend == "local":
                return
        # 3) 都没成功 → mock
        self._backend = "mock"

    def _init_api(self) -> None:
        api_key = self._get("embedding_api_key") or self._settings.bailian_api_key
        base_url = self._get("embedding_base_url") or self._settings.bailian_base_url
        if not api_key:
            logger.warning("Embedding API 模式：缺少 API Key，跳过")
            return
        try:
            from openai import AsyncOpenAI

            self._api_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self._backend = "api"
            logger.info(
                "Embedding API 后端就绪: model={}, base={}",
                self._get("embedding_model"),
                base_url,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding API 客户端初始化失败: {}", exc)

    def _init_local(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self._get("embedding_model"))
            self._dim = self._model.get_sentence_embedding_dimension()
            self._backend = "local"
            logger.info("Embedding 本地模型已加载: {} (dim={})", self._get("embedding_model"), self._dim)
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
            # 失败时直接抛错（由上层如 RetrieveNode 决定降级策略）。
            # 静默回退 Mock 会让检索在无感知的情况下返回低相关结果。
            return await self._api_embed(text)
        return self._embed_sync(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._backend == "api" and self._api_client is not None:
            # 失败时直接抛错：Mock 哈希向量一旦被索引管线持久化，
            # 会以 vector_embedded=True 永久污染向量库且难以察觉。
            return await self._api_embed_batch(texts)
        return [self._embed_sync(t) for t in texts]

    # ---- API 调用 ----

    async def _api_embed(self, text: str) -> list[float]:
        model = self._get("embedding_model")
        resp = await self._api_client.embeddings.create(
            model=model,
            input=self._sanitize_text(text),
        )
        vec = resp.data[0].embedding
        if self._dim != len(vec):
            self._dim = len(vec)
        return [float(x) for x in vec]

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """规整单条输入：空串占位 + 截断到模型单条 token 上限以内的安全长度。

        text-embedding-v3 单条输入上限 8192 token；超限（如异常超长分块）
        会让整批请求 400 失败，空串同样会被拒绝。
        """
        cleaned = str(text or "").strip()
        if not cleaned:
            return "（空白内容）"
        if len(cleaned) > _MAX_EMBED_CHARS:
            return cleaned[:_MAX_EMBED_CHARS]
        return cleaned

    async def _api_embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get("embedding_model")
        # 百炼 text-embedding-v3 单次最多 10 条输入，超限整批 400
        batch_size = 10
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = [self._sanitize_text(t) for t in texts[i : i + batch_size]]
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


__all__ = ["EmbeddingService", "get_embedding_service"]
