"""Phase A — 候选场景 B/C 安全发布后的端到端可完成性冒烟（CASE A8 运行层 / D7.5 M4）。

驱动器完全按已发布场景 JSON 构造事件（身份一致的编码 + 正确选项），
复用既有状态机与 gate，不新增场景专用代码路径。
若场景配置与前端条目一致（A8），此链必须 200 并满分完成。
"""

from __future__ import annotations

import pytest

from app.scenarios import get_scenario, load_scenarios

pytestmark = pytest.mark.asyncio

BASE = "/api/training/simulation"
CANDIDATES = ("EQUIPMENT_INSPECTION_PREVIEW_002", "HSE_RECORD_PREVIEW_003")


async def _event(client, token, sid, event_type, event_code="", target_id="", payload=None):
    return await client.post(
        f"{BASE}/sessions/{sid}/events",
        json={"event_type": event_type, "event_code": event_code,
              "target_type": "", "target_id": target_id, "payload": payload or {}},
        headers=token,
    )


async def _run_scenario_to_completion(client, token, code):
    scenario = get_scenario(code)
    assert code in load_scenarios()

    r = await client.post(f"{BASE}/{code}/start", headers=token)
    assert r.status_code == 200, f"已发布场景应可启动：{r.text}"
    sid = r.json()["data"]["session_id"]
    assert r.json()["data"]["stage"] == "briefing"

    r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
    assert r.status_code == 200

    # observe：执行场景定义的全部动作（编码/类型/对象身份一致，即前端操作条目的语义）
    for action in scenario["stages"]["observe"].get("actions") or []:
        payload = {}
        if action.get("event_type") == "MARK_ABNORMAL_POINT":
            answer = action.get("answer") or {}
            lo, hi = float(answer.get("window_min", 0)), float(answer.get("window_max", 0))
            mid = int((lo + hi) // 2)
            payload = {"window_start": mid, "window_end": mid}
        r = await _event(client, token, sid, action["event_type"], action["code"],
                         str(action.get("target_id") or ""), payload)
        assert r.status_code == 200, f"合法动作 {action['code']} 必须被接受：{r.text}"
        assert r.json()["data"]["event"]["is_expected"] is True

    r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
    assert r.status_code == 200, "observe→diagnose gate 应与动作条目一致可达"

    for stage in ("diagnose", "risk_assess", "decision"):
        cfg = scenario["stages"][stage]
        correct = next(o for o in cfg["options"] if o.get("correct"))
        r = await _event(client, token, sid, cfg["allowed_event_types"][0],
                         payload={"choice_code": correct["code"]})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["event"]["raw_score"] == pytest.approx(
            float(next(a for a in cfg["actions"] if a["code"] == cfg["event_code"])["points"]))
        r = await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
        assert r.status_code == 200

    record_cfg = scenario["stages"]["record"]
    fields = {k: f"教学模拟记录-{k}" for k in record_cfg["required_fields"]}
    r = await _event(client, token, sid, "SUBMIT_RECORD", payload={"fields": fields})
    assert r.status_code == 200, r.text

    r = await client.post(f"{BASE}/sessions/{sid}/complete", headers=token)
    assert r.status_code == 200, r.text
    return r.json()["data"]


@pytest.mark.parametrize("code", CANDIDATES)
async def test_candidate_scenario_completes_full_marks(client, student_token, code):
    report = await _run_scenario_to_completion(client, student_token, code)
    assert report["total_score"] == 100.0, report
    assert all(v == 100.0 for v in report["dimension_scores"].values())
    assert set(report["dimension_scores"]) == {
        "process_understanding", "equipment_recognition", "instrument_parameter",
        "abnormal_detection", "safety_awareness", "standard_recording",
    }
    assert len(report["ability_evidence"]) == 6
    assert not report["missed_critical"]
    for ev in report["ability_evidence"]:
        assert ev["confidence"] in {"low", "medium", "high"}


async def test_candidate_sim_tasks_not_leaked_into_choice_list(client, student_token):
    tasks = (await client.get("/api/training/tasks", headers=student_token)).json()["data"]
    assert all(not t["code"].startswith("SIM-") for t in tasks)
