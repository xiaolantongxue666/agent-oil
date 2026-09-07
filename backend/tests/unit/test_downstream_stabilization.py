"""Phase A 下游稳定化——R043 事件身份 / gate 收紧 / 非法能力键（CASE A3/A5/A8/A9 纯函数层）。

对应 D7.5：D75-043（CODE_FIX/P1 event identity）、D75-046（六维合法性）、D75-040（B/C 发布后契约一致性）。
合法错答必须仍可完成并得低分（不得扩大为"必须全对才放行"）。
"""

from __future__ import annotations

import copy
import math

import pytest

from app.scenarios import ScenarioConfigError, _validate, load_scenarios
from app.services.simulation_scoring import assess_event
from app.services.simulation_session import SIM_FLOW

SC = "PIPELINE_ABNORMAL_001"
SIX_KEYS = {
    "process_understanding",
    "equipment_recognition",
    "instrument_parameter",
    "abnormal_detection",
    "safety_awareness",
    "standard_recording",
}


@pytest.fixture(scope="module")
def scenario() -> dict:
    return load_scenarios()[SC]


# ---------- R043：event_code 身份反校验（评分层双保险，服务层已先行 409） ----------


def test_forged_type_with_valid_code_is_unexpected(scenario):
    """借合法类型 VIEW_TREND 冒领标记动作 OBS-MARK-ANOMALY → 未识别、0 分（修复前按观察分支白拿分）。"""
    outcome = assess_event(
        scenario, "observe",
        event_type="VIEW_TREND", event_code="OBS-MARK-ANOMALY", target_id="pressure_mpa",
    )
    assert outcome.error_type == "unexpected_action"
    assert outcome.earned == 0.0


def test_cross_stage_code_is_unexpected(scenario):
    """observe 阶段引用诊断阶段编码 → 未识别。"""
    outcome = assess_event(
        scenario, "observe",
        event_type="VIEW_TREND", event_code="SUBMIT-DIAGNOSIS",
    )
    assert outcome.error_type == "unexpected_action"
    assert outcome.earned == 0.0


def test_target_mismatch_is_unexpected(scenario):
    """编码与请求对象不一致（OBS-PRESSURE-TREND 配 temperature_c）→ 未识别。"""
    outcome = assess_event(
        scenario, "observe",
        event_type="VIEW_TREND", event_code="OBS-PRESSURE-TREND", target_id="temperature_c",
    )
    assert outcome.error_type == "unexpected_action"
    assert outcome.earned == 0.0


def test_identity_consistent_event_still_scores(scenario):
    """正确身份的事件必须照常得分（A6 判分层）。"""
    outcome = assess_event(
        scenario, "observe",
        event_type="VIEW_TREND", event_code="OBS-PRESSURE-TREND", target_id="pressure_mpa",
    )
    assert outcome.error_type == ""
    assert outcome.earned == outcome.max_points > 0
    assert outcome.ability_key == "instrument_parameter"


def test_client_submit_code_conflicting_with_stage_is_unexpected(scenario):
    """SUBMIT 阶段客户端编码与阶段定义不一致 → 不认任何动作。"""
    outcome = assess_event(
        scenario, "diagnose",
        event_type="SUBMIT_DIAGNOSIS", event_code="SUBMIT-RISK", payload={"choice_code": "D1"},
    )
    assert outcome.error_type == "unexpected_action"
    assert outcome.earned == 0.0


# ---------- MARK 窗口输入校验（畸形不蒙分；合法错答照常低分可完成） ----------


def _mark(scenario, *, start, end, target="pressure_mpa"):
    return assess_event(
        scenario, "observe",
        event_type="MARK_ABNORMAL_POINT", event_code="OBS-MARK-ANOMALY", target_id=target,
        payload={"window_start": start, "window_end": end},
    )


def test_inverted_window_cannot_hit(scenario):
    """修复前 30→15 倒置区间可经相交判定蒙混命中（end≥15 且 start≤30）；修复后必须未命中。"""
    outcome = _mark(scenario, start=30, end=15)
    assert outcome.error_type == "missed_anomaly_window"
    assert outcome.earned == 0.0
    assert outcome.done is True  # 如实记录，流程仍可继续


@pytest.mark.parametrize("bad", [(float("nan"), 22), (12, float("inf")), (True, 22)])
def test_non_finite_or_bool_window_is_missed(scenario, bad):
    start, end = bad
    outcome = _mark(scenario, start=start, end=end)
    assert outcome.error_type == "missed_anomaly_window"
    assert outcome.earned == 0.0


def test_legal_wrong_window_scores_zero_but_remains_completed(scenario):
    """合法错答（0–5 与答案区 15–30 不相交）：0 分、可完成、不得报错拒绝——只判"未命中"。"""
    outcome = _mark(scenario, start=0, end=5)
    assert outcome.error_type == "missed_anomaly_window"
    assert outcome.done is True
    ok = _mark(scenario, start=20, end=25)
    assert ok.earned == ok.max_points


# ---------- A8（静态）：全部已发布场景 required_events 与阶段/动作条目一致 ----------


def test_catalog_publishes_three_scenarios():
    assert set(load_scenarios()) == {
        "PIPELINE_ABNORMAL_001",
        "EQUIPMENT_INSPECTION_PREVIEW_002",
        "HSE_RECORD_PREVIEW_003",
    }


def test_published_catalog_contract_consistency():
    for code, s in load_scenarios().items():
        assert set(s["stages"]) <= set(SIM_FLOW), code
        assert set(SIX_KEYS) == set(s["rubric"]["dimensions"]), code
        assert set((s["rubric"].get("evidence_source") or {})) <= SIX_KEYS, code
        for stage_name, cfg in s["stages"].items():
            allowed = cfg.get("allowed_event_types") or []
            gate = cfg.get("gate") or {}
            required = gate.get("required_event_types") or []
            assert set(required) <= set(allowed), (code, stage_name)
            actions = cfg.get("actions") or []
            if not actions:
                continue
            # 每个动作的 event_type（若定义）必须属于本阶段允许类型（不允许跨阶段动作驻留）
            for a in actions:
                if a.get("event_type") is not None:
                    assert a["event_type"] in allowed, (code, stage_name, a["code"])
            if stage_name == "observe":
                # 必需类型必须存在可执行的观察动作（含目标对象），否则 gate 永远不可满足
                for t in required:
                    assert any(
                        a.get("event_type") == t for a in actions
                    ), (code, "observe", t)
            else:
                assert cfg.get("event_code"), (code, stage_name)
                assert any(a.get("code") == cfg["event_code"] for a in actions), (code, stage_name)
                assert allowed and all(
                    str(t).startswith("SUBMIT_") for t in allowed
                ), (code, stage_name)


# ---------- A9：非法能力键不得进入目录（加载器 fail-loud） ----------


def test_illegal_ability_key_in_rubric_rejected(scenario):
    bad = copy.deepcopy(scenario)
    rubric = bad["rubric"]["dimensions"]
    rubric["communication_skills"] = rubric.pop("safety_awareness")
    with pytest.raises(ScenarioConfigError):
        _validate(bad)


def test_illegal_ability_key_in_action_rejected(scenario):
    bad = copy.deepcopy(scenario)
    bad["stages"]["observe"]["actions"][0]["ability_key"] = "seventh_ability"
    with pytest.raises(ScenarioConfigError):
        _validate(bad)


def test_all_published_tasks_use_legal_six_keys_only():
    """已发布场景引用的能力键全部合法（不存在第 7 键，且无键缺维）。"""
    for code, s in load_scenarios().items():
        keys = {a.get("ability_key") for cfg in s["stages"].values() for a in cfg.get("actions") or []}
        assert keys <= SIX_KEYS, (code, keys - SIX_KEYS)
        assert math.isclose(sum(float(v) for v in s["rubric"]["dimensions"].values()), 100.0)
