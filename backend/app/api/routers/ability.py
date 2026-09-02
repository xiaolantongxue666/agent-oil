"""能力画像路由（P0-1 证据化重构）。

端点：
- GET /api/ability/profile     — 学生当前六维能力画像（水平 + 置信度 + 证据数 + XP）
- GET /api/ability/history     — 能力变更历史
- GET /api/ability/radar       — 雷达图数据（ECharts 兼容格式）
- GET /api/ability/evidence    — 技能证据档案（证据时间线 + 来源汇总）
- GET /api/ability/growth      — 成长 XP / 等级汇总
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.services.ability_profile import AbilityProfileService

router = APIRouter(prefix="/ability", tags=["ability"])

_service = AbilityProfileService()


@router.get("/profile", summary="当前能力画像")
async def get_profile(user: CurrentUser, session: DBSession) -> dict:
    uid = int(user["user_id"])
    profile = await _service.get_profile(session, uid)
    return ok(profile)


@router.get("/history", summary="能力变更历史")
async def get_history(
    user: CurrentUser,
    session: DBSession,
    ability_key: str | None = Query(None, description="筛选特定能力维度"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    uid = int(user["user_id"])
    history = await _service.get_history(session, uid, ability_key=ability_key, limit=limit)
    return ok(history)


@router.get("/radar", summary="雷达图数据")
async def get_radar(user: CurrentUser, session: DBSession) -> dict:
    uid = int(user["user_id"])
    radar = await _service.get_radar_data(session, uid)
    return ok(radar)


@router.get("/evidence", summary="技能证据档案")
async def get_evidence(
    user: CurrentUser,
    session: DBSession,
    ability_key: str | None = Query(None, description="筛选特定能力维度"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    uid = int(user["user_id"])
    evidence = await _service.get_evidence(session, uid, ability_key=ability_key, limit=limit)
    return ok(evidence)


@router.get("/growth", summary="成长 XP 与等级")
async def get_growth(user: CurrentUser, session: DBSession) -> dict:
    uid = int(user["user_id"])
    growth = await _service.get_growth(session, uid)
    return ok(growth)


__all__ = ["router"]
