"""实训推荐在全部任务完成后的复训兜底。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.recommendation import RecommendationService


@pytest.mark.asyncio
async def test_retry_fallback_selects_completed_task_for_weakest_ability() -> None:
    service = RecommendationService()
    tasks = [
        SimpleNamespace(
            id=6,
            code="TT-06",
            title="HSE 风险辨识训练",
            target_abilities=["safety_awareness"],
            difficulty=3,
            estimated_minutes=20,
        ),
        SimpleNamespace(
            id=7,
            code="TT-07",
            title="巡检记录规范训练",
            target_abilities=["standard_recording"],
            difficulty=2,
            estimated_minutes=15,
        ),
    ]
    scalar_result = SimpleNamespace(all=lambda: tasks)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: scalar_result))
    )

    recommendations = await service._recommend_retry_tasks(
        db,
        {6, 7},
        {
            "safety_awareness": {"name": "安全风险辨识", "score": 52.0},
            "standard_recording": {"name": "规范表达与记录", "score": 48.0},
        },
    )

    assert len(recommendations) == 1
    item = recommendations[0]
    assert item.task_code == "TT-07"
    assert item.reason_code == "retry"
    assert item.target_ability == "standard_recording"
    assert "复训" in item.reason_text


@pytest.mark.asyncio
async def test_generate_recommendations_uses_retry_only_after_normal_candidates_empty() -> None:
    service = RecommendationService()
    retry_item = SimpleNamespace(reason_code="retry")
    service._get_ability_scores = AsyncMock(
        return_value={"safety_awareness": {"name": "安全风险辨识", "score": 50.0}}
    )
    service._get_completed_task_ids = AsyncMock(return_value={6})
    service._find_tasks_for_ability = AsyncMock(return_value=[])
    service._fill_remaining_tasks = AsyncMock(return_value=[])
    service._recommend_retry_tasks = AsyncMock(return_value=[retry_item])

    result = await service.generate_recommendations(AsyncMock(), 1)

    assert result == [retry_item]
    service._recommend_retry_tasks.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_recommendations_retries_when_beginner_candidates_empty() -> None:
    service = RecommendationService()
    db = AsyncMock()
    retry_item = SimpleNamespace(reason_code="retry")
    service._get_ability_scores = AsyncMock(return_value={})
    service._recommend_beginner_tasks = AsyncMock(return_value=[])
    service._get_completed_task_ids = AsyncMock(return_value={6})
    service._recommend_retry_tasks = AsyncMock(return_value=[retry_item])

    result = await service.generate_recommendations(db, 1)

    assert result == [retry_item]
    service._recommend_retry_tasks.assert_awaited_once_with(db, {6}, {})


@pytest.mark.asyncio
async def test_generate_recommendations_retries_when_advanced_candidates_empty() -> None:
    service = RecommendationService()
    db = AsyncMock()
    scores = {"safety_awareness": {"name": "安全风险辨识", "score": 90.0}}
    retry_item = SimpleNamespace(reason_code="retry")
    service._get_ability_scores = AsyncMock(return_value=scores)
    service._recommend_advanced_tasks = AsyncMock(return_value=[])
    service._get_completed_task_ids = AsyncMock(return_value={6})
    service._recommend_retry_tasks = AsyncMock(return_value=[retry_item])

    result = await service.generate_recommendations(db, 1)

    assert result == [retry_item]
    service._recommend_retry_tasks.assert_awaited_once_with(db, {6}, scores)
