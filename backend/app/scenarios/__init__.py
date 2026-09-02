"""仿真实训场景配置加载器（P0-2）。

场景 = 纯配置文件（JSON），新增场景以加配置为主、少量加代码。
本模块负责：读取目录下的 *.json、结构校验（fail-loud）、缓存与脱敏视图。

校验规则（不满足直接抛 ScenarioConfigError，禁止带病上线）：
- 每个动作 ability_key 的分值之和 == rubric.dimensions 对应维度权重；
- rubric 六维权重之和 == rubric.total == 100；
- 选择题 stage 必须同时有 options 且恰有一个 correct；
- stage 键必须是仿真实训阶段枚举的子集（observe/diagnose/risk_assess/decision/record）。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.enums import SIMULATION_STAGE_FLOW, AbilityKey

SCENARIO_DIR = Path(__file__).resolve().parent

# briefing/finished 由状态机与 start/complete 端点驱动，场景 stages 只定义动作阶段
_ACTION_STAGES = {s.value for s in SIMULATION_STAGE_FLOW} - {"briefing", "finished"}


class ScenarioConfigError(ValueError):
    """场景配置非法。"""


def _validate(scenario: dict[str, Any]) -> None:
    code = scenario.get("scenario_code")
    if not code:
        raise ScenarioConfigError("场景缺少 scenario_code")
    if not scenario.get("teaching_simulation"):
        raise ScenarioConfigError(f"场景 {code} 必须显式标记 teaching_simulation=true")
    if not scenario.get("disclaimer"):
        raise ScenarioConfigError(f"场景 {code} 缺少教学模拟声明 disclaimer")

    rubric = scenario.get("rubric") or {}
    dimensions = rubric.get("dimensions") or {}
    total = rubric.get("total")
    if total != 100 or sum(dimensions.values()) != 100:
        raise ScenarioConfigError(f"场景 {code} rubric 权重之和必须为 100，当前 {dimensions}")
    known_keys = {k.value for k in AbilityKey}
    if not set(dimensions) <= known_keys:
        raise ScenarioConfigError(f"场景 {code} rubric 含未知能力键 {set(dimensions) - known_keys}")

    stages = scenario.get("stages") or {}
    if set(stages) - _ACTION_STAGES:
        raise ScenarioConfigError(f"场景 {code} 含非法阶段 {set(stages) - _ACTION_STAGES}")
    if "observe" not in stages:
        raise ScenarioConfigError(f"场景 {code} 缺少 observe 阶段")

    points_by_ability: dict[str, float] = {}
    for stage_name, stage in stages.items():
        actions = stage.get("actions") or []
        codes = [a.get("code") for a in actions]
        if len(codes) != len(set(codes)):
            raise ScenarioConfigError(f"场景 {code} 阶段 {stage_name} 动作编码重复")
        for action in actions:
            ability = action.get("ability_key")
            if ability not in known_keys:
                raise ScenarioConfigError(f"场景 {code} 动作 {action.get('code')} ability_key 非法: {ability}")
            points_by_ability[ability] = points_by_ability.get(ability, 0.0) + float(action.get("points", 0))
        if stage.get("options"):
            correct = [o for o in stage["options"] if o.get("correct")]
            if len(correct) != 1:
                raise ScenarioConfigError(f"场景 {code} 阶段 {stage_name} 必须恰有一个 correct 选项")
            max_score = max(float(o.get("score", 0)) for o in stage["options"])
            action_points = sum(float(a.get("points", 0)) for a in actions)
            if max_score != action_points:
                raise ScenarioConfigError(
                    f"场景 {code} 阶段 {stage_name} 最高选项分 {max_score} 应等于动作分值 {action_points}"
                )

    for ability, weight in dimensions.items():
        if abs(points_by_ability.get(ability, 0.0) - float(weight)) > 1e-9:
            raise ScenarioConfigError(
                f"场景 {code} 维度 {ability} 动作分值合计 {points_by_ability.get(ability, 0.0)}"
                f" != rubric 权重 {weight}"
            )


_cache: dict[str, dict[str, Any]] | None = None


def load_scenarios(force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """加载并校验全部场景配置（按文件修改时间缓存）。"""
    global _cache
    files = sorted(SCENARIO_DIR.glob("*.json"))
    fingerprint = tuple((f, f.stat().st_mtime_ns) for f in files)
    if not force_reload and _cache is not None and _cache.get("__fingerprint__") == fingerprint:
        return {k: v for k, v in _cache.items() if k != "__fingerprint__"}

    result: dict[str, dict[str, Any]] = {}
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ScenarioConfigError(f"场景文件 {path.name} JSON 解析失败: {exc}") from exc
        _validate(data)
        code = data["scenario_code"]
        if code in result:
            raise ScenarioConfigError(f"scenario_code 重复: {code}")
        result[code] = data
    _cache = {**result, "__fingerprint__": fingerprint}
    return dict(result)


def get_scenario(scenario_code: str) -> dict[str, Any]:
    scenarios = load_scenarios()
    if scenario_code not in scenarios:
        raise ScenarioConfigError(f"仿真场景不存在: {scenario_code}")
    return scenarios[scenario_code]


def student_view(scenario: dict[str, Any]) -> dict[str, Any]:
    """学生可见视图：剔除答案键（correct/score/error_type/answer/points/gate）。

    rubric 维度分值与任务名称公开；选项只公开 code/text。
    """
    view = deepcopy(scenario)
    stages: dict[str, Any] = {}
    for name, stage in (view.get("stages") or {}).items():
        clean_stage = {k: v for k, v in stage.items() if k not in ("gate", "options", "actions", "event_code", "ability_key")}
        if stage.get("options"):
            clean_stage["options"] = [{"code": o["code"], "text": o["text"]} for o in stage["options"]]
        else:
            clean_stage["actions"] = [
                {k: a[k] for k in ("code", "name", "ability_key", "target_type", "target_id") if k in a}
                | ({"event_type": a["event_type"]} if a.get("event_type") else {})
                for a in stage.get("actions", [])
            ]
        stages[name] = clean_stage
    view["stages"] = stages
    view.pop("answer", None)
    return view
