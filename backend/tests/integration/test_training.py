"""数据驱动选择题实训集成测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _finish_session(client, token, data: dict) -> dict:
    for _ in range(data["question_count"]):
        question = data["current_question"]
        response = await client.post(
            f"/api/training/{data['id']}/answer-choice",
            json={"question_id": question["id"], "option_id": question["options"][0]["id"]},
            headers=token,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["last_answer_feedback"] is not None
        if data["finished"]:
            return data
    return data


async def test_training_requires_auth(client):
    response = await client.post("/api/training/start", json={"task_code": "TT-01"})
    assert response.status_code == 401


async def test_list_tasks_requires_auth(client):
    response = await client.get("/api/training/tasks")
    assert response.status_code == 401


async def test_list_tasks(client, student_token):
    response = await client.get("/api/training/tasks", headers=student_token)
    assert response.status_code == 200
    tasks = response.json()["data"]
    assert len(tasks) >= 8
    assert tasks[0]["mode"] == "choice"
    assert tasks[0]["question_count"] >= 3


async def test_start_training_hides_scoring_keys(client, student_token):
    response = await client.post(
        "/api/training/start", json={"task_code": "TT-01"}, headers=student_token
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["stage"] == "answering"
    assert data["mode"] == "choice"
    assert data["scenario_text"]
    assert data["current_question"]["options"]
    assert all(
        "score" not in option and "is_correct" not in option
        for option in data["current_question"]["options"]
    )
    assert data["evidence_citations"]
    assert all(item["source_no"] and item["page"] for item in data["evidence_citations"])


async def test_non_primary_task_has_persisted_scenario_and_question(client, student_token):
    response = await client.post(
        "/api/training/start", json={"task_code": "TT-04"}, headers=student_token
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "仪表" in data["scenario_text"]
    assert "参数" in data["current_question"]["stem"] or data["current_question"]["knowledge_point"]


async def test_start_bad_task(client, student_token):
    response = await client.post(
        "/api/training/start", json={"task_code": "NONEXISTENT"}, headers=student_token
    )
    assert response.status_code == 404


async def test_full_choice_training_flow(client, student_token):
    tasks = (await client.get("/api/training/tasks", headers=student_token)).json()["data"]
    response = await client.post(
        "/api/training/start", json={"task_code": tasks[0]["code"]}, headers=student_token
    )
    data = await _finish_session(client, student_token, response.json()["data"])
    assert data["finished"] is True

    detail = (await client.get(f"/api/training/{data['id']}", headers=student_token)).json()["data"]
    assert detail["stage"] == "finished"
    assert len(detail["answer_records"]) == detail["question_count"]
    evaluation = detail["evaluation"]
    assert evaluation["rule_score"] == evaluation["final_score"]
    assert evaluation["semantic_score"] == 0
    assert evaluation["llm_score"] == 0
    assert evaluation["scoring_mode"] == "database_choice_rule"
    assert evaluation["citations"]


async def test_rejects_skipping_question(client, student_token):
    data = (
        await client.post(
            "/api/training/start", json={"task_code": "TT-01"}, headers=student_token
        )
    ).json()["data"]
    response = await client.post(
        f"/api/training/{data['id']}/answer-choice",
        json={"question_id": data["current_question"]["id"] + 1, "option_id": 1},
        headers=student_token,
    )
    assert response.status_code == 409


async def test_submit_after_finished(client, student_token):
    data = (
        await client.post(
            "/api/training/start", json={"task_code": "TT-01"}, headers=student_token
        )
    ).json()["data"]
    data = await _finish_session(client, student_token, data)
    response = await client.post(
        f"/api/training/{data['id']}/answer-choice",
        json={"question_id": 1, "option_id": 1},
        headers=student_token,
    )
    assert response.status_code == 400


async def test_session_list(client, student_token):
    response = await client.get("/api/training/sessions", headers=student_token)
    assert response.status_code == 200
    assert response.json()["data"]
