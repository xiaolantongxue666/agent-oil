"""Pre-Data P0 修复实测：PIPELINE_ABNORMAL_001 六阶段真实 HTTP 端到端。

模拟前端 SimulationWorkbenchView 实际发出的请求体：
- emit() → POST /events，body 仅含 event_type/target_type/target_id/payload（无 event_code）
- 提交类事件 payload：SUBMIT_* → {choice_code}，SUBMIT_RECORD → {fields}
- 事件类型从学生场景视图 allowed_event_types[0] 读取（验证"配置驱动、非猜测"）
"""
from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8021/api"
SC = "PIPELINE_ABNORMAL_001"
PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    mark = "PASS" if cond else "FAIL"
    if cond:
        PASS += 1
    else:
        FAIL += 1
    print(f"[{mark}] {name}" + (f" | {detail}" if detail else ""))


def emit(c: httpx.Client, sid: int, event_type: str, target_type: str = "", target_id: str = "", payload: dict | None = None):
    """与前端 emit() 完全一致的请求体（不传 event_code）。"""
    return c.post(f"{BASE}/training/simulation/sessions/{sid}/events", json={
        "event_type": event_type,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload or {},
    })


def main() -> None:
    c = httpx.Client(timeout=30)
    r = c.post(f"{BASE}/auth/login", json={"username": "student", "password": "student123"})
    assert r.status_code == 200, r.text
    tok = r.json()["data"]["token"]
    c.headers["Authorization"] = f"Bearer {tok}"

    # 0) 场景详情：验证前端可从配置读取每阶段提交事件类型（非硬编码）
    view = c.get(f"{BASE}/training/simulation/{SC}").json()["data"]
    cfg_event = {s: (view["stages"].get(s) or {}).get("allowed_event_types", [None])[0]
                 for s in ("diagnose", "risk_assess", "decision", "record")}
    check("学生视图暴露 allowed_event_types（配置驱动提交类型）",
          cfg_event == {"diagnose": "SUBMIT_DIAGNOSIS", "risk_assess": "SUBMIT_RISK_ASSESSMENT",
                        "decision": "SUBMIT_DECISION", "record": "SUBMIT_RECORD"},
          json.dumps(cfg_event, ensure_ascii=False))
    check("学生视图选项仅含 code/text（无答案键）",
          all(set(o) == {"code", "text"} for s in ("diagnose", "risk_assess", "decision")
              for o in view["stages"][s]["options"]))

    # 1) 开始会话
    sess = c.post(f"{BASE}/training/simulation/{SC}/start").json()["data"]
    sid = sess["session_id"]
    check("阶段1 briefing：会话创建", sess["stage"] == "briefing", f"session={sid}")

    # gate 正向：briefing 无 required → advance 应成功（真实学生点"下一阶段"）
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("briefing→observe：advance 200", r.status_code == 200 and r.json()["data"]["stage"] == "observe")

    # 2) observe：真实 UI 按钮逐个 emit（含 gate 反证：先推必看 409）
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("observe gate：事件不足时 advance 409（gate 未削弱）", r.status_code == 409,
          r.json().get("detail", {}).get("message", "") if isinstance(r.json().get("detail"), dict) else str(r.json().get("detail", ""))[:60])

    observe_ui_events = [
        ("VIEW_PROCESS_FLOW", "diagram", "pfd-station"),
        ("VIEW_PROCESS_FLOW", "diagram", "segment-up-down"),
        ("OPEN_KNOWLEDGE", "knowledge_doc", "doc-cavitation"),
        ("VIEW_DEVICE_STATUS", "device", "pump-main-01"),
        ("VIEW_DEVICE_STATUS", "device", "inlet-tank-01"),
        ("VIEW_DEVICE_STATUS", "device", "valve-xv-101"),
        ("VIEW_TREND", "trend", "pressure_mpa"),
        ("VIEW_TREND", "trend", "flow_t_h"),
        ("VIEW_TREND", "trend", "inlet_level_pct"),
        ("VIEW_TREND", "trend", "temperature_c"),
        ("VIEW_ALARM", "alarm_panel", "alarm-current"),
        ("MARK_ABNORMAL_POINT", "trend", "pressure_mpa"),
    ]
    ok = True
    for et, tt, ti in observe_ui_events:
        p = {"window_start": 12, "window_end": 22} if et == "MARK_ABNORMAL_POINT" else {}
        rr = emit(c, sid, et, tt, ti, p)
        ok = ok and rr.status_code == 200
    check("observe：12 个真实 UI 动作全部 200", ok)
    rts = c.get(f"{BASE}/training/simulation/sessions/{sid}").json()["data"]
    check("observe gate 满足（min5 + VIEW_TREND/VIEW_ALARM/MARK_ABNORMAL_POINT）",
          rts["event_count"] >= 12 and rts["pending_actions"] == [],
          f"events={rts['event_count']} pending={json.dumps(rts['pending_actions'], ensure_ascii=False)}")
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("observe→diagnose：advance 200", r.status_code == 200 and r.json()["data"]["stage"] == "diagnose")

    # 3) diagnose：修复核心。反证（不提交→advance 必须 409）+ 正证
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("diagnose gate：未产生 SUBMIT_DIAGNOSIS 时 advance 409（gate 完好）", r.status_code == 409)

    r = emit(c, sid, "SUBMIT_DIAGNOSIS", "stage", "diagnose", {"choice_code": "D2"})
    ev = r.json()["data"]["event"]
    check("diagnose 提交入口：SUBMIT_DIAGNOSIS(D2) 200 且满分 8",
          r.status_code == 200 and ev["event_code"] == "SUBMIT-DIAGNOSIS"
          and ev["raw_score"] == 8.0 and ev["error_type"] in ("", None),
          f"code={ev['event_code']} raw={ev['raw_score']} err={ev['error_type']}")

    rts = c.get(f"{BASE}/training/simulation/sessions/{sid}").json()["data"]
    check("runtime.events 含 SUBMIT_DIAGNOSIS（stageSubmitted 事实来源成立）",
          any(e["event_type"] == "SUBMIT_DIAGNOSIS" for e in rts["events"]))
    check("提交后任务清单清空（pending=[] → UI 显示已完成）", rts["pending_actions"] == [])

    # 重复提交（双击场景）：后端幂等 → duplicate_action 0 分
    r = emit(c, sid, "SUBMIT_DIAGNOSIS", "stage", "diagnose", {"choice_code": "D2"})
    ev2 = r.json()["data"]["event"]
    check("重复 SUBMIT_DIAGNOSIS 幂等：duplicate_action 且 raw_score=0",
          ev2["error_type"] == "duplicate_action" and ev2["raw_score"] == 0.0)

    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("diagnose→risk_assess：提交后 advance 200（按钮 disabled→enabled 链路成立）",
          r.status_code == 200 and r.json()["data"]["stage"] == "risk_assess")

    # 4) risk_assess
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("risk_assess gate：未提交 advance 409", r.status_code == 409)
    r = emit(c, sid, "SUBMIT_RISK_ASSESSMENT", "stage", "risk_assess", {"choice_code": "R1"})
    ev = r.json()["data"]["event"]
    check("risk_assess 提交入口：SUBMIT_RISK_ASSESSMENT(R1) 满分 10",
          ev["event_code"] == "SUBMIT-RISK" and ev["raw_score"] == 10.0)
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("risk_assess→decision：advance 200", r.status_code == 200 and r.json()["data"]["stage"] == "decision")

    # 5) decision
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("decision gate：未提交 advance 409", r.status_code == 409)
    r = emit(c, sid, "SUBMIT_DECISION", "stage", "decision", {"choice_code": "T2"})
    ev = r.json()["data"]["event"]
    check("decision 提交入口：SUBMIT_DECISION(T2) 满分 10",
          ev["event_code"] == "SUBMIT-DECISION" and ev["raw_score"] == 10.0)
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/advance")
    check("decision→record：advance 200", r.status_code == 200 and r.json()["data"]["stage"] == "record")

    # 6) record：完成 gate 反证 + 提交 + 完成
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/complete")
    check("record gate：未产生 SUBMIT_RECORD 时 complete 409（完成按钮 gate 完好）", r.status_code == 409)
    fields = {
        "time_phenomenon": "第10分钟起出口压力与流量持续下降（模拟）",
        "observed_data": "压力 4.2→2.1MPa，流量 320→150t/h，进站罐液位 65%→22%",
        "preliminary_cause": "上游进站罐液位持续下降导致吸入不足，泵低入口条件运行",
        "actions_taken": "已复核参数并汇报值班负责人，按教学预案评估降负荷（模拟）",
        "recorder": "演示学生",
    }
    r = emit(c, sid, "SUBMIT_RECORD", "stage", "record", {"fields": fields})
    ev = r.json()["data"]["event"]
    check("record 提交入口：SUBMIT_RECORD(payload.fields) 满分 15",
          ev["event_code"] == "SUBMIT-RECORD" and ev["raw_score"] == 15.0)
    rts = c.get(f"{BASE}/training/simulation/sessions/{sid}").json()["data"]
    check("runtime.events 含 SUBMIT_RECORD（完成实训按钮出现条件成立）",
          any(e["event_type"] == "SUBMIT_RECORD" for e in rts["events"]))

    # 7) 完成
    r = c.post(f"{BASE}/training/simulation/sessions/{sid}/complete")
    rep = r.json()["data"]
    check("完成实训：complete 200，全链路无绕过",
          r.status_code == 200 and rep["total_score"] == 100.0,
          f"total={rep.get('total_score')}")
    rts = c.get(f"{BASE}/training/simulation/sessions/{sid}").json()["data"]
    check("会话 stage=finished", rts["stage"] == "finished" and rts["finished"] is True)

    feed = [f"#{e['sequence_no']} {e['event_type']}" for e in rts["events"]]
    need = ["SUBMIT_DIAGNOSIS", "SUBMIT_RISK_ASSESSMENT", "SUBMIT_DECISION", "SUBMIT_RECORD"]
    check("行为记录完整：4 个关键提交事件全部可见", all(any(n in x for x in feed) for n in need))
    print("\n--- 行为记录（行为链可追溯证据） ---")
    for x in feed:
        print(" ", x)

    # 8) 证据闭环：AbilityEvidence
    prof_before_keys = ("abnormal_detection", "safety_awareness", "standard_recording",
                        "instrument_parameter", "process_understanding", "equipment_recognition")
    dup = {}
    for ab in prof_before_keys:
        e = c.get(f"{BASE}/ability/evidence", params={"ability_key": ab}).json()["data"]
        mine = [i for i in e["items"] if i.get("metadata", {}).get("source_id") == sid
                or i.get("metadata", {}).get("session_id") == sid
                or i.get("source_id") == sid or i.get("session_id") == sid]
        dup[ab] = len(mine)
    check("AbilityEvidence：本会话 6 维度证据各恰好 1 条（无重复）",
          all(v == 1 for v in dup.values()), json.dumps(dup))
    e_ad = c.get(f"{BASE}/ability/evidence", params={"ability_key": "abnormal_detection"}).json()["data"]
    item = next(i for i in e_ad["items"] if i.get("source_id") == sid)
    check("source_type 正确：abnormal_detection → scenario_diagnosis",
          item["source_type"] == "scenario_diagnosis", item["source_type"])
    prof = c.get(f"{BASE}/ability/profile").json()["data"]
    check("profile 可读且 abnormal_detection 证据数>0",
          prof["abnormal_detection"]["evidence_count"] >= 1,
          f"score={prof['abnormal_detection']['score']} conf={prof['abnormal_detection'].get('confidence')}")

    # 9) /adaptive-learning 页面数据源
    r1 = c.get(f"{BASE}/recommendation/tasks")
    r2 = c.get(f"{BASE}/recommendation/adaptive-path")
    check("/adaptive-learning 数据接口正常（recommendation tasks + adaptive-path）",
          r1.status_code == 200 and r2.status_code == 200)
    ap = r2.json()["data"]
    check("adaptive-path 基于更新后画像生成（learning_path 非空且每步含结构字段）",
          isinstance(ap, dict) and isinstance(ap.get("learning_path"), list) and len(ap["learning_path"]) > 0
          and all({"step_type", "title", "route"} <= set(s) for s in ap["learning_path"]),
          f"steps={len(ap.get('learning_path', []))}")

    print(f"\n结果：PASS={PASS} FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
