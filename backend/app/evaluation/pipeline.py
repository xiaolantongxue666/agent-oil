"""评价流水线编排器（EvaluationPipeline）。

串联 RuleScorer → SemanticScorer → LLMScore → FinalScorer，
输出最终评价结果。

供 EvaluateNode 在 PHASE 8 调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import logger
from app.evaluation.final_score import FinalScorer
from app.evaluation.llm_score import LLMScore
from app.evaluation.rule_score import RuleScorer
from app.evaluation.semantic_score import SemanticScorer


@dataclass
class EvaluationInput:
    """评价输入。"""

    answer: str = ""
    task_title: str = ""
    required_points: list[str] = field(default_factory=list)
    reference_points: list[str] = field(default_factory=list)
    all_answers: list[str] = field(default_factory=list)  # 多轮作答历史
    authority_evidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvaluationOutput:
    """评价输出。"""

    final_score: float = 0.0
    rule_score: float = 0.0
    semantic_score: float = 0.0
    llm_score: float = 0.0
    ability_scores: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    missing_points: list[str] = field(default_factory=list)
    explanation: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        """转为可存入 WorkflowContext.metadata['final_eval'] 的 dict。"""
        return {
            "final_score": self.final_score,
            "rule_score": self.rule_score,
            "semantic_score": self.semantic_score,
            "llm_score": self.llm_score,
            "ability_scores": self.ability_scores,
            "strengths": self.strengths,
            "missing_points": self.missing_points,
            "explanation": self.explanation,
            "citations": self.citations,
        }


class EvaluationPipeline:
    """混合评价流水线。"""

    def __init__(
        self,
        rule_scorer: RuleScorer | None = None,
        semantic_scorer: SemanticScorer | None = None,
        llm_scorer: LLMScore | None = None,
        final_scorer: FinalScorer | None = None,
    ):
        self.rule_scorer = rule_scorer or RuleScorer()
        self.semantic_scorer = semantic_scorer or SemanticScorer()
        self.llm_scorer = llm_scorer or LLMScore()
        self.final_scorer = final_scorer or FinalScorer()

    async def evaluate(self, inp: EvaluationInput) -> EvaluationOutput:
        """执行完整评价流水线。"""
        output = EvaluationOutput()

        # 1. 规则评分（同步）
        rule_result = self.rule_scorer.score(
            inp.answer,
            required_points=inp.required_points,
            reference_points=inp.reference_points,
        )
        output.rule_score = rule_result.score

        # 2. 语义评分（异步，需要 embedding）
        semantic_result = await self.semantic_scorer.score(
            inp.answer,
            required_points=inp.required_points,
            reference_points=inp.reference_points,
        )
        output.semantic_score = semantic_result.score

        # 3. LLM 评分（异步）
        llm_result = await self.llm_scorer.score(
            inp.answer,
            task_title=inp.task_title,
            required_points=inp.required_points,
            reference_points=inp.reference_points,
            authority_evidence=inp.authority_evidence,
        )
        output.llm_score = llm_result.score

        # 4. 最终合成
        final_result = self.final_scorer.compute(
            rule_score=rule_result.score,
            semantic_score=semantic_result.score,
            llm_score=llm_result.score,
            llm_comment=llm_result.comment,
            keyword_misses=rule_result.keyword_misses,
        )
        output.final_score = final_result.final_score
        output.strengths = final_result.strengths
        output.missing_points = final_result.missing_points
        output.explanation = final_result.explanation
        output.details = {
            "rule": rule_result.details,
            "semantic": semantic_result.details,
            "llm": llm_result.details,
            "final": final_result.details,
            "weights": final_result.weights,
            "llm_dimensions": llm_result.dimensions,
            "llm_comment": llm_result.comment,
        }
        output.citations = [
            {
                key: evidence.get(key)
                for key in (
                    "knowledge_id", "title", "source_name", "source_no",
                    "chapter", "page", "is_teaching_simulation",
                )
            }
            for evidence in inp.authority_evidence
        ]

        logger.info(
            "评价完成：rule={:.0f} semantic={:.0f} llm={:.0f} final={:.0f}",
            output.rule_score,
            output.semantic_score,
            output.llm_score,
            output.final_score,
        )
        return output


__all__ = ["EvaluationPipeline", "EvaluationInput", "EvaluationOutput"]
