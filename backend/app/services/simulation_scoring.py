"""P0-2 仿真实训确定性评分（纯函数，无 IO）。

评分 = 行为事件 + 状态机 + Rubric，全程不经 LLM、不使用随机数：
- 每个阶段动作在场景 JSON 中定义分值（各维度分值之和 = rubric 权重，加载器已校验）；
- 同一动作只计首次得分（重复提交记 0 分，防刷分）；
- 选择题按选项 score 计分；异常标记按区间命中计分；记录按必填字段完整度按比例计分。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionOutcome:
    """单个场景动作的得分结果。"""

    code: str
    name: str
    ability_key: str
    max_points: float
    earned: float
    is_critical: bool = False
    error_type: str = ""
    done: bool = False  # 学生是否执行过（含重复执行）


@dataclass
class SimulationScore:
    """整场仿真实训评分输出（对应总提示词 §16）。"""

    total_score: float = 0.0
    dimension_scores: dict[str, float] = field(default_factory=dict)  # 维度表现分（0-100 归一）
    dimension_earned: dict[str, float] = field(default_factory=dict)  # 维度实得分值
    outcomes: list[ActionOutcome] = field(default_factory=list)
    missed_actions: list[str] = field(default_factory=list)  # 未做的期望动作（含关键）
    missed_critical: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    # §19 完成页"能力变化/置信度"：由 complete() 在写入证据后回填（评分本身不受影响）
    ability_updates: list[dict[str, Any]] = field(default_factory=list)

    def to_feedback(self) -> dict[str, Any]:
        return {
            "total_score": self.total_score,
            "dimension_scores": self.dimension_scores,
            "missed_actions": self.missed_actions,
            "missed_critical": self.missed_critical,
            "errors": self.errors,
        }


def _option_score(stage: dict[str, Any], choice_code: Any) -> tuple[float, str, bool]:
    for option in stage.get("options") or []:
        if option.get("code") == choice_code:
            return float(option.get("score", 0)), str(option.get("error_type") or ""), bool(option.get("correct"))
    return 0.0, "invalid_choice", False


def _identity_consistent(
    action: dict[str, Any],
    event_type: str,
    *,
    target_id: str,
    payload: dict[str, Any],
) -> bool:
    """R043：event_code 命中的动作定义必须与请求的事件类型/对象一致。

    编码命中但身份不一致（如借 VIEW_TREND 类型冒领标记动作分值）视为非法事件，
    不降级到类型模糊匹配，也不计分。
    """
    defined_type = action.get("event_type")
    if defined_type is not None and str(defined_type) != str(event_type):
        return False
    defined_target = action.get("target_id")
    if defined_target is not None:
        effective = str(payload.get("target_id") or target_id or "")
        if effective != str(defined_target):
            return False
    return True


def _valid_number(value: Any) -> bool:
    """区间端点必须是有限实数；排除 bool 与 NaN/Inf（畸形输入按未命中处理）。"""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def assess_event(
    scenario: dict[str, Any],
    stage_name: str,
    *,
    event_type: str,
    event_code: str = "",
    target_type: str = "",
    target_id: str = "",
    payload: dict[str, Any] | None = None,
    counted: bool = True,
) -> ActionOutcome:
    """对单条行为事件做确定性判分。

    Args:
        counted: 该动作是否仍计分（False = 会话内重复动作，只记事件不计分）。
    """
    payload = payload or {}
    stage = (scenario.get("stages") or {}).get(stage_name) or {}
    actions = stage.get("actions") or []

    action: dict[str, Any] | None = None
    if event_type.startswith("SUBMIT_"):
        stage_code = stage.get("event_code")
        # 客户端提交的编码与当前阶段定义不一致时，不认任何动作（防跨阶段伪造）
        code = stage_code or event_code
        if event_code and stage_code and str(event_code) != str(stage_code):
            code = None
        action = next((a for a in actions if code and a.get("code") == code), None)
    else:
        if event_code:
            code_action = next((a for a in actions if a.get("code") == event_code), None)
            # R043：仅当编码命中且身份一致才计分；否则按未识别动作处理，不回退类型匹配
            if code_action is not None and _identity_consistent(
                code_action, event_type, target_id=target_id, payload=payload
            ):
                action = code_action
        else:
            action = next(
                (
                    a
                    for a in actions
                    if a.get("event_type") == event_type
                    and (not a.get("target_id") or a.get("target_id") == target_id)
                ),
                None,
            )

    if action is None:
        return ActionOutcome(
            code=event_code or event_type,
            name=event_type,
            ability_key="",
            max_points=0.0,
            earned=0.0,
            error_type="unexpected_action",
            done=True,
        )

    code = str(action.get("code"))
    name = str(action.get("name", code))
    ability = str(action.get("ability_key", ""))
    max_points = float(action.get("points", 0))
    critical = bool(action.get("critical"))

    if not counted:
        return ActionOutcome(code, name, ability, max_points, 0.0, critical, "duplicate_action", done=True)

    earned = 0.0
    error_type = ""
    if event_type == "MARK_ABNORMAL_POINT":
        answer = action.get("answer") or {}
        start = payload.get("window_start")
        end = payload.get("window_end")
        hit = (
            _valid_number(start)
            and _valid_number(end)
            and float(start) <= float(end)  # 倒置区间属畸形输入，不允许靠相交判定蒙混命中
            and str(payload.get("target_id") or target_id) == str(answer.get("target_id"))
            and float(end) >= float(answer.get("window_min", 0))
            and float(start) <= float(answer.get("window_max", 0))
        )
        if hit:
            earned = max_points
        else:
            error_type = "missed_anomaly_window"
    elif event_type.startswith("SUBMIT_") and stage.get("options"):
        got, opt_error, _correct = _option_score(stage, payload.get("choice_code"))
        earned = got
        error_type = "" if got > 0 else (opt_error or "wrong_choice")
    elif event_type == "SUBMIT_RECORD":
        required = stage.get("required_fields") or []
        fields = payload.get("fields") or {}
        filled = sum(
            1
            for key in required
            if isinstance(fields.get(key), str) and fields[key].strip()
        )
        ratio = filled / len(required) if required else 0.0
        earned = round(max_points * ratio, 2)
        if filled < len(required):
            error_type = "incomplete_record"
    else:
        # 观察/查资料类动作：执行即得分
        earned = max_points

    return ActionOutcome(code, name, ability, max_points, round(earned, 2), critical, error_type, done=True)


def score_session(scenario: dict[str, Any], outcomes: list[ActionOutcome]) -> SimulationScore:
    """按 rubric 聚合全部动作结果 → 总分 + 维度分 + 缺漏 + 错误清单。"""
    rubric = scenario["rubric"]
    dimensions: dict[str, float] = rubric["dimensions"]

    best: dict[str, ActionOutcome] = {}
    for outcome in outcomes:
        prev = best.get(outcome.code)
        if prev is None or outcome.earned > prev.earned:
            best[outcome.code] = outcome

    all_actions = {
        str(a.get("code")): (a, stage_name)
        for stage_name, stage in (scenario.get("stages") or {}).items()
        for a in (stage.get("actions") or [])
    }

    earned_by_ability: dict[str, float] = {}
    missed: list[str] = []
    missed_critical: list[str] = []
    errors: list[dict[str, str]] = []
    for code, (action, _stage_name) in all_actions.items():
        ability = str(action.get("ability_key", ""))
        outcome = best.get(code)
        earned = outcome.earned if outcome else 0.0
        earned_by_ability[ability] = earned_by_ability.get(ability, 0.0) + earned
        if outcome is None or not outcome.done:
            missed.append(str(action.get("name", code)))
            if action.get("critical"):
                missed_critical.append(str(action.get("name", code)))
        elif outcome.error_type:
            errors.append(
                {
                    "code": code,
                    "action": str(action.get("name", code)),
                    "error_type": outcome.error_type,
                    "critical": bool(action.get("critical")),
                }
            )

    dimension_scores: dict[str, float] = {}
    for ability, weight in dimensions.items():
        weight_f = float(weight)
        earned_val = earned_by_ability.get(ability, 0.0)
        dimension_scores[ability] = round(min(100.0, earned_val / weight_f * 100.0), 2) if weight_f else 0.0

    total = round(sum(earned_by_ability.values()), 2)
    return SimulationScore(
        total_score=round(min(float(rubric.get("total", 100)), total), 2),
        dimension_scores=dimension_scores,
        dimension_earned={k: round(v, 2) for k, v in earned_by_ability.items()},
        outcomes=[best[c] for c in sorted(best)],
        missed_actions=missed,
        missed_critical=missed_critical,
        errors=errors,
    )


def abilities_for_evidence(scenario: dict[str, Any]) -> dict[str, str]:
    """维度 → 能力证据来源类型（配置驱动，见 rubric.evidence_source）。"""
    return dict((scenario.get("rubric") or {}).get("evidence_source") or {})


__all__ = [
    "ActionOutcome",
    "SimulationScore",
    "abilities_for_evidence",
    "assess_event",
    "score_session",
]
