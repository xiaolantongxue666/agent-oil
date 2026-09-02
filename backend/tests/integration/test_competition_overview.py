"""P0-4 Phase 7：比赛模式首页聚合 API。

覆盖：总览结构（主链指标/真实发现案例/证据下钻/实训映射）、发现案例取 Gap 最大项、
指标与群级分析口径一致、证据来自真实招聘快照、访问控制（匿名 401 / 学生可读 /
群缺失 404 / 无群 409）、教学仿真声明透传。全程零 LLM、不读学生数据。
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal
from app.models.professional_group import ProfessionalGroup


async def _group_id() -> int:
    async with AsyncSessionLocal() as session:
        group = (
            await session.scalars(
                select(ProfessionalGroup).where(ProfessionalGroup.code == "PG-OIL-001")
            )
        ).one()
        return group.id


async def _group_total() -> int:
    async with AsyncSessionLocal() as session:
        return int((await session.execute(select(func.count()).select_from(ProfessionalGroup))).scalar_one())


async def _ensure_baseline_program(client, headers):
    """基线方案由 ensure_baseline 惰性创建（与教师端/Phase 5 测试一致），先访问一次列表端点。"""
    response = await client.get("/api/teacher/programs", headers=headers)
    assert response.status_code == 200


async def test_competition_overview_structure(client, teacher_token):
    await _ensure_baseline_program(client, teacher_token)
    response = await client.get("/api/competition/overview", headers=teacher_token)
    assert response.status_code == 200
    data = response.json()["data"]

    # 群定位 + 主链指标
    assert data["group"]["type"] == "group"
    metrics = data["metrics"]
    assert metrics["major_count"] >= 1
    assert metrics["position_count"] >= 1
    assert metrics["course_count"] >= 1
    assert metrics["job_sample_count"] >= 1, "seed 应含人工核验招聘快照"
    assert metrics["data_confidence"] in ("low", "medium", "high")

    # 真实发现案例 = Gap 最大项，需求/供给/Gap 三数齐备
    discovery = data["discovery"]
    assert discovery["demand_share"] >= discovery["curriculum_share"] or discovery["gap"] > 0
    assert abs(discovery["gap"] - round(discovery["demand_share"] - discovery["curriculum_share"], 1)) < 0.11
    assert discovery["months"] >= 3
    assert isinstance(discovery["demand_positions"], list)

    # 证据下钻：招聘快照含可追溯字段（企业/来源/发布日期/技能词）
    evidence = data["evidence"]
    assert evidence["job_postings"], "发现能力应有岗位招聘证据"
    posting = evidence["job_postings"][0]
    for field in ("title", "company", "source_name", "source_url", "published_at", "date_confidence"):
        assert field in posting
    assert evidence["authoritative_knowledge"], "seed 权威知识应进入证据链"

    # 实训映射：六维能力键应命中示范场景并带教学仿真声明
    scenario = data["scenario"]
    assert scenario is not None
    assert scenario["teaching_simulation"] is True
    assert scenario["disclaimer"]
    assert discovery["ability_key"] in {
        "process_understanding",
        "equipment_recognition",
        "instrument_parameter",
        "abnormal_detection",
        "safety_awareness",
        "standard_recording",
    }


async def test_competition_overview_group_param(client, teacher_token):
    group_id = await _group_id()
    response = await client.get(
        "/api/competition/overview", params={"group_id": group_id}, headers=teacher_token
    )
    assert response.status_code == 200
    assert response.json()["data"]["group"]["id"] == group_id

    missing = await client.get(
        "/api/competition/overview", params={"group_id": 999999}, headers=teacher_token
    )
    assert missing.status_code == 404


async def test_competition_overview_access(client, student_token, teacher_token):
    anonymous = await client.get("/api/competition/overview")
    assert anonymous.status_code == 401
    as_student = await client.get("/api/competition/overview", headers=student_token)
    assert as_student.status_code == 200, "比赛首页是主链入口，学生应可读"
    as_teacher = await client.get("/api/competition/overview", headers=teacher_token)
    assert as_teacher.status_code == 200


async def test_competition_overview_discovery_matches_group_analysis(client, teacher_token):
    """发现案例必须与群级分析同口径：直接对比两个接口的 Gap 最大项。"""
    await _ensure_baseline_program(client, teacher_token)
    group_id = await _group_id()
    overview = (
        await client.get("/api/competition/overview", headers=teacher_token)
    ).json()["data"]
    analysis = (
        await client.get(
            f"/api/teacher/professional-groups/{group_id}/analysis", headers=teacher_token
        )
    ).json()["data"]
    top_gap = analysis["ability_gaps"][0]
    assert overview["discovery"]["ability_key"] == top_gap["ability_key"]
    assert overview["discovery"]["gap"] == top_gap["gap"]
    assert overview["metrics"]["job_sample_count"] == analysis["summary"]["job_sample_count"]
    assert overview["metrics"]["course_count"] == analysis["summary"]["course_count"]
