"""Phase A 下游稳定化——R045 自适应任务路由（CASE A1 规则层）。

要求：三个构造分支（证据链 training_retry、知识掌握 practice、冷启动 diagnostic）
都按任务真实类型路由；仿真走既有 /simulation/{scenario_code}，
无题库/场景不可加载的任务不得进入推荐；不新增第 4 类路由。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.adaptive_learning import (
    _launchable_tasks,
    _simulation_scenario_code,
    _task_activity,
    plan_evidence_chain,
)


def _sim_task(task_id=100, code="SIM-PIPE-ABN-001", scenario_code="PIPELINE_ABNORMAL_001", difficulty=3):
    return SimpleNamespace(
        id=task_id,
        code=code,
        title="仿真实训：管输异常",
        difficulty=difficulty,
        target_abilities=["instrument_parameter", "safety_awareness"],
        knowledge_points=["doc-cavitation"],
        estimated_minutes=20,
        scenario={"simulation": True, "scenario_code": scenario_code},
        questions=[],
    )


def _choice_task(task_id=7, code="TT-07", difficulty=1, questions=None):
    return SimpleNamespace(
        id=task_id,
        code=code,
        title="选择题任务",
        difficulty=difficulty,
        target_abilities=["instrument_parameter"],
        knowledge_points=["压力异常处置"],
        estimated_minutes=10,
        scenario={"scenario_text": "情境"},
        questions=questions if questions is not None else [_question()],
    )


def _question(with_options=True, active=True, status="published"):
    return SimpleNamespace(
        active=active,
        status=status,
        options=[{"id": 1}] if with_options else [],
    )


# ---------- 判型与路由 ----------


def test_sim_task_routes_to_existing_simulation_path():
    kind, route = _task_activity(_sim_task())
    assert kind == "simulation"
    assert route == "/simulation/PIPELINE_ABNORMAL_001"


def test_choice_task_routes_to_training_path():
    kind, route = _task_activity(_choice_task())
    assert kind == "choice"
    assert route == "/training/TT-07"


def test_legacy_namespace_task_defaults_to_choice():
    """兼容旧调用方（无 scenario/questions 属性）：默认按选择题处理，行为不回退。"""
    legacy = SimpleNamespace(id=7, code="T-7", title="t", difficulty=1,
                             target_abilities=["x"], knowledge_points=[], estimated_minutes=5)
    assert _simulation_scenario_code(legacy) is None
    assert _task_activity(legacy) == ("choice", "/training/T-7")


def test_simulation_meta_without_code_is_choice_like_but_unlaunchable():
    broken = _sim_task(scenario_code="   ")
    assert _simulation_scenario_code(broken) is None  # 无码 → 不冒充仿真路由
    assert _launchable_tasks([broken], {"PIPELINE_ABNORMAL_001"}) == []


# ---------- 可启动性过滤 ----------


def test_launchable_filter_covers_all_branches():
    scen = {"PIPELINE_ABNORMAL_001"}
    tasks = [
        _sim_task(),                                              # 可启动：场景可加载
        _sim_task(task_id=101, scenario_code="GONE_SCENARIO"),    # 不可启动：目录中不存在
        _choice_task(),                                           # 可启动：完整题库
        _choice_task(task_id=8, code="TT-08", questions=[]),      # 不可启动：无题（start 409）
        _choice_task(task_id=9, code="TT-09",
                     questions=[_question(with_options=False)]),  # 不可启动：缺选项（start 409）
        _choice_task(task_id=10, code="TT-10",
                     questions=[_question(status="draft")]),      # ✗ 未发布
    ]
    kept = _launchable_tasks(tasks, scen)
    assert [t.id for t in kept] == [100, 7]


# ---------- 三个构造分支的路由 ----------

def _chain(tasks, **kw):
    args = dict(
        ability_key="instrument_parameter",
        ability_name="仪表参数感知",
        score=40.0,
        confidence="medium",
        evidence={"meets_recent_op_low": True, "recent_avg": 35.0,
                  "last_scenario_code": "PIPELINE_ABNORMAL_001"},
        tasks=tasks,
    )
    args.update(kw)
    return plan_evidence_chain(**args)


def test_evidence_chain_training_retry_never_sends_sim_task_to_choice_page():
    chain = _chain([_sim_task(difficulty=1)])
    retry = [s for s in chain if s["step_type"] == "training_retry"]
    assert len(retry) == 1
    assert retry[0]["route"] == "/simulation/PIPELINE_ABNORMAL_001"
    assert retry[0]["activity_type"] == "simulation"
    assert not retry[0]["route"].startswith("/training/SIM-")


def test_evidence_chain_choice_task_still_routes_to_training():
    chain = _chain([_choice_task(difficulty=2)])
    retry = next(s for s in chain if s["step_type"] == "training_retry")
    assert retry["route"] == "/training/TT-07"
    assert retry["activity_type"] == "choice"


def test_simulation_retry_gated_by_scenario_availability():
    tasks = [_choice_task()]
    chain = _chain(tasks, available_scenario_codes={"PIPELINE_ABNORMAL_001"})
    assert any(s["step_type"] == "simulation_retry" for s in chain)
    chain = _chain(tasks, available_scenario_codes=set())
    assert not any(s["step_type"] == "simulation_retry" for s in chain)
    # 未提供可用集时保持既有行为（向后兼容旧调用方）
    assert any(s["step_type"] == "simulation_retry" for s in _chain(tasks))
