"""Reranker 服务（第三十二节）。

支持三种后端：
- api: 调用阿里云百炼（DashScope）Rerank API，推荐 qwen3-rerank
- local: 本地 sentence-transformers CrossEncoder（BGE-Reranker）
- mock: 词项重叠（Jaccard）评分（离线兜底）

未安装本地依赖或 API Key 缺失时自动降级。
"""

from __future__ import annotations

import math
from typing import Any

from app.core.config import get_settings
from app.core.logging import logger
from app.rag.embedding import _tokenize  # 复用分词


class RerankerService:
    """Reranker 服务：API / 本地 / Mock。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._backend = "mock"
        self._model: Any = None
        self._api_key: str = ""
        self._api_base_url: str = ""
        self._init()

    def _init(self) -> None:
        # 1) API 模式优先
        if self._settings.reranker_backend == "api":
            self._init_api()
            if self._backend == "api":
                return
        # 2) 本地模式
        if self._settings.reranker_backend == "local":
            self._init_local()
            if self._backend == "local":
                return
        # 3) 都没成功 → mock
        self._backend = "mock"

    def _init_api(self) -> None:
        self._api_key = self._settings.reranker_api_key or self._settings.bailian_api_key
        self._api_base_url = (
            self._settings.reranker_base_url
            or self._settings.bailian_base_url
        )
        if not self._api_key:
            logger.warning("Reranker API 模式：缺少 API Key，跳过")
            return
        self._backend = "api"
        logger.info(
            "Reranker API 后端就绪: model={}, base={}",
            self._settings.reranker_model,
            self._api_base_url,
        )

    def _init_local(self) -> None:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore

            self._model = CrossEncoder(self._settings.reranker_model)
            self._backend = "local"
            logger.info("Reranker 本地模型已加载: {}", self._settings.reranker_model)
        except Exception as exc:  # noqa: BLE001
            logger.warning("本地 Reranker 模型不可用: {}", exc)

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_mock(self) -> bool:
        return self._backend == "mock"

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """返回与 documents 等长的相关性分数（已归一化到 0~1）。"""
        if not documents:
            return []

        # 1) API 模式
        if self._backend == "api" and self._api_key:
            try:
                return await self._api_rerank(query, documents)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reranker API 调用失败，临时回退 Mock: {}", exc)

        # 2) 本地模式
        if self._backend == "local" and self._model is not None:
            try:
                pairs = [(query, d) for d in documents]
                scores = self._model.predict(pairs)
                return [1.0 / (1.0 + math.exp(-float(s))) for s in scores]
            except Exception as exc:  # noqa: BLE001
                logger.warning("本地 Reranker 预测失败，临时回退 Mock: {}", exc)

        # 3) Mock
        return [self._mock_score(query, d) for d in documents]

    # ---- API 调用 ----

    def _build_api_request(
        self,
        query: str,
        documents: list[str],
    ) -> tuple[str, dict[str, Any]]:
        """按模型生成百炼 Rerank 请求。

        qwen3-rerank 使用 OpenAI 兼容的 ``/compatible-api/v1/reranks``；
        其他 DashScope Rerank 模型保留原生接口格式。
        """
        model = self._settings.reranker_model
        base_url = self._api_base_url.rstrip("/")

        if model == "qwen3-rerank":
            if base_url.endswith("/reranks"):
                url = base_url
            else:
                for suffix in ("/compatible-mode/v1", "/compatible-api/v1", "/api/v1"):
                    if base_url.endswith(suffix):
                        base_url = base_url[: -len(suffix)]
                        break
                url = f"{base_url}/compatible-api/v1/reranks"

            payload = {
                "model": model,
                "query": query,
                "documents": documents,
                "top_n": len(documents),
            }
            return url, payload

        native_path = "/api/v1/services/rerank/text-rerank/text-rerank"
        if base_url.endswith(native_path):
            url = base_url
        else:
            for suffix in ("/compatible-mode/v1", "/compatible-api/v1", "/api/v1"):
                if base_url.endswith(suffix):
                    base_url = base_url[: -len(suffix)]
                    break
            url = f"{base_url}{native_path}"

        payload = {
            "model": model,
            "input": {
                "query": query,
                "documents": documents,
            },
            "parameters": {
                "top_n": len(documents),
                "return_documents": False,
            },
        }
        return url, payload

    async def _api_rerank(self, query: str, documents: list[str]) -> list[float]:
        """调用 DashScope Rerank API。"""
        import httpx

        url, payload = self._build_api_request(query, documents)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"Rerank API 错误 status={resp.status_code}: {resp.text[:200]}")

        data = resp.json()

        # qwen3-rerank 的 results 位于顶层；其他 DashScope 模型位于 output 中。
        results = data.get("results") or data.get("output", {}).get("results", [])

        if not results:
            raise RuntimeError(f"Rerank API 返回空结果: {data}")

        # 按 index 排序，确保与 documents 顺序一致
        scores = [0.0] * len(documents)
        for r in results:
            idx = r.get("index", 0)
            score = float(r.get("relevance_score", 0.0))
            if 0 <= idx < len(scores):
                scores[idx] = score

        return scores

    # ---- Mock ----

    def _mock_score(self, query: str, document: str) -> float:
        """词项重叠（Jaccard）作为 Mock 相关性。"""
        q = set(_tokenize(query))
        d = set(_tokenize(document))
        if not q or not d:
            return 0.0
        inter = len(q & d)
        union = len(q | d)
        return inter / union if union else 0.0


# ---------- 单例 ----------
_reranker: RerankerService | None = None


def get_reranker() -> RerankerService:
    global _reranker
    if _reranker is None:
        _reranker = RerankerService()
    return _reranker


__all__ = ["RerankerService", "get_reranker"]
