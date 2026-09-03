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


async def _run_training_until_last(client, token):
    """开题并把除最后一题外的所有题正常答完，返回 (session_id, 当前会话数据, 任务)。"""
    tasks = (await client.get("/api/training/tasks", headers=token)).json()["data"]
    task = tasks[0]
    d = (
        await client.post(
            "/api/training/start", json={"task_code": task["code"]}, headers=token
        )
    ).json()["data"]
    sid = d["id"]
    for _ in range(task["question_count"] - 1):
        question = d["current_question"]
        option = next(
            (item for item in question["options"] if item["key"] == "B"),
            question["options"][0],
        )
        d = (
            await client.post(
                f"/api/training/{sid}/answer-choice",
                json={"question_id": question["id"], "option_id": option["id"]},
                headers=token,
            )
        ).json()["data"]
    return sid, d, task


def _pick_option(question):
    return next(
        (item for item in question["options"] if item["key"] == "B"),
        question["options"][0],
    )


async def _submit_final(client, token, sid, d):
    question = d["current_question"]
    option = _pick_option(question)
    resp = await client.post(
        f"/api/training/{sid}/answer-choice",
        json={"question_id": question["id"], "option_id": option["id"]},
        headers=token,
    )
    return resp


async def test_completion_persists_evaluation_and_single_evidence_per_dimension(
    client, student_token
):
    """场景 1+3：正常完成 → EvaluationResult 与 AbilityEvidence 同时存在，且同会话同维度不重复。"""
    sid, d, _task = await _run_training_until_last(client, student_token)
    final = (await _submit_final(client, token=student_token, sid=sid, d=d)).json()["data"]
    assert final["finished"] is True
    assert final["evaluation"] is not None

    evidence = (await client.get("/api/ability/evidence", headers=student_token)).json()["data"]
    mine = [item for item in evidence["items"] if item["source_id"] == sid]
    assert mine, "训练完成后 AbilityEvidence 必须存在"
    keys = [item["ability_key"] for item in mine]
    assert len(keys) == len(set(keys)), "同一次训练不允许对同一维度产生重复证据"


async def test_evidence_failure_never_silently_completes(client, student_token, monkeypatch):
    """场景 2：AbilityEvidence 写入失败 → 交卷事务回滚，不能出现"有评价无证据"的静默成功。"""
    from app.services.ability_profile import AbilityProfileService

    sid, d, _task = await _run_training_until_last(client, student_token)

    async def boom(*args, **kwargs):
        raise RuntimeError("simulated evidence write failure")

    monkeypatch.setattr(AbilityProfileService, "update_from_training", boom)
    try:
        resp = await _submit_final(client, token=student_token, sid=sid, d=d)
        # ASGITransport 可能透传异常或返回 500，两者都算"未静默成功"
        assert resp.status_code == 500, f"证据写入失败却返回 {resp.status_code}"
    except RuntimeError as exc:
        assert "simulated evidence write failure" in str(exc)
    finally:
        monkeypatch.undo()

    # 事务已回滚：会话未完成、无 EvaluationResult、无本会话证据
    detail = (await client.get(f"/api/training/{sid}", headers=student_token)).json()["data"]
    assert detail["finished"] is False
    assert detail["evaluation"] is None
    evidence = (await client.get("/api/ability/evidence", headers=student_token)).json()["data"]
    assert all(item["source_id"] != sid for item in evidence["items"])

    # 恢复后可重新提交最后一题，链路完整闭合
    final = (await _submit_final(client, token=student_token, sid=sid, d=d)).json()["data"]
    assert final["finished"] is True
    assert final["evaluation"] is not None
    evidence = (await client.get("/api/ability/evidence", headers=student_token)).json()["data"]
    assert any(item["source_id"] == sid for item in evidence["items"])
