"""自适应学习纯函数单元测试（P0-5 Phase 6：§42 证据汇总 + §43 证据链触发）。

summarize_evidence / plan_evidence_chain 为纯规则函数，不经数据库、不经 LLM。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import get_settings
from app.services.adaptive_learning import (
    plan_evidence_chain,
    summarize_evidence,
)

SETTINGS = get_settings()
KW = dict(
    trend_window=SETTINGS.adaptive_trend_window,
    trend_delta=SETTINGS.adaptive_trend_delta,
    low_score=SETTINGS.adaptive_evidence_low_score,
    recent_op_low_count=SETTINGS.adaptive_recent_op_low_count,
)


def _task(task_id: int = 7, difficulty: int = 3, abilities=("abnormal_detection",), points=("异常识别",)):
    return SimpleNamespace(
        id=task_id,
        code=f"T-{task_id}",
        title=f"任务{task_id}",
        difficulty=difficulty,
        estimated_minutes=20,
        target_abilities=list(abilities),
        knowledge_points=list(points),
    )


# ---- summarize_evidence（§42 近期表现 / 历史趋势 / 操作低分连击） ----

def test_summarize_empty_evidence_is_neutral():
    s = summarize_evidence([], **KW)
    assert s["count"] == 0
    assert s["recent_avg"] is None
    assert s["trend"] == "insufficient"
    assert s["meets_recent_op_low"] is False
    assert s["last_scenario_code"] is None


def test_summarize_recent_avg_uses_config_window():
    items = [(90.0, "operation_event", {}), (50.0, "operation_event", {}), (70.0, "operation_event", {})]
    s = summarize_evidence(items, **KW)
    # 最近 adaptive_trend_window(=2) 条：(50+70)/2 = 60
    assert s["recent_avg"] == 60.0


def test_summarize_trend_directions():
    # 近段明显优于前段 → improving；明显劣于 → declining；相近 → stable；
    # 条数不足 2×window → insufficient
    up = [(40.0, "operation_event", {}), (40.0, "operation_event", {}), (90.0, "operation_event", {}), (95.0, "operation_event", {})]
    down = list(reversed(up))
    flat = [(70.0, "operation_event", {})] * 4
    assert summarize_evidence(up, **KW)["trend"] == "improving"
    assert summarize_evidence(down, **KW)["trend"] == "declining"
    assert summarize_evidence(flat, **KW)["trend"] == "stable"
    assert summarize_evidence(up[:3], **KW)["trend"] == "insufficient"


def test_summarize_counts_consecutive_trailing_low_ops_only():
    # 时间正序：低、低、高（非操作）——操作低分连击被高分操作证据打断 → 不触发
    broken = [
        (30.0, "operation_event", {}),
        (30.0, "operation_event", {}),
        (95.0, "operation_event", {}),
    ]
    s = summarize_evidence(broken, **KW)
    assert s["recent_low_ops"] == 0
    assert s["meets_recent_op_low"] is False

    # 非操作证据（教师评价）不打断尾部连击：低、低、评价 → 触发
    mixed = [
        (30.0, "operation_event", {}),
        (30.0, "scenario_diagnosis", {}),
        (20.0, "teacher_assessment", {}),
    ]
    s2 = summarize_evidence(mixed, **KW)
    assert s2["meets_recent_op_low"] is True
    assert s2["recent_low_ops"] >= SETTINGS.adaptive_recent_op_low_count


def test_summarize_records_last_scenario_code_from_metadata():
    items = [
        (30.0, "operation_event", {"scenario_code": "SC_A"}),
        (40.0, "operation_event", {"scenario_code": "SC_B"}),
        (50.0, "knowledge_quiz", {}),
    ]
    # 倒序扫描时取"最近一条带编码"的 → SC_B
    assert summarize_evidence(items, **KW)["last_scenario_code"] == "SC_B"


# ---- plan_evidence_chain（§43 三条件同时满足才触发） ----

def _evidence(**over):
    base = {
        "count": 3,
        "types": ["operation_event", "scenario_diagnosis"],
        "recent_avg": 38.0,
        "trend": "stable",
        "recent_low_ops": SETTINGS.adaptive_recent_op_low_count,
        "meets_recent_op_low": True,
        "last_scenario_code": "PIPELINE_ABNORMAL_001",
    }
    base.update(over)
    return base


def _chain(**over):
    args = dict(
        ability_key="abnormal_detection",
        ability_name="异常识别",
        score=42.0,
        confidence="medium",
        evidence=_evidence(),
        tasks=[_task()],
    )
    args.update(over)
    return plan_evidence_chain(**args)


def test_chain_requires_low_score():
    assert _chain(score=SETTINGS.adaptive_weak_threshold + 5) is None


def test_chain_requires_confidence_at_least_medium():
    # §43：置信度不足（证据太少）不得触发补强链——宁缺毋滥
    assert _chain(confidence="low") is None
    assert _chain(confidence="medium") is not None
    assert _chain(confidence="high") is not None


def test_chain_requires_recent_low_ops():
    ev = _evidence(meets_recent_op_low=False)
    assert _chain(evidence=ev) is None


def test_chain_emits_knowledge_case_training_retry_sequence():
    steps = _chain(score=45.0)
    assert steps is not None
    types = [s["step_type"] for s in steps]
    # 低分段（30~60）目标难度 2：降档训练在案例之后
    assert types == ["knowledge_review", "case_learning", "training_retry", "simulation_retry"]
    assert all(s["evidence_driven"] is True for s in steps)
    assert all(s["target_ability"] == "abnormal_detection" for s in steps)
    assert all(s["priority"] == "证据优先补强" for s in steps)
    assert all(s["route"].startswith("/") for s in steps)
    training = next(s for s in steps if s["step_type"] == "training_retry")
    assert training["task_code"] == "T-7"
    assert training["route"] == "/training/T-7"
    assert training["difficulty"] == 3  # 原任务难度透传
    sim = steps[-1]
    assert sim["route"] == "/simulation/PIPELINE_ABNORMAL_001"


def test_chain_very_low_score_targets_difficulty_one():
    steps = _chain(score=20.0, tasks=[_task(task_id=1, difficulty=1), _task(task_id=2, difficulty=4)])
    training = next(s for s in steps if s["step_type"] == "training_retry")
    assert training["task_id"] == 1  # score<30 → 目标难度 1，取最接近的任务


def test_chain_marks_safety_critical_for_safety_dimension():
    steps = _chain(ability_key="safety_awareness", tasks=[_task(abilities=("safety_awareness",))])
    assert steps is not None
    assert [s["step_type"] for s in steps] == [
        "knowledge_review", "case_learning", "training_retry", "simulation_retry",
    ]
    assert all(s["safety_critical"] is True for s in steps)


def test_chain_without_scenario_metadata_skips_simulation_step():
    steps = _chain(evidence=_evidence(last_scenario_code=None))
    types = [s["step_type"] for s in steps]
    assert "simulation_retry" not in types
    assert types == ["knowledge_review", "case_learning", "training_retry"]


def test_chain_without_matching_tasks_skips_training_step():
    steps = _chain(tasks=[_task(abilities=("process_understanding",))])
    types = [s["step_type"] for s in steps]
    assert "training_retry" not in types
