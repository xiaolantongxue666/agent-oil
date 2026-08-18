"""混合评价引擎（PHASE 8）。

三个独立子评分 + 加权合成：
- RuleScore：基于规则的客观评分（关键词覆盖、风险遗漏、步骤完整度）
- SemanticScore：BGE-M3 语义相似度评分
- LLMScore：LLM 推理质量评分
- FinalScore = Rule×0.4 + Semantic×0.3 + LLM×0.3（权重可配置）

LLM 仅参与 LLMScore 的语言质量评价，不参与最终分数路由/决策。
"""

from __future__ import annotations

from app.evaluation.final_score import FinalScorer
from app.evaluation.llm_score import LLMScore
from app.evaluation.pipeline import EvaluationInput, EvaluationOutput, EvaluationPipeline
from app.evaluation.rule_score import RuleScorer
from app.evaluation.semantic_score import SemanticScorer

__all__ = [
    "EvaluationPipeline",
    "EvaluationInput",
    "EvaluationOutput",
    "RuleScorer",
    "SemanticScorer",
    "LLMScore",
    "FinalScorer",
]
