"""P0-3 Phase 5：专业群/专业级产业-课程能力聚合分析。

覆盖：群级 analyze_group 聚合结构（需求/供给/Gap/共享与特色能力）、
课程能力矩阵（分值来自 ability_weights 归一）、专业级 analyze_major、
访问控制与 404/409 边界。seed 环境：1 个群 / 4 个专业 / 核心专业挂基线方案。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.enums import AbilityKey
from app.db.session import AsyncSessionLocal
from app.models.professional_group import Major, ProfessionalGroup
from app.services.professional_group_analysis import (
    MATRIX_MAX_SCORE,
    _classify_abilities,
    _latest_published_programs,
)

KNOWN_ABILITY_KEYS = {k.value for k in AbilityKey}


async def _core_major_id() -> int:
    async with AsyncSessionLocal() as session:
        major = (
            await session.scalars(select(Major).where(Major.code == "MAJOR-OIL-STORAGE"))
        ).one()
        return major.id


async def _group_id() -> int:
    async with AsyncSessionLocal() as session:
        group = (
            await session.scalars(
                select(ProfessionalGroup).where(ProfessionalGroup.code == "PG-OIL-001")
            )
        ).one()
        return group.id


async def _ensure_baseline_program(teacher_token_holder):
    """基线方案由 ensure_baseline 惰性创建（与教师端一致），先访问一次列表端点。"""
    client, headers = teacher_token_holder
    response = await client.get("/api/teacher/programs", headers=headers)
    assert response.status_code == 200


async def test_group_analysis_structure_and_gap_math(client, teacher_token):
    await _ensure_baseline_program((client, teacher_token))
    group_id = await _group_id()
    response = await client.get(
        f"/api/teacher/professional-groups/{group_id}/analysis", headers=teacher_token
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scope"]["target"]["type"] == "group"
    assert data["scope"]["target"]["id"] == group_id
    assert "不读取学生实训成绩" in data["scope"]["data_boundary"]

    summary = data["summary"]
    assert summary["major_count"] == 4
    assert summary["position_count"] >= 1
    assert summary["course_count"] >= 1, "核心专业基线方案应提供课程供给"

    # 产业需求/课程供给归一且逐能力计算 gap = demand − supply
    assert data["industry_demand"]
    for gap in data["ability_gaps"]:
        key = gap["ability_key"]
        assert key in KNOWN_ABILITY_KEYS
        assert abs(gap["gap"] - round(gap["demand_share"] - gap["curriculum_share"], 1)) < 0.11
        assert abs(data["industry_demand"].get(key, 0) - gap["demand_share"]) < 0.11
        assert abs(data["curriculum_supply"].get(key, 0) - gap["curriculum_share"]) < 0.11

    # 最大 Gap 排最前；正 gap 项进入 course_gaps 且带课程覆盖明细或缺失标记
    gaps = [item["gap"] for item in data["ability_gaps"]]
    assert gaps == sorted(gaps, reverse=True)
    for item in data["course_gaps"]:
        assert item["gap"] > 0
        assert isinstance(item["has_coverage"], bool)

    # 每个专业的需求画像与计数
    assert len(data["majors"]) == 4
    core = next(m for m in data["majors"] if m["is_core_major"])
    assert core["position_count"] >= 1 and core["program_count"] >= 1

    # 培养建议由规则生成且不为空（走既有 build_actions 规则）
    assert isinstance(data["recommendations"], list) and data["recommendations"]
    # 证据链至少包含权威知识（seed 权威知识 > 50）
    ref_types = {item["type"] for item in data["evidence_refs"]}
    assert "authoritative_knowledge" in ref_types


async def test_group_analysis_shared_and_specific_abilities(client, teacher_token):
    """seed 权重：safety_awareness 15/25/10/35（极差 25 → 特色），非共享；
    standard_recording 10/10/10/10（极差 0 → 共享）。"""
    group_id = await _group_id()
    response = await client.get(
        f"/api/teacher/professional-groups/{group_id}/analysis", headers=teacher_token
    )
    data = response.json()["data"]
    shared_keys = {item["ability_key"] for item in data["shared_abilities"]}
    specific = {item["ability_key"]: item for item in data["major_specific_abilities"]}
    assert "standard_recording" in shared_keys, "四专业权重一致的能力应判为群共享"
    assert "safety_awareness" in specific, "安全技术与管理显著领先的能力应判为特色能力"
    leader = specific["safety_awareness"]
    assert leader["major_name"] == "安全技术与管理"
    assert leader["weight"] == 35
    for item in data["shared_abilities"]:
        low, high = item["weight_range"]
        assert high - low <= 10.0


async def test_course_matrix_values_from_ability_weights(client, teacher_token):
    await _ensure_baseline_program((client, teacher_token))
    group_id = await _group_id()
    response = await client.get(
        f"/api/teacher/professional-groups/{group_id}/course-matrix", headers=teacher_token
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["group"]["code"] == "PG-OIL-001"
    assert {item["key"] for item in data["abilities"]} == KNOWN_ABILITY_KEYS
    assert data["max_score"] == MATRIX_MAX_SCORE
    assert data["courses"], "核心专业最新发布方案的课程应出现在矩阵中"

    # 全矩阵最大格子必须等于 max_score（相对最强课程归一）
    all_cells = [cell for course in data["courses"] for cell in course["cells"].values()]
    assert all_cells
    assert max(all_cells) == MATRIX_MAX_SCORE
    for course in data["courses"]:
        for cell in course["cells"].values():
            assert 0 < cell <= MATRIX_MAX_SCORE
        assert course["major_name"] == "油气储运工程" or course["total_hours"] >= 0

    # 课程行必须携带 hour 基本面（供给来源可追溯）
    first = data["courses"][0]
    assert first["total_hours"] > 0 and first["program_name"]


async def test_major_level_analysis_scoped_to_single_major(client, teacher_token):
    core_id = await _core_major_id()
    response = await client.get(
        f"/api/teacher/professional-groups/majors/{core_id}/analysis", headers=teacher_token
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scope"]["target"]["type"] == "major"
    assert data["scope"]["major_count"] == 1
    assert len(data["majors"]) == 1
    assert data["majors"][0]["id"] == core_id
    # 单专业视图仍应有完整 Gap 结构
    assert data["ability_gaps"]
    assert isinstance(data["recommendations"], list)


async def test_group_analysis_access_and_boundary(client, student_token, teacher_token):
    group_id = await _group_id()
    anonymous = await client.get(f"/api/teacher/professional-groups/{group_id}/analysis")
    assert anonymous.status_code == 401
    as_student = await client.get(
        f"/api/teacher/professional-groups/{group_id}/analysis", headers=student_token
    )
    assert as_student.status_code == 403
    missing = await client.get(
        "/api/teacher/professional-groups/999999/analysis", headers=teacher_token
    )
    assert missing.status_code == 404
    missing_matrix = await client.get(
        "/api/teacher/professional-groups/999999/course-matrix", headers=teacher_token
    )
    assert missing_matrix.status_code == 404
    missing_major = await client.get(
        "/api/teacher/professional-groups/majors/999999/analysis", headers=teacher_token
    )
    assert missing_major.status_code == 404


def test_shared_specific_classification_rules():
    """纯规则单元：极差/领先阈值边界。"""
    major_a = _fake_major(1, {"safety_awareness": 30, "standard_recording": 10})
    major_b = _fake_major(2, {"safety_awareness": 22, "standard_recording": 10})
    major_c = _fake_major(3, {"safety_awareness": 30, "standard_recording": 10})
    names = {"safety_awareness": "安全", "standard_recording": "规范"}
    shared, specific = _classify_abilities([major_a, major_b, major_c], names)
    # safety 并列最大（30/30）→ 无唯一领先者，不构成特色；极差 8 ≤ 10 → 共享
    assert "safety_awareness" in {item["ability_key"] for item in shared}
    assert all(item["ability_key"] != "safety_awareness" for item in specific)
    # standard 三专业完全一致 → 共享
    assert "standard_recording" in {item["ability_key"] for item in shared}

    major_d = _fake_major(4, {"safety_awareness": 40, "standard_recording": 10})
    shared2, specific2 = _classify_abilities([major_a, major_d], names)
    # safety 极差 10 ≤ 10 → 共享，同时 30 vs 40 领先 10 ≥ 5 → 也可为特色；standard 完全一致 → 共享
    assert "standard_recording" in {item["ability_key"] for item in shared2}
    leader = next(item for item in specific2 if item["ability_key"] == "safety_awareness")
    assert leader["major_id"] == 4 and leader["weight"] == 40


def test_latest_published_programs_dedup_by_code():
    programs = [
        _fake_program("OGTE-2026", 1, status="archived"),
        _fake_program("OGTE-2026", 2, status="published"),
        _fake_program("OGTE-2026", 3, status="published"),
        _fake_program("OTHER-001", 1, status="published"),
    ]
    latest = _latest_published_programs(programs)
    codes = {p.program_code: p.version for p in latest}
    assert codes == {"OGTE-2026": 3, "OTHER-001": 1}


# ---- 测试辅助（避免为纯函数测试拉起 ORM 会话） ----

def _fake_major(major_id: int, weights: dict[str, float]):
    from types import SimpleNamespace

    return SimpleNamespace(id=major_id, name=f"专业{major_id}", ability_weights=weights)


def _fake_program(code: str, version: int, status: str = "published"):
    from types import SimpleNamespace

    return SimpleNamespace(program_code=code, version=version, status=status)
