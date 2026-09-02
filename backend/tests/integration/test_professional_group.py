"""P0-3 Phase 4：专业群数据模型与兼容链路。

覆盖：seed 群/专业结构与权重合法性、旧数据 major_id 回填、
CurriculumProgram/Position 字符串列兼容、只读 API 与角色守卫。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.enums import AbilityKey
from app.db.session import AsyncSessionLocal
from app.models.curriculum import CurriculumProgram
from app.models.position import Position
from app.models.professional_group import Major, ProfessionalGroup

KNOWN_ABILITY_KEYS = {k.value for k in AbilityKey}


async def _core_major_id() -> int:
    async with AsyncSessionLocal() as session:
        major = (
            await session.scalars(select(Major).where(Major.code == "MAJOR-OIL-STORAGE"))
        ).one()
        return major.id


async def test_seeded_group_and_majors_are_valid():
    async with AsyncSessionLocal() as session:
        group = (
            await session.scalars(
                select(ProfessionalGroup).where(ProfessionalGroup.code == "PG-OIL-001")
            )
        ).one()
        majors = (
            await session.scalars(
                select(Major).where(Major.professional_group_id == group.id).order_by(Major.id)
            )
        ).all()
        assert len(majors) == 4, "示范专业群应有 4 个专业"
        assert sum(1 for m in majors if m.is_core_major) == 1, "有且仅有一个核心专业"
        for major in majors:
            weights = major.ability_weights or {}
            assert set(weights) == KNOWN_ABILITY_KEYS, (
                f"专业 {major.code} 必须复用六维能力键，不得另造字典"
            )
            assert abs(sum(weights.values()) - 100) < 1e-9, f"专业 {major.code} 权重合计应为 100"


async def test_legacy_positions_and_program_backfilled_with_compat_string_kept():
    core_id = await _core_major_id()
    async with AsyncSessionLocal() as session:
        # 种子岗位均为"油气储运工程"，回填后全部挂到核心专业，且字符串列原样保留
        positions = (await session.scalars(select(Position))).all()
        assert positions
        for position in positions:
            assert position.major == "油气储运工程"
            assert position.major_id == core_id
        # 基线方案（ensure_baseline 惰性建）与旧方案：字符串列仍是权威兼容字段
        programs = (
            await session.scalars(
                select(CurriculumProgram).where(CurriculumProgram.major == "油气储运工程")
            )
        ).all()
        for program in programs:
            assert program.major_id in (None, core_id)


async def test_program_endpoint_exposes_major_id_compat(client, teacher_token):
    response = await client.get("/api/teacher/programs", headers=teacher_token)
    assert response.status_code == 200
    programs = response.json()["data"]
    assert programs
    core_id = await _core_major_id()
    # 刚触发 ensure_baseline 的基线（或既有最新版本）必须已挂接核心专业
    assert all(
        item["major_id"] == core_id for item in programs if item["major"] == "油气储运工程"
    )
    assert all("major" in item and "major_id" in item for item in programs)


async def test_professional_group_list_and_detail_api(client, teacher_token):
    response = await client.get("/api/teacher/professional-groups", headers=teacher_token)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    groups = payload["data"]
    assert groups and groups[0]["code"] == "PG-OIL-001"
    assert len(groups[0]["majors"]) == 4

    detail = await client.get(
        f"/api/teacher/professional-groups/{groups[0]['id']}", headers=teacher_token
    )
    assert detail.status_code == 200
    body = detail.json()["data"]
    assert body["major_count"] == 4
    core = next(m for m in body["majors"] if m["is_core_major"])
    assert core["code"] == "MAJOR-OIL-STORAGE"
    assert core["position_count"] >= 1, "核心专业应能通过 major_id 下钻到岗位"


async def test_professional_group_api_access_control(client, student_token, teacher_token):
    anonymous = await client.get("/api/teacher/professional-groups")
    assert anonymous.status_code == 401
    as_student = await client.get(
        "/api/teacher/professional-groups", headers=student_token
    )
    assert as_student.status_code == 403
    missing = await client.get(
        "/api/teacher/professional-groups/999999", headers=teacher_token
    )
    assert missing.status_code == 404
