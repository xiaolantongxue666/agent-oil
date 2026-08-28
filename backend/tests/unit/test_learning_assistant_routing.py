"""学习助手意图分流与引用采用校验。"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.routers.chat import _sanitize_stream_citations
from app.llm.base import LLMMessage, StructuredOutputResult
from app.llm.gateway import LLMGateway
from app.llm.mock import MockLLMProvider
from app.services import learning_assistant as learning_assistant_module
from app.services.learning_assistant import LearningAssistantService
from app.workflow.context import RetrievedDoc, WorkflowContext
from app.workflow.nodes.qa_nodes import AnswerNode


def test_identify_composite_business_intents() -> None:
    service = LearningAssistantService()

    primary, secondary = service.identify_intents(
        "分析我的能力画像并推荐训练",
        "student",
    )

    assert primary == "training_recommendation"
    assert secondary == ["ability_diagnosis"]


def test_conversation_and_text_assistance_do_not_default_to_knowledge_qa() -> None:
    service = LearningAssistantService()

    assert service.identify_intents("你好", "student") == ("conversation", [])
    assert service.identify_intents("帮我改写这段话", "student") == ("text_assistance", [])
    assert service.identify_intents("你好，阀门工作原理是什么？", "student") == (
        "knowledge_qa",
        [],
    )


def test_follow_up_inherits_recent_business_intent() -> None:
    service = LearningAssistantService()

    primary, secondary = service.identify_intents(
        "为什么？",
        "student",
        history=["我的能力画像如何？"],
    )

    assert primary == "ability_diagnosis"
    assert secondary == []


# ---------- 教师专属意图（班级学情 / 题库质量） ----------
def test_teacher_intents_route_to_teaching_management_modules() -> None:
    service = LearningAssistantService()

    assert service.identify_intents("看看班级学情如何", "teacher") == ("class_insight", [])
    assert service.identify_intents("这次考试的平均分和错误率怎么样", "teacher") == (
        "class_insight",
        [],
    )
    assert service.identify_intents("题库质量怎么样？", "teacher") == (
        "question_bank_quality",
        [],
    )
    assert service.identify_intents("待审核的题目多吗", "teacher") == (
        "question_bank_quality",
        [],
    )


def test_teacher_business_questions_do_not_leak_student_intents() -> None:
    """学生角色不触发教师意图，教师角色不触发学生个人意图。"""

    service = LearningAssistantService()

    assert service.identify_intents("看看班级学情如何", "student") == ("knowledge_qa", [])
    assert service.identify_intents("推荐一个实训", "teacher") == ("knowledge_qa", [])


def test_composite_teacher_intents_keep_priority_order() -> None:
    service = LearningAssistantService()

    primary, secondary = service.identify_intents("看看班级学情和题库质量", "teacher")

    assert primary == "class_insight"
    assert secondary == ["question_bank_quality"]


@pytest.mark.asyncio
async def test_teacher_class_insight_prepare_collects_aggregate_facts() -> None:
    service = LearningAssistantService()
    captured: dict[str, str] = {}

    async def fake_class_insight(db, message, result):
        captured["message"] = message
        result.evidence.append({"type": "class_insight", "title": "学情"})

    service._add_class_insight_facts = fake_class_insight

    result = await service.prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="看看这次班级学情情况",
    )

    assert captured["message"] == "看看这次班级学情情况"
    assert result.intent == "class_insight"
    # 教师业务意图不触发知识库检索（避免再次踩中 Embedding 链路）
    assert result.requires_knowledge_base is False
    assert result.evidence[0]["type"] == "class_insight"
    assert "class_insight" in result.controlled_facts
    steps = {item["step"]: item["status"] for item in result.execution_trace}
    assert steps.get("class_insight") == "completed"


@pytest.mark.asyncio
async def test_teacher_question_bank_prepare_wires_module() -> None:
    service = LearningAssistantService()

    async def fake_bank(db, result):
        result.evidence.append({"type": "question_bank_quality", "title": "题库"})

    service._add_question_bank_facts = fake_bank

    result = await service.prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="题库质量如何？",
    )

    assert result.intent == "question_bank_quality"
    assert result.requires_knowledge_base is False
    assert result.evidence[0]["type"] == "question_bank_quality"
    steps = {item["step"]: item["status"] for item in result.execution_trace}
    assert steps.get("question_bank_quality") == "completed"


@pytest.mark.asyncio
async def test_teacher_module_failure_is_reported_without_rag_fallback() -> None:
    service = LearningAssistantService()
    service._add_class_insight_facts = AsyncMock(side_effect=RuntimeError("db down"))

    result = await service.prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="班级学情怎么样",
    )

    assert result.module_errors == [{"module": "class_insight", "error": "RuntimeError"}]
    assert result.requires_knowledge_base is False
    assert "不得用知识库结果冒充" in result.controlled_facts
    steps = {item["step"]: item["status"] for item in result.execution_trace}
    assert steps.get("class_insight") == "failed"


# ---------- 教师误用学生端个人功能：角色使用指引 ----------
@pytest.mark.asyncio
async def test_teacher_student_feature_question_gets_role_guidance(monkeypatch) -> None:
    """教师问学生个人功能时不走学生模块/知识库，确定性返回教师端指引。"""

    gateway = _IntentClassifierGateway({"intent": "class_insight"})
    monkeypatch.setattr(learning_assistant_module, "get_gateway", lambda: gateway)

    result = await LearningAssistantService().prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="我的薄弱能力是什么？",
    )

    assert result.role_guidance_hint == "个人能力诊断"
    assert result.role_guidance_kind == "student_feature"
    assert result.intent == "role_guidance"
    assert result.requires_knowledge_base is False
    # 角色指引是确定性规则，不应触发 LLM 兜底分类
    assert gateway.calls == 0
    routes = {card.get("route") for card in result.cards}
    assert {"/teacher/training-results", "/teacher/training", "/teacher/students"} <= routes
    assert "学生端个人功能" in result.controlled_facts
    steps = {item["step"]: item["status"] for item in result.execution_trace}
    assert steps.get("role_guidance") == "completed"


@pytest.mark.asyncio
async def test_student_same_question_does_not_get_role_guidance() -> None:
    """学生提问相同内容时正常走学生模块，不产生角色提示。"""

    service = LearningAssistantService()
    service._recommendation.generate_recommendations = AsyncMock(return_value=[])

    result = await service.prepare(
        AsyncMock(),
        user_id=1,
        role="student",
        message="推荐一个实训",
    )

    assert result.role_guidance_hint == ""
    assert result.intent == "training_recommendation"


@pytest.mark.asyncio
async def test_teacher_class_question_is_not_mistaken_for_student_feature() -> None:
    """命中教师管理意图的消息优先走教学模块，不产生角色提示。"""

    service = LearningAssistantService()
    service._add_class_insight_facts = AsyncMock()

    result = await service.prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="学生的训练成绩怎么样",
    )

    assert result.role_guidance_hint == ""
    assert result.intent == "class_insight"


def test_role_guidance_answer_names_teacher_entries() -> None:
    answer = AnswerNode._build_teacher_guidance_answer("个性化实训推荐")

    assert "个性化实训推荐" in answer
    assert "教师/管理员账号" in answer
    assert "班级教学实施复盘" in answer
    assert "实训任务与题库" in answer
    assert "知识库" in answer


def test_student_guidance_answer_names_student_entries() -> None:
    answer = AnswerNode._build_student_guidance_answer("班级学情分析")

    assert "班级学情分析" in answer
    assert "学生账号" in answer
    assert "能力画像" in answer
    assert "自适应学习" in answer
    assert "咨询任课教师" in answer


@pytest.mark.asyncio
async def test_student_teacher_feature_question_gets_role_guidance() -> None:
    """学生问教师端管理功能时不退回知识库，确定性返回学生端指引。"""

    result = await LearningAssistantService().prepare(
        AsyncMock(),
        user_id=1,
        role="student",
        message="班级学情怎么样？",
    )

    assert result.role_guidance_hint == "班级学情分析"
    assert result.role_guidance_kind == "teacher_feature"
    assert result.intent == "role_guidance"
    assert result.requires_knowledge_base is False
    routes = {card.get("route") for card in result.cards}
    assert {"/profile", "/adaptive-learning"} <= routes
    assert "教师端教学管理功能" in result.controlled_facts
    steps = {item["step"]: item["status"] for item in result.execution_trace}
    assert steps.get("role_guidance") == "completed"


@pytest.mark.asyncio
async def test_student_personal_intent_wins_over_teacher_words() -> None:
    """学生消息同时命中学生意图与教师词表时，优先走学生模块、不提示。"""

    service = LearningAssistantService()
    service._recommendation.generate_recommendations = AsyncMock(return_value=[])
    service._add_training_review = AsyncMock()

    # “错题”既是学生复盘词也是教师题库词，学生角色应走个人复盘模块
    result = await service.prepare(
        AsyncMock(),
        user_id=1,
        role="student",
        message="我上次训练的错题有哪些",
    )

    assert result.role_guidance_hint == ""
    assert result.intent == "training_review"


@pytest.mark.asyncio
async def test_admin_gets_no_role_hint_and_can_ask_both_sides(monkeypatch) -> None:
    """管理员两端都可提问：管理数据走教学模块，其余不提示、不拦截。"""
    service = LearningAssistantService()

    # 管理员问教师端管理数据 → 正常走班级学情模块
    service._add_class_insight_facts = AsyncMock()
    admin_teacher_side = await service.prepare(
        AsyncMock(),
        user_id=3,
        role="admin",
        message="班级学情怎么样",
    )
    assert admin_teacher_side.role_guidance_hint == ""
    assert admin_teacher_side.intent == "class_insight"

    # 管理员问学生端个人功能 → 不提示，兜底分类不采纳白名单外标签，走知识库
    gateway = _IntentClassifierGateway({"intent": "training_recommendation"})
    monkeypatch.setattr(learning_assistant_module, "get_gateway", lambda: gateway)
    admin_student_side = await service.prepare(
        AsyncMock(),
        user_id=3,
        role="admin",
        message="推荐一个实训",
    )
    assert admin_student_side.role_guidance_hint == ""
    assert admin_student_side.intent == "knowledge_qa"
    assert admin_student_side.requires_knowledge_base is True
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_answer_node_outputs_role_guidance_without_llm(monkeypatch) -> None:
    """AnswerNode 命中角色提示时确定性作答，不调用模型、不检索知识库。"""

    qa_nodes_module = importlib.import_module("app.workflow.nodes.qa_nodes")

    def _fail_gateway():
        raise AssertionError("角色指引回答不得调用 LLM")

    monkeypatch.setattr(qa_nodes_module, "get_gateway", _fail_gateway)
    monkeypatch.setattr(
        qa_nodes_module,
        "get_pipeline",
        lambda: SimpleNamespace(to_citation=lambda doc: {}),
    )
    context = WorkflowContext(
        session_id="s-1",
        user_id=2,
        role="teacher",
        intent="role_guidance",
        mode="qa",
        current_node="answer",
        user_input="我的薄弱能力是什么？",
        metadata={
            "role_guidance_hint": "个人能力诊断",
            "role_guidance_kind": "student_feature",
            "requires_knowledge_base": False,
            "execution_trace": [],
        },
    )

    result = await AnswerNode().execute(context)

    assert "个人能力诊断" in result.metadata["answer"]
    assert result.metadata["answer_basis"] == ["role_guidance"]
    assert result.metadata["retrieval_status"] == "not_called"
    assert result.metadata["citations"] == []
    assert result.next_node == "output_guard"


# ---------- 教师意图兜底分类（关键词未命中 → 闭合集 LLM + 白名单过滤） ----------
class _IntentClassifierGateway:
    """可编程的结构化分类网关，用于校验兜底分类的过滤行为。"""

    provider_name = "fake"

    def __init__(self, payload: dict | None = None, error: bool = False) -> None:
        self._payload = payload
        self._error = error
        self.calls = 0

    async def chat_structured(self, messages: list[LLMMessage], **_kwargs):
        self.calls += 1
        if self._error:
            raise RuntimeError("llm unavailable")
        return StructuredOutputResult(
            success=self._payload is not None,
            data=self._payload,
            attempts=1,
            provider="fake",
        )


def test_teacher_class_insight_keywords_cover_natural_phrasings() -> None:
    service = LearningAssistantService()

    assert service.identify_intents("当前学生的学习情况如何", "teacher") == (
        "class_insight",
        [],
    )
    assert service.identify_intents("学生掌握得怎么样", "teacher") == ("class_insight", [])
    assert service.identify_intents("学生对任务的完成情况如何", "teacher") == (
        "class_insight",
        [],
    )


@pytest.mark.asyncio
async def test_teacher_llm_fallback_promotes_class_insight(monkeypatch) -> None:
    service = LearningAssistantService()
    gateway = _IntentClassifierGateway({"intent": "class_insight"})

    async def fake_facts(db, message, result):
        result.evidence.append({"type": "class_insight", "title": "学情"})

    service._add_class_insight_facts = fake_facts
    monkeypatch.setattr(learning_assistant_module, "get_gateway", lambda: gateway)

    # “训练得怎么样”未命中任何关键词，只能靠兜底分类改判
    result = await service.prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="最近学生们训练得怎么样啊",
    )

    assert gateway.calls == 1
    assert result.intent == "class_insight"
    assert result.intent_confidence == 0.6
    assert result.requires_knowledge_base is False
    assert "intent_via_llm_classifier" in result.trace


@pytest.mark.asyncio
async def test_teacher_llm_fallback_filters_non_whitelisted_labels(monkeypatch) -> None:
    """LLM 输出白名单之外的标签时必须过滤，维持 knowledge_qa 原判。"""

    service = LearningAssistantService()
    gateway = _IntentClassifierGateway({"intent": "training_recommendation"})
    monkeypatch.setattr(learning_assistant_module, "get_gateway", lambda: gateway)

    result = await service.prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="这个平台能做什么",
    )

    assert gateway.calls == 1
    assert result.intent == "knowledge_qa"


@pytest.mark.asyncio
async def test_teacher_llm_fallback_failure_keeps_knowledge_qa(monkeypatch) -> None:
    """模型不可用/超时时兜底静默失效，不阻塞原问答链路。"""

    service = LearningAssistantService()
    gateway = _IntentClassifierGateway(error=True)
    monkeypatch.setattr(learning_assistant_module, "get_gateway", lambda: gateway)

    result = await service.prepare(
        AsyncMock(),
        user_id=2,
        role="teacher",
        message="给我讲讲输气站的工艺流程",
    )

    assert gateway.calls == 1
    assert result.intent == "knowledge_qa"
    assert "intent_via_llm_classifier" not in result.trace


@pytest.mark.asyncio
async def test_student_keyword_miss_does_not_invoke_classifier(monkeypatch) -> None:
    """兜底分类只对教师/管理员生效，学生路径零额外模型调用。"""

    service = LearningAssistantService()
    gateway = _IntentClassifierGateway({"intent": "class_insight"})
    monkeypatch.setattr(learning_assistant_module, "get_gateway", lambda: gateway)

    result = await service.prepare(
        AsyncMock(),
        user_id=1,
        role="student",
        message="阀门渗漏怎么判断",
    )

    assert gateway.calls == 0
    assert result.intent == "knowledge_qa"


@pytest.mark.asyncio
async def test_llm_fallback_is_noop_for_mock_template_output(monkeypatch) -> None:
    """离线 Mock 模式：模板输出不含合法 intent 字段，闭合集过滤保证行为不变。"""

    monkeypatch.setattr(
        learning_assistant_module,
        "get_gateway",
        lambda: LLMGateway(MockLLMProvider()),
    )

    promoted = await LearningAssistantService._refine_teacher_intent(
        "最近学生们训练得怎么样啊"
    )

    assert promoted is None


def test_follow_up_does_not_inherit_stale_business_intent() -> None:
    service = LearningAssistantService()

    primary, secondary = service.identify_intents(
        "为什么？",
        "student",
        history=["我的能力画像如何？", "阀门渗漏如何判断？"],
    )

    assert primary == "knowledge_qa"
    assert secondary == []


def test_knowledge_evidence_follow_up_keeps_business_intent() -> None:
    service = LearningAssistantService()

    primary, secondary = service.identify_intents(
        "教材中怎么说？",
        "student",
        history=["我的能力画像如何？"],
    )

    assert primary == "ability_diagnosis"
    assert secondary == []


def test_used_citations_are_whitelisted_and_invalid_markers_removed() -> None:
    candidates = [
        {"knowledge_id": "K-1", "chapter": "第一章", "chunk_id": 11},
        {"knowledge_id": "K-2", "chapter": "第二章", "chunk_id": 22},
    ]

    answer, citations = AnswerNode._select_used_citations(
        "结论一有资料支持[2]，无效引用不得保留[9]。",
        candidates,
    )

    assert "[2]" in answer
    assert "[9]" not in answer
    assert citations == [candidates[1]]


def test_retrieved_candidates_are_not_citations_when_answer_does_not_use_them() -> None:
    candidates = [
        {"knowledge_id": "K-1", "chapter": "第一章", "chunk_id": 11},
    ]

    answer, citations = AnswerNode._select_used_citations("仅基于业务结果回答。", candidates)

    assert answer == "仅基于业务结果回答。"
    assert citations == []


def test_business_evidence_requires_valid_answer_marker() -> None:
    answer, indexes = AnswerNode._select_used_business_evidence(
        "采用第一条业务事实[B1]，越界标注[B9]不保留。",
        2,
    )

    assert indexes == [1]
    assert "[B1]" in answer
    assert "[B9]" not in answer


def test_stream_citation_sanitizer_removes_out_of_range_markers() -> None:
    cleaned = _sanitize_stream_citations(
        "有效[1][B1]，无效[8][B7]。",
        knowledge_count=2,
        business_count=1,
    )

    assert cleaned == "有效，无效。"


@pytest.mark.asyncio
async def test_support_verifier_only_keeps_indexes_returned_by_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Gateway:
        async def chat_structured(self, *_args, **_kwargs):
            return SimpleNamespace(
                success=True,
                data={
                    "supported_knowledge_indexes": [2, 99],
                    "supported_business_indexes": [],
                },
            )

    qa_nodes_module = importlib.import_module("app.workflow.nodes.qa_nodes")
    monkeypatch.setattr(qa_nodes_module, "get_gateway", lambda: Gateway())
    docs = [
        RetrievedDoc(content="不支持结论的片段"),
        RetrievedDoc(content="能够支持结论的片段"),
    ]

    knowledge, business, succeeded = await AnswerNode()._verify_used_evidence(
        "结论[1][2][B1]",
        docs,
        [{"title": "业务事实"}],
        [1, 2],
        [1],
    )

    assert succeeded is True
    assert knowledge == {2}
    assert business == set()


@pytest.mark.asyncio
async def test_business_failure_is_reported_without_forcing_rag() -> None:
    service = LearningAssistantService()
    service._ability.get_profile = AsyncMock(side_effect=RuntimeError("unavailable"))

    result = await service.prepare(
        AsyncMock(),
        user_id=1,
        role="student",
        message="我的能力画像如何？",
    )

    assert result.requires_knowledge_base is False
    assert result.module_errors == [{"module": "ability_diagnosis", "error": "RuntimeError"}]
    assert any(item["status"] == "failed" for item in result.execution_trace)
    assert "不得用知识库结果冒充" in result.controlled_facts


@pytest.mark.asyncio
async def test_recommendation_progress_is_realtime_and_retry_is_explicit() -> None:
    service = LearningAssistantService()
    service._recommendation.generate_recommendations = AsyncMock(
        return_value=[
            SimpleNamespace(
                task_code="TT-06",
                task_title="HSE 风险辨识训练",
                reason_text="当前任务均已完成，建议针对薄弱能力复训。",
                reason_code="retry",
                difficulty=3,
                estimated_minutes=20,
            )
        ]
    )
    progress: asyncio.Queue[dict] = asyncio.Queue()

    result = await service.prepare(
        AsyncMock(),
        user_id=1,
        role="student",
        message="推荐一个实训",
        progress_sink=progress,
    )
    events = []
    while not progress.empty():
        events.append(progress.get_nowait())

    recommendation_events = [
        item for item in events if item["step"] == "training_recommendation"
    ]
    assert [item["status"] for item in recommendation_events] == [
        "running",
        "completed",
    ]
    assert "复训" in recommendation_events[-1]["summary"]
    assert result.evidence[0]["recommendation_status"] == "retry"
    assert result.evidence[0]["items"][0]["mode"] == "retry"
    assert result.cards[0]["title"].startswith("复训：")
    assert all(item["status"] != "running" for item in result.execution_trace)


@pytest.mark.asyncio
async def test_empty_recommendation_is_not_exposed_as_business_evidence() -> None:
    service = LearningAssistantService()
    service._recommendation.generate_recommendations = AsyncMock(return_value=[])

    result = await service.prepare(
        AsyncMock(),
        user_id=1,
        role="student",
        message="推荐一个实训",
    )

    assert result.evidence == []
    assert result.cards == []
    assert result.module_outcomes == [
        {"module": "training_recommendation", "status": "no_candidate", "count": 0}
    ]
    assert "暂无可用的已发布实训" in result.execution_trace[-1]["summary"]
    assert "no_candidate" in result.controlled_facts


def test_recommendation_answer_names_retry_task() -> None:
    answer = AnswerNode._build_recommendation_answer(
        [
            {
                "type": "training_recommendation",
                "items": [
                    {
                        "title": "阀室巡检基础训练",
                        "reason": "用于补强安全风险辨识能力",
                        "reason_code": "retry",
                        "mode": "retry",
                        "difficulty": 2,
                        "estimated_minutes": 30,
                    }
                ],
            }
        ]
    )

    assert "复训「阀室巡检基础训练」" in answer
    assert "安全风险辨识" in answer
    assert "[B1]" in answer
