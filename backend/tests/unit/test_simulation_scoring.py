"""P0-2 仿真实训确定性评分单元测试（纯函数，无数据库）。

覆盖：场景配置校验、满分/缺漏/错选/重复/记录完整度五类评分路径、
学生视图脱敏（不得泄漏答案键与分值）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.scenarios import ScenarioConfigError, load_scenarios, student_view
from app.services.simulation_scoring import assess_event, score_session
from app.services.simulation_session import replay_outcomes

SCENARIO_CODE = "PIPELINE_ABNORMAL_001"


@pytest.fixture(scope="module")
def scenario() -> dict:
    return load_scenarios()[SCENARIO_CODE]


def _ev(stage_cfg: dict, event_type: str, event_code: str = "", target_id: str = "", payload=None):
    code = event_code or stage_cfg["event_code"]
    return SimpleNamespace(
        event_type=event_type,
        event_code=code,
        target_type="",
        target_id=target_id,
        payload_json=payload or {},
        sequence_no=0,
        is_expected=True,
        raw_score=0.0,
    )


def _perfect_events(scenario: dict) -> list:
    st = scenario["stages"]
    events = []
    observe_actions = st["observe"]["actions"]
    for action in observe_actions:
        payload = (
            {"window_start": 12, "window_end": 22}
            if action["event_type"] == "MARK_ABNORMAL_POINT"
            else {}
        )
        events.append(
            _ev({}, action["event_type"], action["code"], action.get("target_id", ""), payload)
        )
    events.append(_ev(st["diagnose"], "SUBMIT_DIAGNOSIS", payload={"choice_code": "D2"}))
    events.append(_ev(st["risk_assess"], "SUBMIT_RISK_ASSESSMENT", payload={"choice_code": "R1"}))
    events.append(_ev(st["decision"], "SUBMIT_DECISION", payload={"choice_code": "T2"}))
    fields = {k: "模拟内容" for k in st["record"]["required_fields"]}
    events.append(_ev(st["record"], "SUBMIT_RECORD", payload={"fields": fields}))
    for i, e in enumerate(events):
        e.sequence_no = i + 1
    return events


# ---- 配置校验 ----


def test_scenarios_load_and_validate(scenario: dict) -> None:
    assert scenario["teaching_simulation"] is True
    assert scenario["disclaimer"]
    dims = scenario["rubric"]["dimensions"]
    assert sum(dims.values()) == 100
    assert list(dims) == [
        "process_understanding",
        "equipment_recognition",
        "instrument_parameter",
        "abnormal_detection",
        "safety_awareness",
        "standard_recording",
    ]


def test_bad_scenario_rejected(scenario: dict) -> None:
    broken = json.loads(json.dumps(scenario))
    # 篡改维度分值使其与 rubric 不一致
    broken["stages"]["observe"]["actions"][0]["points"] = 99
    from app.scenarios import _validate

    with pytest.raises(ScenarioConfigError):
        _validate(broken)
    broken2 = json.loads(json.dumps(scenario))
    broken2["teaching_simulation"] = False
    with pytest.raises(ScenarioConfigError):
        _validate(broken2)


# ---- 评分路径 ----


def test_perfect_play_scores_100(scenario: dict) -> None:
    score = score_session(scenario, replay_outcomes(scenario, _perfect_events(scenario)))
    assert score.total_score == 100.0
    assert all(v == 100.0 for v in score.dimension_scores.values())
    assert score.missed_actions == []
    assert score.errors == []


def test_missing_critical_observation_penalized(scenario: dict) -> None:
    events = [e for e in _perfect_events(scenario) if e.event_code != "OBS-LEVEL-TREND"]
    score = score_session(scenario, replay_outcomes(scenario, events))
    # 液位趋势 3 分（instrument_parameter 15 → 12/15 = 80）
    assert score.total_score == 97.0
    assert score.dimension_scores["instrument_parameter"] == 80.0
    assert "查看进站罐液位趋势" in score.missed_critical


def test_wrong_diagnosis_and_decision(scenario: dict) -> None:
    events = _perfect_events(scenario)
    for e in events:
        if e.event_type == "SUBMIT_DIAGNOSIS":
            e.payload_json = {"choice_code": "D1"}
        if e.event_type == "SUBMIT_DECISION":
            e.payload_json = {"choice_code": "T1"}
    score = score_session(scenario, replay_outcomes(scenario, events))
    assert score.total_score == 100.0 - 8.0 - 10.0
    assert score.dimension_scores["abnormal_detection"] == 60.0
    assert score.dimension_scores["safety_awareness"] == 50.0
    kinds = {e["error_type"] for e in score.errors}
    assert {"wrong_cause", "unsafe_decision"} <= kinds
    # 关键动作做过（有事件）不算遗漏，但记错误
    assert "提交异常诊断" not in score.missed_critical


def test_duplicate_action_counted_once(scenario: dict) -> None:
    events = _perfect_events(scenario)
    dup = _ev({}, "VIEW_TREND", "OBS-PRESSURE-TREND", "pressure_mpa", {})
    dup.sequence_no = 99
    events.append(dup)
    score = score_session(scenario, replay_outcomes(scenario, events))
    assert score.total_score == 100.0  # 重复不加分


def test_record_partial_fields_proportional(scenario: dict) -> None:
    events = _perfect_events(scenario)
    for e in events:
        if e.event_type == "SUBMIT_RECORD":
            fields = {k: "模拟内容" for k in scenario["stages"]["record"]["required_fields"][:3]}
            e.payload_json = {"fields": fields}
    score = score_session(scenario, replay_outcomes(scenario, events))
    assert score.dimension_scores["standard_recording"] == 60.0  # 3/5
    assert any(e["error_type"] == "incomplete_record" for e in score.errors)


def test_mark_wrong_window_scores_zero(scenario: dict) -> None:
    events = _perfect_events(scenario)
    for e in events:
        if e.event_type == "MARK_ABNORMAL_POINT":
            e.payload_json = {"window_start": 0, "window_end": 5}
    score = score_session(scenario, replay_outcomes(scenario, events))
    assert score.total_score == 100.0 - 8.0
    assert any(e["error_type"] == "missed_anomaly_window" for e in score.errors)


def test_assess_unexpected_action(scenario: dict) -> None:
    outcome = assess_event(
        scenario, "diagnose", event_type="VIEW_TREND", target_id="pressure_mpa"
    )
    assert outcome.error_type == "unexpected_action"
    assert outcome.earned == 0.0
    assert outcome.max_points == 0.0


# ---- 脱敏 ----


def test_student_view_leaks_no_answers(scenario: dict) -> None:
    view = student_view(scenario)
    dumped = json.dumps({k: v for k, v in view.items() if k != "monitor"}, ensure_ascii=False)
    for banned in ('"correct"', '"score"', '"answer"', '"error_type"', '"points"', '"gate"'):
        assert banned not in dumped, f"学生视图泄漏答案键 {banned}"
    monitor = json.dumps(view["monitor"], ensure_ascii=False)
    assert '"correct"' not in monitor and '"answer"' not in monitor  # 模拟曲线数据允许含 points
    # 题目与选项内容仍对学生可见
    assert view["stages"]["diagnose"]["question"]
    assert len(view["stages"]["diagnose"]["options"]) == 4


# ---- 启发式提示（无答案） ----


def test_hint_is_heuristic_without_answers(scenario: dict) -> None:
    from app.services.simulation_session import heuristic_hint

    events = _perfect_events(scenario)
    events = [e for e in events if e.event_code not in ("OBS-LEVEL-TREND", "OBS-ALARM-LIST")]
    hint = heuristic_hint(scenario, "observe", events)
    assert "启发提示" in hint
    assert "查看进站罐液位趋势" in hint  # 只提示未做的观察动作名
    # 不得泄漏诊断答案内容
    correct_text = next(o["text"] for o in scenario["stages"]["diagnose"]["options"] if o.get("correct"))
    assert correct_text not in hint
