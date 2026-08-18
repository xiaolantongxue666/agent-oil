"""能力画像集成测试（PHASE 9）。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_ability_profile_requires_auth(client):
    r = await client.get("/api/ability/profile")
    assert r.status_code == 401


async def test_ability_profile_empty(client, student_token):
    """新学生没有训练历史，画像全为 0。"""
    r = await client.get("/api/ability/profile", headers=student_token)
    assert r.status_code == 200
    profile = r.json()["data"]
    # 应该有六维能力
    assert "process_understanding" in profile
    assert "safety_awareness" in profile
    # 全部为 0（无训练历史）
    for key, dim in profile.items():
        assert dim["score"] == 0.0
        assert dim["attempt_count"] == 0
        assert "name" in dim


async def test_ability_radar_empty(client, student_token):
    r = await client.get("/api/ability/radar", headers=student_token)
    assert r.status_code == 200
    radar = r.json()["data"]
    assert len(radar["labels"]) == 6
    assert len(radar["scores"]) == 6
    assert all(s == 0 for s in radar["scores"])


async def test_ability_history_empty(client, student_token):
    r = await client.get("/api/ability/history", headers=student_token)
    assert r.status_code == 200
    history = r.json()["data"]
    assert isinstance(history, list)


async def test_ability_updates_after_training(client, student_token):
    """完成训练后能力画像应更新。"""
    # 获取任务信息
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
        option = next((item for item in question["options"] if item["key"] == "B"), question["options"][0])
        r = await client.post(
            f"/api/training/{sid}/answer-choice",
            json={"question_id": question["id"], "option_id": option["id"]},
            headers=student_token,
        )
        d = r.json()["data"]
        if d["finished"]:
            break

    # 检查能力画像
    r = await client.get("/api/ability/profile", headers=student_token)
    assert r.status_code == 200
    profile = r.json()["data"]
    # 至少有一个维度分数 > 0
    scores = [dim["score"] for dim in profile.values()]
    assert any(s > 0 for s in scores), f"训练后至少一个能力维度应 >0: {scores}"

    # 检查历史
    r = await client.get("/api/ability/history", headers=student_token)
    assert r.status_code == 200
    history = r.json()["data"]
    assert len(history) > 0
    h0 = history[0]
    assert "ability_key" in h0
    assert "before_score" in h0
    assert "after_score" in h0
    assert h0["after_score"] > h0["before_score"] or h0["after_score"] == h0["before_score"]

    # 检查雷达图
    r = await client.get("/api/ability/radar", headers=student_token)
    assert r.status_code == 200
    radar = r.json()["data"]
    assert len(radar["labels"]) == 6
    assert any(s > 0 for s in radar["scores"])
