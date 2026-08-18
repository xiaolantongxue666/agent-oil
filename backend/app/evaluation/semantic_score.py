"""语义评分器（SemanticScorer）。

使用 BGE-M3 Embedding（或 Mock 降级）计算学生作答与参考要点的语义相似度。

流程：
1. 将参考要点拼成 reference text
2. 获取 answer embedding 和 reference embedding
3. 计算 cosine similarity
4. 映射到 0-100 分

禁止只依靠关键词匹配——必须使用向量语义。
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SemanticScoreResult:
    """语义评分结果。"""

    score: float = 0.0  # 0-100
    similarity: float = 0.0  # 0-1 cosine similarity
    details: dict[str, Any] = field(default_factory=dict)


class SemanticScorer:
    """基于向量语义相似度的评分器。"""

    def __init__(self, embedding_service=None):
        """
        Args:
            embedding_service: 实现 embed(text) → list[float] 的服务。
                              为 None 时延迟获取（从 rag 包）。
        """
        self._embedding_service = embedding_service

    def _get_embedding_service(self):
        if self._embedding_service is None:
            from app.rag import get_embedding_service

            self._embedding_service = get_embedding_service()
        return self._embedding_service

    async def score(
        self,
        answer: str,
        required_points: list[str] | None = None,
        reference_points: list[str] | None = None,
    ) -> SemanticScoreResult:
        """对学生作答进行语义评分。"""
        result = SemanticScoreResult()

        # 构建参考文本
        all_points = []
        if required_points:
            all_points.extend(required_points)
        if reference_points:
            all_points.extend(reference_points)

        if not all_points:
            # 无参考要点，给予中等基础分
            result.score = 50.0
            result.similarity = 0.5
            result.details = {"note": "no_reference_points"}
            return result

        reference_text = "。".join(all_points)

        try:
            svc = self._get_embedding_service()
            # 获取 embedding
            answer_vec = await svc.embed_query(answer)
            reference_vec = await svc.embed_query(reference_text)

            # 计算 cosine similarity
            sim = self._cosine_similarity(answer_vec, reference_vec)
            result.similarity = sim

            # 映射到 0-100 分（similarity 通常 0.3-0.9，映射到 40-100）
            # 使用线性映射：score = sim * 100
            result.score = max(0.0, min(100.0, sim * 100))
            result.details = {
                "answer_dim": len(answer_vec),
                "reference_dim": len(reference_vec),
                "raw_similarity": round(sim, 4),
            }
        except Exception as exc:  # noqa: BLE001
            # Embedding 失败时降级为基础分
            result.score = 40.0
            result.similarity = 0.4
            result.details = {"error": str(exc), "fallback": True}

        return result

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        # 维度对齐（取较短长度）
        min_len = min(len(va), len(vb))
        va = va[:min_len]
        vb = vb[:min_len]
        norm_a = np.linalg.norm(va)
        norm_b = np.linalg.norm(vb)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))


__all__ = ["SemanticScorer", "SemanticScoreResult"]
