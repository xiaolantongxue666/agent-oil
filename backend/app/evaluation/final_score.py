"""最终评分合成器（FinalScorer）。

Final Score = Rule × rule_weight + Semantic × semantic_weight + LLM × llm_weight

权重从 Settings 读取，禁止散落硬编码。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings


@dataclass
class FinalScoreResult:
    """最终评分结果。"""

    final_score: float = 0.0  # 0-100
    rule_score: float = 0.0
    semantic_score: float = 0.0
    llm_score: float = 0.0
    weights: dict[str, float] = field(default_factory=dict)
    ability_scores: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    missing_points: list[str] = field(default_factory=list)
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class FinalScorer:
    """加权合成评分器。"""

    def __init__(
        self,
        rule_weight: float | None = None,
        semantic_weight: float | None = None,
        llm_weight: float | None = None,
    ):
        settings = get_settings()
        self.rule_weight = rule_weight if rule_weight is not None else settings.eval_rule_weight
        self.semantic_weight = (
            semantic_weight if semantic_weight is not None else settings.eval_semantic_weight
        )
        self.llm_weight = llm_weight if llm_weight is not None else settings.eval_llm_weight

    def compute(
        self,
        rule_score: float,
        semantic_score: float,
        llm_score: float,
        llm_comment: str = "",
        keyword_misses: list[str] | None = None,
    ) -> FinalScoreResult:
        """合成最终评分。"""
        result = FinalScoreResult()
        result.rule_score = rule_score
        result.semantic_score = semantic_score
        result.llm_score = llm_score

        # 加权
        weighted = (
            rule_score * self.rule_weight
            + semantic_score * self.semantic_weight
            + llm_score * self.llm_weight
        )
        result.final_score = round(max(0.0, min(100.0, weighted)), 1)
        result.weights = {
            "rule": self.rule_weight,
            "semantic": self.semantic_weight,
            "llm": self.llm_weight,
        }

        # 优点/缺点分析
        strengths = []
        if rule_score >= 80:
            strengths.append("关键点覆盖良好")
        if semantic_score >= 80:
            strengths.append("语义表达与参考答案高度一致")
        if llm_score >= 80:
            strengths.append("推理过程清晰，具备岗位思维")
        result.strengths = strengths

        missing = []
        if keyword_misses:
            missing.extend(keyword_misses)
        result.missing_points = missing

        # 解释
        parts = []
        if llm_comment:
            parts.append(llm_comment)
        parts.append(
            f"综合评分：规则分 {rule_score:.0f}(×{self.rule_weight}) + "
            f"语义分 {semantic_score:.0f}(×{self.semantic_weight}) + "
            f"AI 分 {llm_score:.0f}(×{self.llm_weight}) = "
            f"最终 {result.final_score:.0f} 分"
        )
        result.explanation = "\n".join(parts)

        result.details = {
            "weighted_rule": round(rule_score * self.rule_weight, 1),
            "weighted_semantic": round(semantic_score * self.semantic_weight, 1),
            "weighted_llm": round(llm_score * self.llm_weight, 1),
        }
        return result


__all__ = ["FinalScorer", "FinalScoreResult"]
