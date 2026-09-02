"""P1 阶段：效果评估 / 数据集治理 / 多 Provider 分发。

覆盖：
- dataset-overview：规模结构、§48 四类数据来源口径、§46 对照目标、溯源字段与样本；
- effect-overview：五项指标结构与口径说明（seed 环境样本为 0 时 rate=null，不编造数字）；
- 审核埋点：题库批次发布、草案审核动作写入审计日志（效果统计的数据源）；
- Provider 分发：网关按 llm_provider 运行时键构建 Bailian/Spark/Mock（纯单元，不联网）。
"""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.llm.gateway import _build_provider, _runtime_llm_config, reset_gateway
from app.models.admin import AdminAuditLog
from app.models.curriculum import ProgramAdjustmentProposal


async def test_dataset_overview_structure(client, teacher_token):
    response = await client.get("/api/teacher/analytics-ext/dataset-overview", headers=teacher_token)
    assert response.status_code == 200
    data = response.json()["data"]

    scale = data["scale"]
    assert scale["job_sample_count"] >= 1, "seed 应含人工核验招聘样本"
    assert scale["job_sample_month_span"] >= 1
    assert scale["authoritative_standard_count"] >= 50
    # §46 对照目标必须展示，但不伪装达标
    assert scale["reference_targets"]["job_sample_count"] == "150~300"

    # §48 四类来源齐全且计数为非负整数
    category_keys = {item["key"] for item in data["categories"]}
    assert category_keys == {"live_collected", "frozen_snapshot", "competition_demo", "manual_entry"}
    assert all(isinstance(item["count"], int) and item["count"] >= 0 for item in data["categories"])
    # 种子里 5 条招聘样本来自核验目录 → competition_demo 计数应至少包含它们
    demo = next(item for item in data["categories"] if item["key"] == "competition_demo")
    assert demo["count"] >= 5

    assert "observed_at" in data["traceability_fields"]
    assert "observed_at" in data["time_boundary"]
    assert isinstance(data["samples"], list) and data["samples"]
    sample = data["samples"][0]
    for field in ("source_url", "published_at", "observed_at", "date_confidence", "content_hash", "data_category"):
        assert field in sample


async def test_effect_overview_structure_and_null_rates(client, teacher_token):
    response = await client.get("/api/teacher/analytics-ext/effect-overview", headers=teacher_token)
    assert response.status_code == 200
    data = response.json()["data"]

    # seed 环境没有真实审核流水量，样本为 0 时 rate 必须是 null（§50 不预设漂亮数字）
    for key in ("question_first_pass", "graph_publish", "proposal_adoption", "citation_verifiable"):
        metric = data[key]
        assert set(metric.keys()) >= {"total", "rate"}
        assert metric["rate"] is None or isinstance(metric["rate"], float)
    assert data["remediation_gain"]["paired_student_count"] == 0
    assert data["remediation_gain"]["avg_gain"] is None
    assert set(data["basis_notes"]) == {
        "question_first_pass", "graph_publish", "proposal_adoption", "citation_verifiable",
    }


async def test_review_actions_written_to_audit_log(client, teacher_token):
    """题库批次发布与培养方案草案审核必须留下审计记录（效果统计的数据源）。

    使用测试自建任务，避免发布动作归档种子批次、污染共享演示数据
    （test_p1 按字母序先于 test_training 运行）。
    """
    create = await client.post(
        "/api/teacher/tasks",
        json={
            "code": "P1-EFFECT-001",
            "title": "P1 效果评估测试任务",
            "description": "仅供审计埋点验证",
            "difficulty": 2,
            "target_abilities": ["process_understanding"],
        },
        headers=teacher_token,
    )
    assert create.status_code == 200, create.text
    task = create.json()["data"]
    task_id = task["id"]

    from datetime import UTC, datetime

    from app.models.training import TrainingOption, TrainingQuestion

    async with AsyncSessionLocal() as session:
        batch_code = f"P1TEST-{datetime.now(UTC).strftime('%H%M%S')}"
        question = TrainingQuestion(
            task_id=task_id,
            code=f"{task['code']}-P1Q1",
            stem="测试题干：管道投产前需要执行哪类操作？（教学模拟）",
            ability_key="process_understanding",
            knowledge_point="投产流程",
            explanation="教学解析",
            sort_order=99,
            max_score=100,
            active=False,
            status="draft",
            batch_code=batch_code,
            generated_by_ai=True,
        )
        question.options = [
            TrainingOption(option_key="A", content="置换", score=100, feedback="正确", is_correct=True),
            TrainingOption(option_key="B", content="直接投产", score=0, feedback="错误", is_correct=False),
            TrainingOption(option_key="C", content="提高压力", score=0, feedback="错误", is_correct=False),
            TrainingOption(option_key="D", content="关闭阀门", score=0, feedback="错误", is_correct=False),
        ]
        session.add(question)
        await session.commit()

    response = await client.post(
        f"/api/teacher/tasks/{task_id}/questions/batches/{batch_code}/publish",
        headers=teacher_token,
    )
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        publish_logs = (
            await session.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "question_batch.publish",
                    AdminAuditLog.target_id == batch_code,
                )
            )
        ).all()
        assert len(publish_logs) == 1
        detail = publish_logs[0].detail or {}
        assert detail.get("ai_generated_count") == 1

    # ---- 培养方案草案审核 ----
    programs = (await client.get("/api/teacher/programs", headers=teacher_token)).json()["data"]
    assert programs, "ensure_baseline 应已创建基线方案"
    program_id = programs[0]["id"]
    created = await client.post(
        f"/api/teacher/programs/{program_id}/proposals",
        json={},  # ProposalCreateBody 全部字段有默认值
        headers=teacher_token,
    )
    assert created.status_code == 200
    proposal_id = created.json()["data"]["id"]

    reviewed = await client.patch(
        f"/api/teacher/programs/proposals/{proposal_id}",
        json={"status": "reviewed", "review_note": "P1 测试采纳"},
        headers=teacher_token,
    )
    assert reviewed.status_code == 200

    async with AsyncSessionLocal() as session:
        proposal = await session.get(ProgramAdjustmentProposal, proposal_id)
        assert proposal is not None and proposal.status == "reviewed"
        audit_rows = (
            await session.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "program_proposal.reviewed",
                    AdminAuditLog.target_type == "program_proposal",
                    AdminAuditLog.target_id == str(proposal_id),
                )
            )
        ).all()
        assert len(audit_rows) == 1


def test_gateway_builds_spark_provider_when_configured():
    """P1-3：llm_provider=spark 时网关构建 SparkProvider（不联网，仅验证分发）。"""
    reset_gateway()
    _runtime_llm_config.update({
        "llm_provider": "spark",
        "llm_api_key": "test-spark-key",
        "llm_use_mock": "false",
        "llm_model": "generalv3.5",
    })
    try:
        provider = _build_provider()
        assert provider.name == "spark"
    finally:
        _runtime_llm_config.clear()
        reset_gateway()


def test_gateway_builds_bailian_and_mock_providers():
    """P1-3 回归：默认 bailian 与强制 mock 分发行为不变。"""
    reset_gateway()
    _runtime_llm_config.update({
        "llm_provider": "bailian",
        "llm_api_key": "test-key",
        "llm_use_mock": "false",
        "llm_model": "qwen-plus",
    })
    try:
        assert _build_provider().name == "bailian"
    finally:
        _runtime_llm_config.clear()
        reset_gateway()

    _runtime_llm_config.update({"llm_use_mock": "true", "llm_api_key": "test-key"})
    try:
        assert _build_provider().name == "mock"
    finally:
        _runtime_llm_config.clear()
        reset_gateway()


def test_spark_provider_missing_key_fails_loud():
    """缺少 Key 时 SparkProvider 必须抛 LLMUnavailableError（fail-loud，网关回退 Mock）。"""
    import pytest

    from app.llm.base import LLMUnavailableError
    from app.llm.spark import SparkProvider

    with pytest.raises(LLMUnavailableError):
        SparkProvider(api_key="", model="generalv3.5")


async def test_analytics_ext_access_control(client, student_token, teacher_token):
    anonymous = await client.get("/api/teacher/analytics-ext/effect-overview")
    assert anonymous.status_code == 401
    as_student = await client.get("/api/teacher/analytics-ext/effect-overview", headers=student_token)
    assert as_student.status_code == 403, "教师分析端点拒绝学生"
    as_teacher = await client.get("/api/teacher/analytics-ext/dataset-overview", headers=teacher_token)
    assert as_teacher.status_code == 200


async def test_qa_stream_emits_safety_trace_events(client, student_token):
    """P1-4：QA 流式链路应输出业务阶段事件（safety/检索/回答），不含模型内部内容。"""
    import json as _json

    body = {
        "message": "管道投产前置换的目的是什么？（教学模拟问答）",
        "session_id": None,
    }
    events: list[dict] = []
    async with client.stream(
        "POST", "/api/chat/stream", json=body, headers=student_token
    ) as response:
        assert response.status_code == 200
        buffer = ""
        async for chunk in response.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                event_name = ""
                data_str = ""
                for line in frame.splitlines():
                    if line.startswith("event: "):
                        event_name = line[7:]
                    elif line.startswith("data: "):
                        data_str = line[6:]
                if event_name == "process" and data_str:
                    try:
                        events.append(_json.loads(data_str))
                    except _json.JSONDecodeError:
                        pass

    steps = {event.get("step") for event in events}
    assert "safety" in steps, "应包含安全校验业务阶段事件"
    safety_completed = [
        e for e in events if e.get("step") == "safety" and e.get("status") == "completed"
    ]
    assert safety_completed, "输入安全校验通过事件应存在"
    # 不暴露模型内部内容：所有 summary 均为业务描述，不含 CoT 字样
    for event in events:
        summary = str(event.get("summary", ""))
        assert "chain" not in summary.lower()
        assert "thought" not in summary.lower()
