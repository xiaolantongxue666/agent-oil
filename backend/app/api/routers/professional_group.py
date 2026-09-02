"""教师端专业群结构查询与群级能力分析（P0-3 Phase 4/5）。

Phase 4 提供"专业群 → 专业"真实结构的只读视图；
Phase 5 增加群级/专业级产业-课程能力聚合分析（Gap、课程能力矩阵）。
治理沿用 teacher_industry / analytics 功能开关与 TeacherUser 角色守卫，不新增权限面。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import ok
from app.api.deps import DBSession, TeacherUser
from app.api.response import AppError
from app.models.curriculum import CurriculumProgram
from app.models.position import Position
from app.models.professional_group import Major, ProfessionalGroup
from app.services.admin_governance import enforce_feature
from app.services.professional_group_analysis import ProfessionalGroupAnalysisService

router = APIRouter(prefix="/teacher/professional-groups", tags=["teacher-professional-groups"])
analysis_service = ProfessionalGroupAnalysisService()


def _group_out(group: ProfessionalGroup, majors: list[Major]) -> dict[str, Any]:
    return {
        "id": group.id,
        "code": group.code,
        "name": group.name,
        "industry_domain": group.industry_domain,
        "description": group.description,
        "status": group.status,
        "majors": [
            {
                "id": m.id,
                "professional_group_id": m.professional_group_id,
                "code": m.code,
                "name": m.name,
                "is_core_major": m.is_core_major,
                "ability_weights": m.ability_weights or {},
                "description": m.description,
                "status": m.status,
            }
            for m in majors
        ],
    }


async def _load_group(session: AsyncSession, group_id: int) -> ProfessionalGroup:
    group = await session.get(ProfessionalGroup, group_id)
    if not group:
        raise AppError("PROFESSIONAL_GROUP_NOT_FOUND", "专业群不存在", 404)
    return group


@router.get("", summary="专业群列表（含专业）")
async def list_professional_groups(user: TeacherUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "teacher_industry")
    groups = (
        await session.execute(
            select(ProfessionalGroup)
            .where(ProfessionalGroup.status == "published")
            .order_by(ProfessionalGroup.id)
        )
    ).scalars().all()
    majors = (
        await session.execute(select(Major).order_by(Major.professional_group_id, Major.id))
    ).scalars().all()
    by_group: dict[int, list[Major]] = {}
    for major in majors:
        by_group.setdefault(major.professional_group_id, []).append(major)
    return ok([_group_out(group, by_group.get(group.id, [])) for group in groups])


@router.get("/{group_id}", summary="专业群详情（含专业与链接计数）")
async def get_professional_group(group_id: int, user: TeacherUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "teacher_industry")
    group = await _load_group(session, group_id)
    majors = (
        await session.execute(
            select(Major)
            .where(Major.professional_group_id == group.id)
            .order_by(Major.id)
        )
    ).scalars().all()
    program_counts = dict(
        (
            await session.execute(
                select(CurriculumProgram.major_id, func.count())
                .where(CurriculumProgram.major_id.in_([m.id for m in majors]))
                .group_by(CurriculumProgram.major_id)
            )
        ).all()
    )
    position_counts = dict(
        (
            await session.execute(
                select(Position.major_id, func.count())
                .where(Position.major_id.in_([m.id for m in majors]))
                .group_by(Position.major_id)
            )
        ).all()
    )
    payload = _group_out(group, majors)
    for major in payload["majors"]:
        major["program_count"] = int(program_counts.get(major["id"], 0))
        major["position_count"] = int(position_counts.get(major["id"], 0))
    payload["major_count"] = len(payload["majors"])
    return ok(payload)


@router.get("/{group_id}/analysis", summary="专业群产业-课程能力聚合分析（需求/供给/Gap）")
async def get_group_analysis(
    group_id: int,
    user: TeacherUser,
    session: DBSession,
    months: int = Query(default=12, ge=3, le=36),
) -> dict:
    await enforce_feature(session, user, "analytics")
    return ok(await analysis_service.analyze_group(session, group_id, months))


@router.get("/{group_id}/course-matrix", summary="专业群课程能力矩阵（课程 × 六维）")
async def get_group_course_matrix(group_id: int, user: TeacherUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "analytics")
    return ok(await analysis_service.course_matrix(session, group_id))


@router.get("/majors/{major_id}/analysis", summary="专业级产业-课程能力聚合分析")
async def get_major_analysis(
    major_id: int,
    user: TeacherUser,
    session: DBSession,
    months: int = Query(default=12, ge=3, le=36),
) -> dict:
    await enforce_feature(session, user, "analytics")
    return ok(await analysis_service.analyze_major(session, major_id, months))


__all__ = ["router"]
