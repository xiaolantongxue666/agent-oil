"""混合评价引擎单元测试（PHASE 8）。"""

from __future__ import annotations

import pytest

from app.evaluation.final_score import FinalScorer
from app.evaluation.llm_score import LLMScore
from app.evaluation.pipeline import EvaluationInput, EvaluationPipeline
from app.evaluation.rule_score import RuleScorer
from app.evaluation.semantic_score import SemanticScorer

pytestmark = pytest.mark.asyncio


# ---------- RuleScorer ----------
class TestRuleScorer:
    def test_keyword_coverage_full(self):
        scorer = RuleScorer()
        result = scorer.score(
            "检查进站区管线渗漏情况，确认阀门状态正常，记录压力表读数",
            required_points=["管线渗漏", "阀门状态", "记录压力"],
        )
        assert result.score > 60
        assert result.keyword_coverage == 1.0
        assert len(result.keyword_hits) == 3
        assert len(result.keyword_misses) == 0

    def test_keyword_coverage_partial(self):
        scorer = RuleScorer()
        result = scorer.score(
            "检查管线渗漏情况",
            required_points=["管线渗漏", "阀门状态", "记录压力"],
        )
        assert 0.2 < result.keyword_coverage < 0.5
        assert len(result.keyword_hits) >= 1

    def test_keyword_coverage_none(self):
        scorer = RuleScorer()
        result = scorer.score(
            "今天天气不错",
            required_points=["检查管线", "确认阀门", "记录压力"],
        )
        assert result.keyword_coverage == 0.0
        assert result.score < 50

    def test_safety_bonus(self):
        scorer = RuleScorer()
        result = scorer.score(
            "戴好安全帽和手套，设置警戒区域，检查设备风险，确认应急预案，上报隐患",
            required_points=["检查设备"],
        )
        assert result.safety_bonus >= 15  # 有安全意识加分

    def test_critical_error_penalty(self):
        scorer = RuleScorer()
        result = scorer.score(
            "检查管线后不用戴安全帽，直接启动设备，未经许可擅自操作",
            required_points=["检查管线"],
        )
        assert len(result.critical_errors) >= 2
        assert result.score < 40

    def test_no_required_points_baseline(self):
        scorer = RuleScorer()
        result = scorer.score("这是一段关于巡检操作的详细描述，包含很多专业内容")
        assert result.score > 0
        assert result.details["keyword_score"] == 30  # 基础分

    def test_reference_points_bonus(self):
        scorer = RuleScorer()
        result = scorer.score(
            "检查渗漏并报告值班长",
            required_points=["检查渗漏"],
            reference_points=["报告值班长", "记录异常"],
        )
        assert result.details["reference_score"] > 0

    def test_empty_answer_low_score(self):
        scorer = RuleScorer()
        result = scorer.score(
            "",
            required_points=["检查管线", "确认阀门"],
        )
        assert result.score < 30


# ---------- SemanticScorer ----------
class TestSemanticScorer:
    async def test_semantic_similar(self):
        scorer = SemanticScorer()
        result = await scorer.score(
            "检查进站区管线的渗漏情况，确认各阀门的开关状态",
            required_points=["检查管线渗漏", "确认阀门状态"],
        )
        assert result.score > 0
        assert result.similarity > 0

    async def test_semantic_no_reference(self):
        scorer = SemanticScorer()
        result = await scorer.score("一段回答", required_points=None, reference_points=None)
        assert result.score == 50.0
        assert result.details.get("note") == "no_reference_points"

    async def test_semantic_result_fields(self):
        scorer = SemanticScorer()
        result = await scorer.score(
            "巡检时需要检查压力表读数是否正常",
            required_points=["检查压力表"],
        )
        assert result.score >= 0
        # Either successful embed or fallback
        assert "answer_dim" in result.details or "error" in result.details

    def test_cosine_similarity_identical(self):
        sim = SemanticScorer._cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert sim == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        sim = SemanticScorer._cosine_similarity([1.0, 0.0], [0.0, 1.0])
        assert sim == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector(self):
        sim = SemanticScorer._cosine_similarity([0.0, 0.0], [1.0, 0.0])
        assert sim == 0.0


# ---------- LLMScore ----------
class TestLLMScore:
    async def test_llm_score_returns_result(self):
        scorer = LLMScore()
        result = await scorer.score(
            "巡检时应先检查进站区管线有无渗漏，然后确认各阀门开关状态，最后记录仪表参数",
            task_title="输气站日常巡检",
            required_points=["检查管线", "确认阀门"],
        )
        assert result.score > 0
        assert isinstance(result.comment, str)

    async def test_llm_score_with_empty_answer(self):
        scorer = LLMScore()
        result = await scorer.score("", task_title="测试任务")
        # Mock LLM 应该仍然返回结果
        assert result.score >= 0

    def test_authority_evidence_is_marked_as_non_mandatory(self):
        prompt = LLMScore()._build_prompt(
            "学生回答",
            "巡检任务",
            ["检查阀门"],
            ["记录参数"],
            [{"source_no": "GB 30871—2022", "chapter": "4.1", "page": 9, "content": "风险辨识"}],
        )
        assert "权威教学依据" in prompt
        assert "不额外增加必答项" in prompt
        assert "PDF第9页" in prompt


# ---------- FinalScorer ----------
class TestFinalScorer:
    def test_weighted_combination(self):
        scorer = FinalScorer(rule_weight=0.4, semantic_weight=0.3, llm_weight=0.3)
        result = scorer.compute(
            rule_score=80,
            semantic_score=70,
            llm_score=90,
        )
        expected = 80 * 0.4 + 70 * 0.3 + 90 * 0.3
        assert result.final_score == pytest.approx(expected, abs=0.1)

    def test_default_weights(self):
        scorer = FinalScorer()
        assert scorer.rule_weight == pytest.approx(0.4)
        assert scorer.semantic_weight == pytest.approx(0.3)
        assert scorer.llm_weight == pytest.approx(0.3)

    def test_score_clamped_0_100(self):
        scorer = FinalScorer(rule_weight=0.4, semantic_weight=0.3, llm_weight=0.3)
        result = scorer.compute(rule_score=0, semantic_score=0, llm_score=0)
        assert result.final_score == 0.0
        result = scorer.compute(rule_score=100, semantic_score=100, llm_score=100)
        assert result.final_score == 100.0

    def test_strengths_generated(self):
        scorer = FinalScorer(rule_weight=0.4, semantic_weight=0.3, llm_weight=0.3)
        result = scorer.compute(rule_score=90, semantic_score=85, llm_score=88)
        assert len(result.strengths) >= 2

    def test_missing_points_passed_through(self):
        scorer = FinalScorer()
        result = scorer.compute(
            rule_score=60,
            semantic_score=50,
            llm_score=70,
            keyword_misses=["未覆盖要点A", "未覆盖要点B"],
        )
        assert len(result.missing_points) == 2

    def test_explanation_includes_formula(self):
        scorer = FinalScorer(rule_weight=0.4, semantic_weight=0.3, llm_weight=0.3)
        result = scorer.compute(rule_score=80, semantic_score=70, llm_score=90)
        assert "规则分" in result.explanation
        assert "语义分" in result.explanation
        assert "AI 分" in result.explanation


# ---------- Pipeline ----------
class TestEvaluationPipeline:
    async def test_full_pipeline(self):
        pipeline = EvaluationPipeline()
        inp = EvaluationInput(
            answer="巡检时应先检查进站区管线有无渗漏，确认各阀门开关状态正常，记录仪表参数并上报异常",
            task_title="输气站日常巡检",
            required_points=["检查管线渗漏", "确认阀门状态"],
            reference_points=["记录仪表参数", "上报异常"],
            authority_evidence=[{
                "knowledge_id": "NOS-001",
                "title": "运行参数读取与记录",
                "source_name": "燃气储运工国家职业技能标准（2021年版）",
                "source_no": "职业编码6-28-02-01",
                "chapter": "3.1.2",
                "page": 12,
                "content": "巡查中读取并记录运行参数。",
                "is_teaching_simulation": True,
            }],
        )
        output = await pipeline.evaluate(inp)
        assert output.final_score > 0
        assert output.rule_score > 0
        assert output.semantic_score > 0
        assert output.llm_score > 0
        assert isinstance(output.explanation, str)
        assert output.citations[0]["knowledge_id"] == "NOS-001"

    async def test_pipeline_to_metadata(self):
        pipeline = EvaluationPipeline()
        inp = EvaluationInput(
            answer="检查设备运行状态",
            task_title="设备巡检",
        )
        output = await pipeline.evaluate(inp)
        meta = output.to_metadata()
        assert "final_score" in meta
        assert "rule_score" in meta
        assert "semantic_score" in meta
        assert "llm_score" in meta
        assert "ability_scores" in meta
        assert "explanation" in meta
        assert "citations" in meta

    async def test_pipeline_empty_answer(self):
        pipeline = EvaluationPipeline()
        inp = EvaluationInput(
            answer="",
            task_title="测试",
            required_points=["关键点A"],
        )
        output = await pipeline.evaluate(inp)
        assert output.final_score >= 0
        assert output.rule_score < 50  # 空回答规则分应较低
