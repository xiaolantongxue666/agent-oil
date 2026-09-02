"""P0-5 Phase 6 集成测试：统一证据驱动的自适应学习路径（§41~§44）。

演示学生共享 session 级数据库，且更早的测试文件可能已写入证据/答题数据，
本文件先清空演示学生画像，再走 4 次仿真实训制造确定性证据形态：
- safety_awareness 每场 50 分（连续低分操作/诊断证据）→ 应触发 §43 证据链并置顶；
- abnormal_detection 每场 60 分（不严格低于低分线）→ 不应触发证据链。
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.ability import AbilityHistory, AbilityScore
from app.models.ability_evidence import AbilityEvidence
from app.models.user import User

pytestmark = pytest.mark.asyncio

SC = "PIPELINE_ABNORMAL_001"
BASE = "/api/training/simulation"

OBSERVE_PLAN = [
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


async def _reset_demo_student_profile() -> int:
    async with AsyncSessionLocal() as session:
        student_id = await session.scalar(select(User.id).where(User.username == "student"))
        assert student_id is not None
        await session.execute(delete(AbilityEvidence).where(AbilityEvidence.student_id == student_id))
        await session.execute(delete(AbilityHistory).where(AbilityHistory.student_id == student_id))
        await session.execute(delete(AbilityScore).where(AbilityScore.student_id == student_id))
        await session.commit()
        return int(student_id)


async def _run_simulation(client, token) -> dict:
    """完整走一遍仿真：错诊断(-8) + 错风险判断(R2=0，安全 10/20=50) + 漏流量趋势(-4)。"""
    sess = (await client.post(f"{BASE}/{SC}/start", headers=token)).json()["data"]
    sid = sess["session_id"]
    await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
    for event_type, code, target_id, payload in OBSERVE_PLAN:
        r = await client.post(
            f"{BASE}/sessions/{sid}/events",
            json={
                "event_type": event_type, "event_code": code,
                "target_type": "", "target_id": target_id, "payload": payload,
            },
            headers=token,
        )
        assert r.status_code == 200, r.text
    await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
    await client.post(
        f"{BASE}/sessions/{sid}/events",
        json={"event_type": "SUBMIT_DIAGNOSIS", "event_code": "", "target_type": "", "target_id": "", "payload": {"choice_code": "D1"}},
        headers=token,
    )
    await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
    await client.post(
        f"{BASE}/sessions/{sid}/events",
        json={"event_type": "SUBMIT_RISK_ASSESSMENT", "event_code": "", "target_type": "", "target_id": "", "payload": {"choice_code": "R2"}},
        headers=token,
    )
    await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
    await client.post(
        f"{BASE}/sessions/{sid}/events",
        json={"event_type": "SUBMIT_DECISION", "event_code": "", "target_type": "", "target_id": "", "payload": {"choice_code": "T2"}},
        headers=token,
    )
    await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)
    await client.post(
        f"{BASE}/sessions/{sid}/events",
        json={
            "event_type": "SUBMIT_RECORD", "event_code": "", "target_type": "", "target_id": "",
            "payload": {"fields": {k: "模拟记录" for k in ["time_phenomenon", "observed_data", "preliminary_cause", "actions_taken"]}},
        },
        headers=token,
    )
    r = await client.post(f"{BASE}/sessions/{sid}/complete", headers=token)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_adaptive_path_is_evidence_driven_with_safety_first(client, student_token):
    settings = get_settings()
    await _reset_demo_student_profile()
    for _ in range(4):
        report = await _run_simulation(client, student_token)
        assert report["dimension_scores"]["safety_awareness"] == 50.0
        assert report["dimension_scores"]["abnormal_detection"] == 60.0

    r = await client.get("/api/recommendation/adaptive-path", headers=student_token)
    assert r.status_code == 200
    data = r.json()["data"]
    steps = data["learning_path"]

    # §41 证据层：统一证据表已被消费（每场 6 维 × 4 场）
    assert data["summary"]["evidence_count"] == 24
    assert data["summary"]["path_step_count"] == len(steps)

    by_key = {item["key"]: item for item in data["ability_state"]}
    safety = by_key["safety_awareness"]
    abnormal = by_key["abnormal_detection"]
    # §42 能力状态暴露置信度/趋势/近期均值（全部确定性规则推导）
    assert safety["confidence"] == "medium" and safety["evidence_count"] == 4
    assert safety["trend"] == "stable" and safety["recent_avg"] == 50.0
    assert safety["score"] < settings.adaptive_weak_threshold

    # §43 证据优先链：相关知识点 → 案例学习 →（可选降档训练）→ 原场景重练
    safety_chain = [s for s in steps if s.get("evidence_driven") and s["target_ability"] == "safety_awareness"]
    chain_types = [s["step_type"] for s in safety_chain]
    assert "knowledge_review" in chain_types and "case_learning" in chain_types
    assert chain_types[-1] == "simulation_retry"
    assert safety_chain[-1]["route"] == f"/simulation/{SC}"
    assert all(s["priority"] == "证据优先补强" for s in safety_chain)

    # abnormal_detection 每场证据 60 分，未严格低于低分线 → 不触发证据链（阈值语义边界）
    assert abnormal["recent_avg"] == 60.0
    assert not [s for s in steps if s.get("evidence_driven") and s["target_ability"] == "abnormal_detection"]

    # §44 安全置顶 + 全局提醒 + 高难度门禁标记
    assert steps[0]["target_ability"] == "safety_awareness" and steps[0]["safety_critical"] is True
    alert = data["safety_alert"]
    assert alert is not None
    assert alert["floor"] == settings.adaptive_safety_score_floor
    assert alert["safety_score"] == safety["score"]
    assert "安全意识" in alert["message"]
    for step in steps:
        if step["difficulty"] >= settings.adaptive_safety_gate_difficulty and not step["safety_critical"]:
            assert step.get("safety_gate_warning") is True

    assert "不影响专业培养方案" in data["data_boundary"]
    assert data["refresh_rule"] and "LLM" not in data["refresh_rule"] + data["data_boundary"]


async def test_recommendation_pins_safety_when_below_floor(client, student_token):
    """§44：安全意识未达下限（上一测试学生为 ~33 分）时，薄弱推荐首位为安全类任务。"""
    r = await client.get("/api/recommendation/tasks", headers=student_token)
    assert r.status_code == 200
    items = r.json()["data"]
    weak = [i for i in items if i["reason_code"] == "weak_ability"]
    safety_weak = [i for i in weak if i["target_ability"] == "safety_awareness"]
    if safety_weak:  # 存在可用的安全类薄弱任务时，必须排最前
        assert weak[0]["target_ability"] == "safety_awareness"
