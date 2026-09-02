"""P0-2 仿真实训端到端集成测试：场景列表 → 开始 → 事件 → 状态机 → 评分 → 能力证据。

集成库 session 级共享（不假设学生零状态），只断言本次会话的确定分值与增量。
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio

SC = "PIPELINE_ABNORMAL_001"
BASE = "/api/training/simulation"


async def _post_event(client, token, sid, event_type, event_code="", target_id="", payload=None):
    return await client.post(
        f"{BASE}/sessions/{sid}/events",
        json={
            "event_type": event_type,
            "event_code": event_code,
            "target_type": "",
            "target_id": target_id,
            "payload": payload or {},
        },
        headers=token,
    )


async def _start_session(client, token):
    r = await client.post(f"{BASE}/{SC}/start", headers=token)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_simulation_list_and_detail_sanitized(client, student_token):
    r = await client.get(BASE, headers=student_token)
    assert r.status_code == 200
    codes = [item["scenario_code"] for item in r.json()["data"]]
    assert SC in codes
    listed = next(i for i in r.json()["data"] if i["scenario_code"] == SC)
    assert listed["teaching_simulation"] is True
    assert "教学仿真" in listed["disclaimer"]

    r = await client.get(f"{BASE}/{SC}", headers=student_token)
    assert r.status_code == 200
    dumped = json.dumps(r.json()["data"], ensure_ascii=False)
    for banned in ('"correct"', '"score"', '"answer"', '"error_type"'):
        assert banned not in dumped


async def test_simulation_requires_auth(client):
    assert (await client.get(BASE)).status_code == 401
    assert (await client.post(f"{BASE}/{SC}/start")).status_code == 401


async def test_simulation_full_flow_scores_and_evidence(client, student_token):
    growth_before = (await client.get("/api/ability/growth", headers=student_token)).json()["data"]
    sess = await _start_session(client, student_token)
    sid = sess["session_id"]
    assert sess["stage"] == "briefing"
    assert sess["scenario_code"] == SC
    assert sess["stage_flow"] == ["briefing", "observe", "diagnose", "risk_assess", "decision", "record", "finished"]

    # briefing 阶段不允许提交行为事件
    r = await _post_event(client, student_token, sid, "VIEW_TREND", "OBS-PRESSURE-TREND")
    assert r.status_code == 409
    # 阶段推进由后端控制
    r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=student_token)
    assert r.status_code == 200
    assert r.json()["data"]["stage"] == "observe"

    # observe 阶段禁止跨阶段动作
    r = await _post_event(client, student_token, sid, "SUBMIT_DIAGNOSIS", payload={"choice_code": "D2"})
    assert r.status_code == 409
    # gate 未满足不得推进
    r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=student_token)
    assert r.status_code == 409

    # 观察事件（跳过流量趋势 → 扣 4 分且记关键遗漏；错误窗口标记先失败再重做不会，直接做对）
    observe_plan = [
        ("VIEW_PROCESS_FLOW", "OBS-PROCESS-FLOW", "pfd-station", {}),
        ("VIEW_PROCESS_FLOW", "OBS-UPSTREAM-DOWNSTREAM", "segment-up-down", {}),
        ("OPEN_KNOWLEDGE", "OBS-KNOW-CAVITATION", "doc-cavitation", {}),
        ("VIEW_DEVICE_STATUS", "OBS-PUMP-STATUS", "pump-main-01", {}),
        ("VIEW_DEVICE_STATUS", "OBS-INLET-TANK-STATUS", "inlet-tank-01", {}),
        ("VIEW_DEVICE_STATUS", "OBS-VALVE-STATUS", "valve-xv-101", {}),
        ("VIEW_TREND", "OBS-PRESSURE-TREND", "pressure_mpa", {}),
        ("VIEW_TREND", "OBS-LEVEL-TREND", "inlet_level_pct", {}),
        ("VIEW_TREND", "OBS-TEMP-TREND", "temperature_c", {}),
        ("VIEW_ALARM", "OBS-ALARM-LIST", "alarm-current", {}),
        ("MARK_ABNORMAL_POINT", "OBS-MARK-ANOMALY", "pressure_mpa", {"window_start": 12, "window_end": 22}),
    ]
    for event_type, code, target_id, payload in observe_plan:
        r = await _post_event(client, student_token, sid, event_type, code, target_id, payload)
        assert r.status_code == 200, r.text
    # 重复动作只计首次
    r = await _post_event(client, student_token, sid, "VIEW_TREND", "OBS-PRESSURE-TREND", "pressure_mpa")
    assert r.json()["data"]["event"]["raw_score"] == 0.0
    assert r.json()["data"]["event"]["error_type"] == "duplicate_action"

    # 启发式提示不含答案
    r = await client.post(f"{BASE}/sessions/{sid}/hint", headers=student_token)
    assert r.status_code == 200
    assert "启发提示" in r.json()["data"]["hint"]

    r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=student_token)
    assert r.json()["data"]["stage"] == "diagnose"
    # 故意选错诊断 → 0 分但流程可继续
    r = await _post_event(client, student_token, sid, "SUBMIT_DIAGNOSIS", payload={"choice_code": "D1"})
    assert r.json()["data"]["event"]["raw_score"] == 0.0
    assert r.json()["data"]["event"]["error_type"] == "wrong_cause"
    r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=student_token)
    assert r.json()["data"]["stage"] == "risk_assess"
    r = await _post_event(client, student_token, sid, "SUBMIT_RISK_ASSESSMENT", payload={"choice_code": "R1"})
    assert r.json()["data"]["event"]["raw_score"] == 10.0
    await client.post(f"{BASE}/sessions/{sid}/advance", headers=student_token)
    r = await _post_event(client, student_token, sid, "SUBMIT_DECISION", payload={"choice_code": "T2"})
    assert r.json()["data"]["event"]["raw_score"] == 10.0
    r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=student_token)
    assert r.json()["data"]["stage"] == "record"
    # 记录缺一个必填字段 → 按比例 12/15
    r = await _post_event(
        client, student_token, sid, "SUBMIT_RECORD",
        payload={"fields": {k: "模拟记录内容" for k in [
            "time_phenomenon", "observed_data", "preliminary_cause", "actions_taken",
        ]}},
    )
    assert r.json()["data"]["event"]["raw_score"] == 12.0

    # 完成 → 确定性总分
    r = await client.post(f"{BASE}/sessions/{sid}/complete", headers=student_token)
    assert r.status_code == 200, r.text
    report = r.json()["data"]
    # 100 - 8(错诊断) - 4(漏看流量趋势) - 3(记录缺一项) = 85
    assert report["total_score"] == 85.0
    assert report["dimension_scores"]["abnormal_detection"] == 60.0
    assert report["dimension_scores"]["instrument_parameter"] == 73.33  # 11/15 小数分
    assert report["dimension_scores"]["standard_recording"] == 80.0
    assert "查看流量趋势" in report["missed_critical"]
    error_types = {e["error_type"] for e in report["errors"]}
    assert {"wrong_cause", "incomplete_record"} <= error_types
    assert {ev["source_type"] for ev in report["ability_evidence"]} <= {
        "operation_event", "scenario_diagnosis",
    }
    # §19 完成页契约：能力画像变化（before→after）与置信度随证据回传
    for ev in report["ability_evidence"]:
        assert isinstance(ev["before_score"], (int, float))
        assert isinstance(ev["after_score"], (int, float))
        assert ev["confidence"] in {"low", "medium", "high"}
        assert ev["evidence_count"] >= 1

    # 会话状态：finished + EvaluationResult 分数为真实浮点（不再截断）
    r = await client.get(f"{BASE}/sessions/{sid}", headers=student_token)
    data = r.json()["data"]
    assert data["stage"] == "finished" and data["finished"] is True
    assert data["evaluation"]["final_score"] == 85.0
    assert data["evaluation"]["dimension_scores"]["instrument_parameter"] == 73.33

    # 完成后再操作被状态机拒绝
    r = await _post_event(client, student_token, sid, "VIEW_TREND", "OBS-FLOW-TREND")
    assert r.status_code == 409

    # 能力证据链路：本次仿真产生 scenario_diagnosis + operation_event 证据
    evidence = (await client.get("/api/ability/evidence?ability_key=instrument_parameter", headers=student_token)).json()["data"]
    sim_items = [i for i in evidence["items"] if i["metadata"].get("scenario_code") == SC]
    assert sim_items, "仿真应投递 instrument_parameter 证据"
    assert sim_items[0]["source_type"] == "operation_event"
    assert abs(sim_items[0]["final_score"] - 73.33) < 0.01

    diagnosis_evidence = (await client.get("/api/ability/evidence?ability_key=abnormal_detection", headers=student_token)).json()["data"]
    assert any(
        i["metadata"].get("scenario_code") == SC and i["source_type"] == "scenario_diagnosis"
        for i in diagnosis_evidence["items"]
    )

    profile = (await client.get("/api/ability/profile", headers=student_token)).json()["data"]
    assert profile["abnormal_detection"]["evidence_count"] > 0
    growth_after = (await client.get("/api/ability/growth", headers=student_token)).json()["data"]
    assert growth_after["total_xp"] > growth_before["total_xp"]


async def test_simulation_choice_training_unaffected(client, student_token):
    """回归：仿真任务不得混入选择题任务列表，选择题流程仍正常。"""
    tasks = (await client.get("/api/training/tasks", headers=student_token)).json()["data"]
    assert all(not t["code"].startswith("SIM-") for t in tasks)
