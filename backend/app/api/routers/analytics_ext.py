"""教学效果评估与数据集治理路由（P1-1/P1-2，§45~§50）。

GET /api/teacher/dataset-overview   — 可信数据集规模与来源分类（§46~§48）
GET /api/teacher/effect-overview    — 五项教学效果真实指标（§49~§50）

均为教师/管理员只读端点，受 analytics 功能开关约束；纯 SQL 聚合，不经 LLM。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import ok
from app.api.deps import DBSession, TeacherUser
from app.services.admin_governance import enforce_feature
from app.services.dataset_governance import DatasetGovernanceService
from app.services.teaching_effect import TeachingEffectService

router = APIRouter(prefix="/teacher/analytics-ext", tags=["teacher-analytics"])

_dataset_service = DatasetGovernanceService()
_effect_service = TeachingEffectService()


@router.get("/dataset-overview", summary="可信数据集总览（规模 + 来源分类 + 溯源说明）")
async def get_dataset_overview(user: TeacherUser, session: DBSession) -> dict:
    """数据集规模统计与四类数据来源分布；对照 §46 建议规模如实展示缺口。"""
    await enforce_feature(session, user, "analytics")
    overview = await _dataset_service.dataset_overview(session)
    overview["samples"] = await _dataset_service.sample_evidence_refs(session, limit=10)
    return ok(overview)


@router.get("/effect-overview", summary="教学效果指标（AI 题库一次通过率等五项，真实数据）")
async def get_effect_overview(user: TeacherUser, session: DBSession) -> dict:
    """效果统计全部从既有审核记录推导；样本不足时 rate=null，不预设数字。"""
    await enforce_feature(session, user, "analytics")
    return ok(await _effect_service.effect_overview(session))


__all__ = ["router"]
