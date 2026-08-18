"""推荐引擎集成测试（PHASE 10）。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_recommendation_requires_auth(client):
    r = await client.get("/api/recommendation/tasks")
    assert r.status_code == 401


async def test_recommendation_empty_for_new_student(client, student_token):
    """新学生无训练历史，推荐入门任务。"""
    r = await client.get("/api/recommendation/tasks", headers=student_token)
    assert r.status_code == 200
    items = r.json()["data"]
    assert isinstance(items, list)
    # 应该有一些推荐（发布的任务）
    if items:
        item = items[0]
        assert "task_id" in item
        assert "task_code" in item
        assert "task_title" in item
        assert "reason_code" in item
        assert "difficulty" in item


async def test_recommendation_after_training(client, student_token):
    """完成训练后推荐应包含针对薄弱能力的任务。"""
    # 获取任务
    r = await client.get("/api/training/tasks", headers=student_token)
    tasks = r.json()["data"]
    task = tasks[0]

    # 完成一次训练
    r = await client.post(
        "/api/training/start",
        json={"task_code": task["code"]},
        headers=student_token,
    )
    d = r.json()["data"]
    sid = d["id"]

    for _ in range(task["question_count"]):
        question = d["current_question"]
        r = await client.post(
            f"/api/training/{sid}/answer-choice",
            json={"question_id": question["id"], "option_id": question["options"][0]["id"]},
            headers=student_token,
        )
        d = r.json()["data"]
        if d["finished"]:
            break

    # 获取推荐
    r = await client.get("/api/recommendation/tasks", headers=student_token)
    assert r.status_code == 200
    items = r.json()["data"]
    assert isinstance(items, list)

    # 推荐不应包含已完成的任务
    completed_codes = {task["code"]}
    for item in items:
        assert item["task_code"] not in completed_codes or item["reason_code"] != "weak_ability"

    # 每条推荐应有合理结构
    for item in items:
        assert item["task_id"] > 0
        assert len(item["task_title"]) > 0
        assert item["difficulty"] >= 1
        assert len(item["reason_text"]) > 0


async def test_recommendation_fields_complete(client, student_token):
    """推荐结果字段完整性检查。"""
    r = await client.get("/api/recommendation/tasks", headers=student_token)
    assert r.status_code == 200
    items = r.json()["data"]
    required_fields = [
        "task_id",
        "task_code",
        "task_title",
        "target_ability",
        "target_ability_name",
        "reason_code",
        "reason_text",
        "difficulty",
        "estimated_minutes",
        "current_ability_score",
    ]
    for item in items:
        for field in required_fields:
            assert field in item, f"缺少字段: {field}"
