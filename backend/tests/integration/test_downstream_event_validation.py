"""Phase A 下游稳定化——集成验收 CASE A1–A7（事件身份 409、角色隔离、完成链）。

对应 D7.5 M1/M2/R047/M4：
- A1 推荐路径只指向可启动活动；A2 错误角色不能进入学生仿真（route/API）；
- A3 跨场景/跨阶段编码 409；A4 非法阶段事件 409；A5 状态不允许事件 409；
- A6 正确事件 200 且计分；A7 场景可完整完成（含合法错答低分、完成防重）。
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.scenarios import load_scenarios

pytestmark = pytest.mark.asyncio

SC = "PIPELINE_ABNORMAL_001"
BASE = "/api/training/simulation"


async def _start(client, token, code=SC):
    r = await client.post(f"{BASE}/{code}/start", headers=token)
    assert r.status_code == 200, r.text
    return r.json()["data"]["session_id"]


async def _event(client, token, sid, event_type, event_code="", target_id="", payload=None):
    return await client.post(
        f"{BASE}/sessions/{sid}/events",
        json={"event_type": event_type, "event_code": event_code,
              "target_type": "", "target_id": target_id, "payload": payload or {}},
        headers=token,
    )


async def _advance(client, token, sid):
    return await client.post(f"{BASE}/sessions/{sid}/advance", headers=token)


# ---------- A2：角色隔离（服务端强制，不依赖前端守卫） ----------


async def test_teacher_and_admin_cannot_enter_student_simulation(client, teacher_token, admin_token):
    for token in (teacher_token, admin_token):
        r = await client.post(f"{BASE}/{SC}/start", headers=token)
        assert r.status_code == 403, "teacher/admin 不得开始学生仿真实训会话"
        r = await client.post(f"{BASE}/sessions/1/events", headers=token,
                              json={"event_type": "VIEW_TREND", "payload": {}})
        assert r.status_code == 403
        r = await client.post(f"{BASE}/sessions/1/complete", headers=token)
        assert r.status_code == 403
    # 只读场景目录（已脱敏元数据）仍对已授权角色开放，不属于进入学生流程
    r = await client.get(BASE, headers=teacher_token)
    assert r.status_code == 200


async def test_teacher_cannot_read_student_session_state(client, student_token, teacher_token):
    sid = await _start(client, student_token)
    r = await client.get(f"{BASE}/sessions/{sid}", headers=teacher_token)
    assert r.status_code == 403  # 角色守卫先于归属检查


# ---------- A3/A4/A5：跨场景 / 跨阶段 / 状态不允许事件 → 服务端 409 ----------


async def test_cross_scenario_and_forged_codes_rejected(client, student_token):
    sid = await _start(client, student_token)
    await _advance(client, student_token, sid)  # briefing → observe
    # A 阶段中合法 VIEW_TREND 类型 + 伪造身份编码（冒领标记动作）
    r = await _event(client, student_token, sid, "VIEW_TREND", "OBS-MARK-ANOMALY", "pressure_mpa")
    assert r.status_code == 409
    # 跨场景：候选 B 的编码混入 A 的 observe
    r = await _event(client, student_token, sid, "VIEW_PROCESS_FLOW", "B-FLOW", "b-flow")
    assert r.status_code == 409
    # 跨阶段：诊断阶段编码冒入 observe
    r = await _event(client, student_token, sid, "VIEW_TREND", "SUBMIT-DIAGNOSIS")
    assert r.status_code == 409
    # 编码对象不一致（借压力趋势编码指向温度对象）
    r = await _event(client, student_token, sid, "VIEW_TREND", "OBS-PRESSURE-TREND", "temperature_c")
    assert r.status_code == 409
    # 全部被拒 → 未落库任何事件（gate 仍不可过）
    r = await _advance(client, student_token, sid)
    assert r.status_code == 409


async def test_state_disallowed_event_after_stage_advance(client, student_token):
    """A4/A5：进入 diagnose 后，observe 专属事件被拒；诊断阶段不认非本阶段编码。"""
    sid = await _start(client, student_token)
    await _advance(client, student_token, sid)
    for t, c, tgt in (("VIEW_PROCESS_FLOW", "OBS-PROCESS-FLOW", "pfd-station"),
                      ("VIEW_DEVICE_STATUS", "OBS-PUMP-STATUS", "pump-main-01"),
                      ("VIEW_TREND", "OBS-PRESSURE-TREND", "pressure_mpa"),
                      ("VIEW_ALARM", "OBS-ALARM-LIST", "alarm-current"),
                      ("MARK_ABNORMAL_POINT", "OBS-MARK-ANOMALY", "pressure_mpa")):
        payload = {"window_start": 15, "window_end": 30} if c == "OBS-MARK-ANOMALY" else {}
        r = await _event(client, student_token, sid, t, c, tgt, payload)
        assert r.status_code == 200, r.text
    assert (await _advance(client, student_token, sid)).status_code == 200
    r = await _event(client, student_token, sid, "VIEW_TREND")
    assert r.status_code == 409  # 状态不允许
    r = await _event(client, student_token, sid, "SUBMIT_DIAGNOSIS", "B-DIAG",
                     payload={"choice_code": "D1"})
    assert r.status_code == 409  # 跨场景编码在 submit 路径同样被拒


async def test_gate_not_bypassable_by_unrecognized_events(client, student_token):
    """A5/gate：无编码的探索事件如实记录（0 分、is_expected=False），但不得计入阶段门槛。"""
    sid = await _start(client, student_token)
    await _advance(client, student_token, sid)
    for _ in range(5):
        r = await _event(client, student_token, sid, "VIEW_TREND", target_id="nonexistent-object")
        assert r.status_code == 200
        data = r.json()["data"]["event"]
        assert data["is_expected"] is False and data["raw_score"] == 0.0
    r = await _advance(client, student_token, sid)
    assert r.status_code == 409  # unexpected 事件不再放行 gate


# ---------- A6/A7：正确事件计分、完整完成、完成防重（R047 串行） ----------


async def _minimal_to_record(client, token, sid):
    """用与场景定义身份一致的最少事件推进 observe→…→record（A6：正确事件必须保持可用）。"""
    await _advance(client, token, sid)  # → observe
    plan = [
        ("VIEW_PROCESS_FLOW", "OBS-PROCESS-FLOW", "pfd-station", {}),
        ("VIEW_DEVICE_STATUS", "OBS-PUMP-STATUS", "pump-main-01", {}),
        ("VIEW_TREND", "OBS-PRESSURE-TREND", "pressure_mpa", {}),
        ("VIEW_ALARM", "OBS-ALARM-LIST", "alarm-current", {}),
        ("MARK_ABNORMAL_POINT", "OBS-MARK-ANOMALY", "pressure_mpa",
         {"window_start": 15, "window_end": 30}),
    ]
    for t, c, tgt, p in plan:
        assert (await _event(client, token, sid, t, c, tgt, p)).status_code == 200
    assert (await _advance(client, token, sid)).status_code == 200  # → diagnose
    assert (await _event(client, token, sid, "SUBMIT_DIAGNOSIS",
                         payload={"choice_code": "D1"})).status_code == 200  # 合法错答 → 0 分
    assert (await _advance(client, token, sid)).status_code == 200  # → risk_assess
    assert (await _event(client, token, sid, "SUBMIT_RISK_ASSESSMENT",
                         payload={"choice_code": "R1"})).status_code == 200
    assert (await _advance(client, token, sid)).status_code == 200  # → decision
    assert (await _event(client, token, sid, "SUBMIT_DECISION",
                         payload={"choice_code": "T1"})).status_code == 200
    assert (await _advance(client, token, sid)).status_code == 200  # → record


async def test_legal_wrong_answers_complete_with_low_score(client, student_token):
    """合法错答（漏做多数动作 + 错选 + 空记录）仍能完成并得低分——修复不得扩大为必须全对。"""
    sid = await _start(client, student_token)
    await _minimal_to_record(client, student_token, sid)
    r = await _event(client, student_token, sid, "SUBMIT_RECORD",
                     payload={"fields": {"time_phenomenon": "只填一项"}})
    assert r.status_code == 200
    r = await client.post(f"{BASE}/sessions/{sid}/complete", headers=student_token)
    assert r.status_code == 200, r.text
    report = r.json()["data"]
    assert 0 < report["total_score"] < 60
    assert report["dimension_scores"]["abnormal_detection"] < 100
    assert len(report["ability_evidence"]) == 6
    # 完成后再提交事件被状态机拒绝（既有行为保持）
    assert (await _event(client, student_token, sid, "VIEW_TREND",
                         "OBS-PRESSURE-TREND", "pressure_mpa")).status_code == 409
    # 串行重复 complete → 409
    r = await client.post(f"{BASE}/sessions/{sid}/complete", headers=student_token)
    assert r.status_code == 409


async def test_concurrent_complete_produces_single_evaluation(client, student_token):
    """R047：并发 complete 只有一个成功；EvaluationResult 恰一条、六维证据只投递一次。"""
    sid = await _start(client, student_token)
    await _minimal_to_record(client, student_token, sid)
    assert (await _event(client, student_token, sid, "SUBMIT_RECORD",
                         payload={"fields": {k: "x" for k in [
                             "time_phenomenon", "observed_data", "preliminary_cause",
                             "actions_taken", "recorder"]}})).status_code == 200

    async def _complete():
        return (await client.post(f"{BASE}/sessions/{sid}/complete",
                                  headers=student_token)).status_code

    codes = await asyncio.gather(_complete(), _complete())
    assert sorted(codes) == [200, 409], codes

    async with AsyncSessionLocal() as db:
        n_eval = (await db.execute(
            text("SELECT COUNT(*) FROM evaluation_results WHERE session_id = :sid"),
            {"sid": sid},
        )).scalar_one()
        n_ev = (await db.execute(
            text("SELECT COUNT(DISTINCT ability_key) FROM ability_evidences "
                 "WHERE source_type IN ('operation_event','scenario_diagnosis') "
                 "AND source_id = :sid AND metadata_json LIKE '%\"simulation\"%'"),
            {"sid": sid},
        )).scalar_one()
    assert n_eval == 1
    assert n_ev == 6


# ---------- A1：自适应推荐路由全部指向可启动活动（集成层审计） ----------


def _audit_launchable(steps, *, scenario_codes, choice_launchable):
    activity_steps = [s for s in steps
                      if s["step_type"] in {"training_retry", "simulation_retry",
                                            "diagnostic_training"}]
    for step in activity_steps:
        route = step["route"]
        assert not route.startswith("/training/SIM-"), f"仿真任务被误路由到选择题页：{step}"
        if route.startswith("/training/"):
            assert route.removeprefix("/training/") in choice_launchable, step
        elif route.startswith("/simulation/"):
            assert route.removeprefix("/simulation/") in scenario_codes, step
        else:
            pytest.fail(f"出现未登记的第四类活动路由：{route}")
    return activity_steps


async def test_cold_start_diagnostic_steps_are_launchable(client):
    """冷启动分支：零证据新学生的诊断步骤必须全部可启动。

    仅创建空学生账号（测试夹具，非结果数据）；不写任何证据/画像/成绩。
    """
    from app.core.enums import UserRole
    from app.core.security import hash_password
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        if (await db.execute(
            text("SELECT id FROM users WHERE username = 'qa_coldstart'")
        )).scalar_one_or_none() is None:
            db.add(User(
                username="qa_coldstart",
                hashed_password=hash_password("qa123456"),
                role=UserRole.student,
            ))
            await db.commit()
    r = await client.post("/api/auth/login",
                          json={"username": "qa_coldstart", "password": "qa123456"})
    assert r.status_code == 200, r.text
    token = {"Authorization": f"Bearer {r.json()['data']['token']}"}

    path = (await client.get("/api/recommendation/adaptive-path",
                             headers=token)).json()["data"]
    steps = path["learning_path"]
    diagnostics = [s for s in steps if s["step_type"] == "diagnostic_training"]
    assert diagnostics, "零证据学生应得到冷启动诊断步骤（既有行为保持）"
    choice_launchable = {t["code"] for t in (
        await client.get("/api/training/tasks", headers=token)).json()["data"]}
    audit = _audit_launchable(steps, scenario_codes=set(load_scenarios()),
                              choice_launchable=choice_launchable)
    assert len(audit) == len(diagnostics)


async def test_adaptive_path_routes_are_launchable(client, student_token):
    # 先真实完成一次仿真，确保有证据链输入
    sid = await _start(client, student_token)
    await _minimal_to_record(client, student_token, sid)
    await _event(client, student_token, sid, "SUBMIT_RECORD",
                 payload={"fields": {k: "x" for k in [
                     "time_phenomenon", "observed_data", "preliminary_cause",
                     "actions_taken", "recorder"]}})
    assert (await client.post(f"{BASE}/sessions/{sid}/complete",
                              headers=student_token)).status_code == 200

    path = (await client.get("/api/recommendation/adaptive-path",
                             headers=student_token)).json()["data"]
    choice_launchable = {t["code"] for t in (
        await client.get("/api/training/tasks", headers=student_token)).json()["data"]}
    _audit_launchable(path["learning_path"], scenario_codes=set(load_scenarios()),
                      choice_launchable=choice_launchable)
    # 若证据链触发重练，simulation_retry 必须指向可加载场景的既有仿真路由
    for step in path["learning_path"]:
        if step["step_type"] == "simulation_retry":
            assert step["route"] in {f"/simulation/{c}" for c in load_scenarios()}
