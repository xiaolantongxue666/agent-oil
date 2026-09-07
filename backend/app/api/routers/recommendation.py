"""推荐路由（PHASE 10）。

端点：
- GET /api/recommendation/tasks — 个性化推荐任务列表
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.services.recommendation import RecommendationService
from app.services.adaptive_learning import AdaptiveLearningService

router = APIRouter(prefix="/recommendation", tags=["recommendation"])

_service = RecommendationService()
_adaptive_service = AdaptiveLearningService()


@router.get("/tasks", summary="个性化推荐任务")
async def get_recommendations(user: CurrentUser, session: DBSession) -> dict:
    uid = int(user["user_id"])
    items = await _service.generate_recommendations(session, uid)
    out = [
        {
            "task_id": item.task_id,
            "task_code": item.task_code,
            "task_title": item.task_title,
            "target_ability": item.target_ability,
            "target_ability_name": item.target_ability_name,
            "reason_code": item.reason_code,
            "reason_text": item.reason_text,
            "difficulty": item.difficulty,
            "estimated_minutes": item.estimated_minutes,
            "current_ability_score": item.current_ability_score,
            # R045：任务真实活动类型（simulation 的 route 由 scenario_code 承载）
            "activity_type": item.activity_type,
            "scenario_code": item.scenario_code,
        }
        for item in items
    ]
    return ok(out)


@router.get("/adaptive-path", summary="学生个性化自适应学习路径")
async def get_adaptive_path(user: CurrentUser, session: DBSession) -> dict:
    """实训结果只在这里转化为个人掌握度和补学重练路径。"""
    return ok(await _adaptive_service.build_path(session, int(user["user_id"])))


__all__ = ["router"]
