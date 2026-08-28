"""题库草稿生成器单元测试。

覆盖：
- _normalise_question 字段别名与容器形态兼容（字符串 options 字典等）
- is_correct/score 健壮解析（字符串 "false" 不再误判为真）
- 选项数 3-5 归一到恰好 4 个
- 选项内容重复整题拒绝
- 题级答案别名（answer / correct_answer）定位正确项
- 兜底模板去雷同（题干与干扰项轮换，正确项不照抄参考要点原文）
- generate() 模型失败时整批兜底并给出明确警告
"""

from __future__ import annotations

import pytest

from app.llm.base import StructuredOutputResult
from app.models.training import TrainingTask
from app.services import training_question_generator as module
from app.services.training_question_generator import TrainingQuestionGenerator


def _task() -> TrainingTask:
    return TrainingTask(
        id=1,
        code="TT-01",
        title="输气站日常巡检",
        description="巡检训练任务",
        difficulty=2,
        target_abilities=["safety_awareness"],
        knowledge_points=["阀门状态确认"],
        required_points=["核对压力表读数"],
        reference_points=["先核对任务条件和教学依据，客观记录并按教学流程报告。"],
    )


def _base_raw() -> dict:
    return {
        "stem": "巡检时发现压力表读数异常，应如何处理？",
        "ability_key": "safety_awareness",
        "knowledge_point": "压力表核查",
        "explanation": "应记录读数并按流程上报复核。",
        "options": [
            {"key": "A", "content": "记录读数并上报复核", "score": 100, "is_correct": True},
            {"key": "B", "content": "修改历史记录使其一致", "score": 0, "is_correct": False},
            {"key": "C", "content": "忽略异常继续巡检", "score": 0, "is_correct": False},
            {"key": "D", "content": "直接认定设备故障并停机", "score": 0, "is_correct": False},
        ],
    }


def _correct(question):
    return [option for option in question.options if option.is_correct]


# ---------- 字段别名与容器兼容 ----------
def test_normalise_accepts_question_alias_and_string_options_dict():
    raw = {
        "question": "发现仪表读数与台账不一致时应如何处理？",
        "explanation": "应记录差异并复核上报。",
        "options": {
            "A": "忽略差异继续巡检",
            "B": "修改台账使其一致",
            "C": "记录差异、复核来源并报告",
            "D": "直接认定仪表故障",
        },
        "answer": "C",
    }
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    assert question.stem.startswith("发现仪表读数")
    assert len(question.options) == 4
    assert [option.key for option in question.options] == ["A", "B", "C", "D"]
    assert _correct(question)[0].content == "记录差异、复核来源并报告"


def test_normalise_accepts_option_content_aliases():
    raw = _base_raw()
    raw["options"] = [
        {"text": "记录读数并上报复核", "is_correct": True},
        {"option_content": "修改历史记录使其一致"},
        {"text": "忽略异常继续巡检"},
        {"text": "直接认定设备故障并停机"},
    ]
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    assert question.options[0].content == "记录读数并上报复核"
    assert question.options[1].content == "修改历史记录使其一致"


# ---------- is_correct / score 健壮解析 ----------
def test_string_false_is_correct_is_not_truthy():
    raw = _base_raw()
    for option in raw["options"]:
        option["is_correct"] = "false"
        option["score"] = 0
    raw["options"][2]["is_correct"] = "TRUE"
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    assert [option.key for option in _correct(question)] == ["C"]


def test_string_false_everywhere_falls_back_to_question_answer_hint():
    raw = _base_raw()
    for option in raw["options"]:
        option["is_correct"] = "false"
    raw["answer"] = "D"
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    assert [option.key for option in _correct(question)] == ["D"]


def test_answer_hint_supports_correct_answer_alias_and_content():
    task = _task()
    raw = _base_raw()
    for option in raw["options"]:
        option.pop("is_correct")
    raw["correct_answer"] = "直接认定设备故障并停机"
    question = TrainingQuestionGenerator._normalise_question(raw, task, 0)
    assert [option.key for option in _correct(question)] == ["D"]

    raw = _base_raw()
    for option in raw["options"]:
        option.pop("is_correct")
    raw["answer_key"] = "2"
    question = TrainingQuestionGenerator._normalise_question(raw, task, 0)
    assert [option.key for option in _correct(question)] == ["B"]


def test_score_formats_are_parsed_and_clamped():
    raw = _base_raw()
    raw["options"][1]["score"] = "85分"
    raw["options"][2]["score"] = "bad"
    raw["options"][3]["score"] = 250
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    scores = {option.key: option.score for option in question.options}
    assert scores["A"] == 100
    assert scores["B"] == 80
    assert scores["C"] == 0
    assert scores["D"] == 80


def test_no_correct_and_all_zero_score_picks_highest_index_first():
    raw = _base_raw()
    for option in raw["options"]:
        option.pop("is_correct")
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    assert _correct(question)[0].key == "A"


# ---------- 选项数归一与去重 ----------
def test_five_options_trimmed_to_four_keeping_correct():
    raw = _base_raw()
    raw["options"].append({"key": "E", "content": "口头汇报后不做记录", "score": 0})
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    assert len(question.options) == 4
    assert [option.key for option in question.options] == ["A", "B", "C", "D"]
    assert "记录读数并上报复核" in [option.content for option in _correct(question)]


def test_three_options_padded_to_four_distinct():
    raw = _base_raw()
    raw["options"] = raw["options"][:3]
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    contents = [option.content for option in question.options]
    assert len(contents) == 4
    assert len(set(contents)) == 4


def test_duplicate_option_content_is_rejected():
    raw = _base_raw()
    for option in raw["options"]:
        option["content"] = "同一个说法"
    with pytest.raises(ValueError):
        TrainingQuestionGenerator._normalise_question(raw, _task(), 0)


def test_overlong_fields_are_truncated_not_rejected():
    raw = _base_raw()
    raw["stem"] = "长" * 3000
    raw["explanation"] = "解" * 5000
    raw["options"][0]["content"] = "选" * 2000
    question = TrainingQuestionGenerator._normalise_question(raw, _task(), 0)
    assert len(question.stem) <= 2000
    assert len(question.explanation) <= 3000
    assert len(question.options[0].content) <= 1000


# ---------- 兜底模板去雷同 ----------
def test_fallback_questions_vary_across_batch():
    task = _task()
    result = TrainingQuestionGenerator().generate_offline(task, [], count=6, difficulty=2)
    questions = result.questions
    assert result.used_fallback is True
    assert len(questions) == 6
    stems = {question.stem for question in questions}
    assert len(stems) > 1, "整批题干不应逐字相同"
    for question in questions:
        contents = [option.content for option in question.options]
        assert len(set(contents)) == 4
        correct = _correct(question)[0]
        assert correct.score == 100
    # 正确项不再照抄参考要点原文
    reference = task.reference_points[0]
    for question in questions:
        assert _correct(question)[0].content != reference
    # 干扰项组合随题目轮换
    distractor_sets = {
        frozenset(option.content for option in question.options if not option.is_correct)
        for question in questions
    }
    assert len(distractor_sets) > 1, "整批干扰项不应完全一致"


# ---------- generate() 兜底行为 ----------
class _FakeGateway:
    provider_name = "fake"

    def __init__(self, result: StructuredOutputResult) -> None:
        self._result = result

    async def chat_structured(self, *args, **kwargs) -> StructuredOutputResult:
        return self._result


class _CapturingStructuredGateway:
    """记录 chat_structured 调用参数，用于校验按题量缩放的生成预算。"""

    provider_name = "fake"

    def __init__(self) -> None:
        self.kwargs: dict | None = None

    async def chat_structured(self, messages, **kwargs) -> StructuredOutputResult:
        self.kwargs = kwargs
        return StructuredOutputResult(success=False, raw_content="", error="x", attempts=1)


async def test_generation_budget_scales_with_question_count(monkeypatch):
    async def fake_prompt(code, variables):
        return "system", "user"

    monkeypatch.setattr(module, "get_prompt_messages", fake_prompt)
    gateway = _CapturingStructuredGateway()
    monkeypatch.setattr(module, "get_gateway", lambda: gateway)
    generator = TrainingQuestionGenerator()

    # 10 题：输出预算触顶 16000、超时触顶 300s，并关闭思考模式
    await generator.generate(_task(), [], count=10, difficulty=2)
    assert gateway.kwargs["max_tokens"] == 16000
    assert gateway.kwargs["timeout"] == 300
    assert gateway.kwargs["extra_body"] == {"enable_thinking": False}

    await generator.generate(_task(), [], count=5, difficulty=2)
    assert gateway.kwargs["max_tokens"] == 11000
    assert gateway.kwargs["timeout"] == 180

    await generator.generate(_task(), [], count=1, difficulty=2)
    assert gateway.kwargs["max_tokens"] == 3000
    assert gateway.kwargs["timeout"] == 84


async def test_generate_falls_back_when_model_fails(monkeypatch):
    async def fake_prompt(code, variables):
        return "system", "user"

    monkeypatch.setattr(module, "get_prompt_messages", fake_prompt)
    monkeypatch.setattr(
        module,
        "get_gateway",
        lambda: _FakeGateway(
            StructuredOutputResult(success=False, raw_content="", error="bad json", attempts=3)
        ),
    )
    result = await TrainingQuestionGenerator().generate(_task(), [], count=3, difficulty=2)
    assert result.used_fallback is True
    assert len(result.questions) == 3
    assert "规则模板" in result.warning
    for question in result.questions:
        assert len(question.options) == 4
        assert len(_correct(question)) == 1


async def test_generate_keeps_valid_questions_and_fills_rest(monkeypatch):
    good = _base_raw()
    async def fake_prompt(code, variables):
        return "system", "user"

    monkeypatch.setattr(module, "get_prompt_messages", fake_prompt)
    monkeypatch.setattr(
        module,
        "get_gateway",
        lambda: _FakeGateway(
            StructuredOutputResult(
                success=True,
                data={"questions": [good, {"stem": "太短"}]},
                attempts=1,
                provider="fake",
            )
        ),
    )
    result = await TrainingQuestionGenerator().generate(_task(), [], count=2, difficulty=2)
    assert result.used_fallback is True
    assert len(result.questions) == 2
    assert "1/2" in result.warning
    assert result.questions[0].stem == good["stem"]
    assert len(result.questions[1].options) == 4


async def test_generate_clean_output_has_no_warning(monkeypatch):
    good = _base_raw()
    async def fake_prompt(code, variables):
        return "system", "user"

    monkeypatch.setattr(module, "get_prompt_messages", fake_prompt)
    monkeypatch.setattr(
        module,
        "get_gateway",
        lambda: _FakeGateway(
            StructuredOutputResult(
                success=True,
                data={"questions": [good]},
                attempts=1,
                provider="fake",
            )
        ),
    )
    result = await TrainingQuestionGenerator().generate(_task(), [], count=1, difficulty=2)
    assert result.used_fallback is False
    assert result.warning == ""
    assert result.provider == "fake"
