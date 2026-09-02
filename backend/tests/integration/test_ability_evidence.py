"""P0-1 能力证据链路集成测试：选择题实训 → AbilityEvidence → 画像/置信度/成长 XP。

注意：集成库为 session 级共享（bootstrap 只 seed 一次），本文件所有断言
不得假设学生是"零证据"状态，只断言训练一次后的增量与结构。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

_PROFILE_NEW_KEYS = (
    "growth_xp",
    "confidence",
    "evidence_count",
    "evidence_type_count",
    "last_evaluated_at",
)


async def _finish_training(client, token) -> None:
    tasks = (await client.get("/api/training/tasks", headers=token)).json()["data"]
    task = tasks[0]
    d = (
        await client.post(
            "/api/training/start", json={"task_code": task["code"]}, headers=token
        )
    ).json()["data"]
    for _ in range(task["question_count"]):
        question = d["current_question"]
        option = next(
            (item for item in question["options"] if item["key"] == "B"),
            question["options"][0],
        )
        d = (
            await client.post(
                f"/api/training/{d['id']}/answer-choice",
                json={"question_id": question["id"], "option_id": option["id"]},
                headers=token,
            )
        ).json()["data"]
        if d["finished"]:
            return


async def test_profile_shape_backwards_compatible(client, student_token):
    """画像仍是六维结构且保留旧字段（name/score/attempt_count/weight）。"""
    r = await client.get("/api/ability/profile", headers=student_token)
    assert r.status_code == 200
    profile = r.json()["data"]
    assert len(profile) == 6
    for dim in profile.values():
        assert {"name", "score", "attempt_count", "weight"} <= set(dim)
        assert set(_PROFILE_NEW_KEYS) <= set(dim)
        assert dim["confidence"] in ("low", "medium", "high")


async def test_evidence_endpoints_require_auth(client):
    assert (await client.get("/api/ability/evidence")).status_code == 401
    assert (await client.get("/api/ability/growth")).status_code == 401


async def test_training_produces_ability_evidence(client, student_token):
    """完成一次选择题实训后：证据落库、画像带置信度与证据数、成长 XP 增加。"""
    before_growth = (
        await client.get("/api/ability/growth", headers=student_token)
    ).json()["data"]

    await _finish_training(client, student_token)

    evidence = (
        await client.get("/api/ability/evidence", headers=student_token)
    ).json()["data"]
    assert evidence["total_returned"] > 0
    assert "scenario_choice" in evidence["by_source_type"]
    item = evidence["items"][0]
    assert item["ability_key"]
    assert 0.0 <= item["raw_score"] <= 100.0
    assert 0.0 < item["evidence_weight"] <= 1.0
    assert 0.0 <= item["final_score"] <= 100.0
    assert item["source_id"] is not None  # 关联训练会话

    profile = (await client.get("/api/ability/profile", headers=student_token)).json()["data"]
    updated = [dim for dim in profile.values() if dim["evidence_count"] > 0]
    assert updated, "训练后至少一个维度应有证据计数"
    for dim in updated:
        assert dim["last_evaluated_at"] is not None
        assert dim["growth_xp"] > 0

    after_growth = (
        await client.get("/api/ability/growth", headers=student_token)
    ).json()["data"]
    assert after_growth["total_xp"] > before_growth["total_xp"]
    assert after_growth["growth_level"] >= 1
    assert after_growth["total_evidence"] == sum(d["evidence_count"] for d in profile.values())


async def test_evidence_filter_by_ability_key(client, student_token):
    profile = (await client.get("/api/ability/profile", headers=student_token)).json()["data"]
    keyed = next((k for k, d in profile.items() if d["evidence_count"] > 0), None)
    if keyed is None:
        pytest.skip("画像尚无证据，跳过筛选断言")
    data = (
        await client.get(
            f"/api/ability/evidence?ability_key={keyed}", headers=student_token
        )
    ).json()["data"]
    assert data["items"]
    assert all(item["ability_key"] == keyed for item in data["items"])
