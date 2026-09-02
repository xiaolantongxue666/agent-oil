"""比赛模式首页聚合 API（P0-4 Phase 7，§35~§39）。

GET /api/competition/overview — 比赛总览：主链指标 + 真实发现案例 + 证据下钻 + 实训映射。
数据全部来自既有确定性分析（群级 Gap）与真实证据表，不含前端写死或伪造数据；
不读学生数据、不经 LLM。

权限：登录用户可访问（比赛首页是"评委理解闭环"入口，学生也要从主链跳实训）。
教师/管理员额外受 analytics 功能开关约束；学生放行只读视图（与群级分析不读学生
数据的边界一致，不暴露任何他人成绩）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.api.response import AppError
from app.models.professional_group import ProfessionalGroup
from app.services.admin_governance import enforce_feature
from app.services.competition_overview import CompetitionOverviewService

router = APIRouter(prefix="/competition", tags=["competition"])
service = CompetitionOverviewService()


@router.get("/overview", summary="比赛模式总览（主链指标 + 真实发现案例 + 证据链）")
async def get_competition_overview(
    user: CurrentUser,
    session: DBSession,
    group_id: int | None = Query(default=None, description="专业群 ID，默认取第一个已发布群"),
    months: int = Query(default=12, ge=3, le=36),
) -> dict:
    """比赛总览聚合。未传 group_id 时按 id 顺序取第一个已发布专业群。"""
    if user.get("role") in ("teacher", "admin"):
        await enforce_feature(session, user, "analytics")
    if group_id is None:
        group = (
            await session.execute(
                select(ProfessionalGroup)
                .where(ProfessionalGroup.status == "published")
                .order_by(ProfessionalGroup.id)
            )
        ).scalars().first()
        if group is None:
            raise AppError("COMPETITION_NO_GROUP", "暂无已发布专业群，请先完成专业群配置", 409)
        group_id = group.id
    return ok(await service.build_overview(session, group_id, months))


__all__ = ["router"]
