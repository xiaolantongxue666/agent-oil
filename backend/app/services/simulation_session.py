"""P0-2 仿真实训会话状态机服务。

规则：
- 阶段推进由后端控制（SIMULATION_STAGE_FLOW），前端只能请求 advance 且必须通过 gate；
- 每条行为事件由 simulation_scoring 纯函数确定性判分后落 TrainingActionEvents；
- 完成时按 rubric 聚合 → 写 EvaluationResult → 逐维度投递 AbilityEvidence（P0-1 通道）；
- LLM 不参与任何评分与阶段判定。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EvidenceSourceType, TrainingStage
from app.core.logging import logger
from app.models.training import EvaluationResult, TrainingSession, TrainingTask
from app.models.training_action_event import TrainingActionEvent
from app.scenarios import ScenarioConfigError, get_scenario
from app.services.ability_profile import AbilityProfileService
from app.services.simulation_scoring import (
    ActionOutcome,
    SimulationScore,
    abilities_for_evidence,
    assess_event,
    score_session,
)

# 仿真阶段顺序（briefing 起步，finished 仅由 complete 达成）
SIM_FLOW: tuple[str, ...] = (
    TrainingStage.briefing.value,
    TrainingStage.observe.value,
    TrainingStage.diagnose.value,
    TrainingStage.risk_assess.value,
    TrainingStage.decision.value,
    TrainingStage.record.value,
)


class SimulationStageError(ValueError):
    """状态机违规（阶段/事件不允许）。路由层转 409。"""


def _stage_value(sess: TrainingSession) -> str:
    return sess.stage.value if isinstance(sess.stage, TrainingStage) else str(sess.stage)


def _next_stage(stage: str) -> str:
    if stage not in SIM_FLOW:
        raise SimulationStageError(f"当前阶段 {stage} 不属于仿真实训流程")
    idx = SIM_FLOW.index(stage)
    if idx == len(SIM_FLOW) - 1:
        raise SimulationStageError("记录阶段请使用完成接口提交成绩，不能直接推进")
    return SIM_FLOW[idx + 1]


def check_gate(scenario: dict[str, Any], stage: str, events: list[TrainingActionEvent]) -> None:
    """阶段离开条件：必需事件类型齐全 + 最少事件数（配置驱动）。"""
    gate = ((scenario.get("stages") or {}).get(stage) or {}).get("gate") or {}
    allowed = ((scenario.get("stages") or {}).get(stage) or {}).get("allowed_event_types") or []
    stage_events = [e for e in events if e.event_type in allowed]
    min_events = int(gate.get("min_events", 0))
    if len(stage_events) < min_events:
        raise SimulationStageError(f"当前阶段至少需要 {min_events} 次有效操作（已做 {len(stage_events)}）")
    done_types = {e.event_type for e in stage_events}
    missing = [t for t in gate.get("required_event_types") or [] if t not in done_types]
    if missing:
        raise SimulationStageError(f"当前阶段还未完成必需动作: {', '.join(missing)}")


async def start_session(db: AsyncSession, student_id: int, scenario_code: str) -> TrainingSession:
    """创建仿真实训会话（绑定既有 TrainingTask，stage 从 briefing 起步）。"""
    scenario = get_scenario(scenario_code)
    task_code = scenario["task_code"]
    task = (
        await db.execute(select(TrainingTask).where(TrainingTask.code == task_code))
    ).scalar_one_or_none()
    if task is None or task.status.value != "published":
        raise ScenarioConfigError(f"仿真任务 {task_code} 未发布（请先执行 seed）")

    sess = TrainingSession(
        student_id=student_id,
        task_id=task.id,
        stage=TrainingStage.briefing,
        scenario_code=scenario_code,
        max_follow_ups=0,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    logger.info("仿真实训开始：student={} session={} scenario={}", student_id, sess.id, scenario_code)
    return sess


async def load_events(db: AsyncSession, session_id: int) -> list[TrainingActionEvent]:
    rows = (
        await db.execute(
            select(TrainingActionEvent)
            .where(TrainingActionEvent.session_id == session_id)
            .order_by(TrainingActionEvent.sequence_no)
        )
    ).scalars().all()
    return list(rows)


async def record_event(
    db: AsyncSession,
    sess: TrainingSession,
    *,
    event_type: str,
    event_code: str = "",
    target_type: str = "",
    target_id: str = "",
    payload: dict[str, Any] | None = None,
) -> TrainingActionEvent:
    """校验当前阶段允许的动作 → 确定性判分 → 落事件表。"""
    scenario = get_scenario(sess.scenario_code)
    stage = _stage_value(sess)
    stage_cfg = (scenario.get("stages") or {}).get(stage)
    if not stage_cfg or stage == TrainingStage.briefing.value:
        raise SimulationStageError(f"阶段 {stage} 不允许提交行为事件")
    allowed = stage_cfg.get("allowed_event_types") or []
    if event_type not in allowed:
        raise SimulationStageError(f"当前阶段不允许事件类型 {event_type}")

    existing = await load_events(db, sess.id)
    # 预解析动作编码以判定重复（同码动作只计首次得分）
    preview = assess_event(
        scenario, stage,
        event_type=event_type, event_code=event_code,
        target_type=target_type, target_id=target_id, payload=payload,
    )
    existing_codes = {e.event_code for e in existing}
    counted = preview.error_type == "unexpected_action" or preview.code not in existing_codes

    outcome = assess_event(
        scenario, stage,
        event_type=event_type, event_code=event_code,
        target_type=target_type, target_id=target_id, payload=payload,
        counted=counted,
    )
    seq = (existing[-1].sequence_no + 1) if existing else 1
    evidence_score = round(outcome.earned / outcome.max_points * 100.0, 2) if outcome.max_points else 0.0
    event = TrainingActionEvent(
        session_id=sess.id,
        student_id=sess.student_id,
        event_type=event_type,
        event_code=outcome.code,
        target_type=target_type,
        target_id=target_id or str(
            next((a.get("target_id") for a in stage_cfg.get("actions") or [] if a.get("code") == outcome.code), "")
        ),
        sequence_no=seq,
        payload_json=payload or {},
        ability_key=outcome.ability_key,
        raw_score=outcome.earned,
        evidence_score=evidence_score,
        is_expected=outcome.error_type != "unexpected_action",
        is_critical=outcome.is_critical,
        error_type=outcome.error_type,
    )
    db.add(event)
    sess.attempt_count += 1
    await db.commit()
    await db.refresh(event)
    return event


def replay_outcomes(scenario: dict[str, Any], events: list[TrainingActionEvent]) -> list[ActionOutcome]:
    """按时间序重放事件流做判分（同码取首次得分，重复不计分），保证结果可复核。"""
    stage_of_type: dict[str, str] = {
        et: stage
        for stage, cfg in (scenario.get("stages") or {}).items()
        for et in cfg.get("allowed_event_types") or []
    }
    outcomes: list[ActionOutcome] = []
    scored: set[str] = set()
    for event in events:
        stage = stage_of_type.get(event.event_type, "")
        if not stage:
            continue
        counted = event.event_code not in scored
        outcome = assess_event(
            scenario, stage,
            event_type=event.event_type, event_code=event.event_code,
            target_type=event.target_type, target_id=event.target_id,
            payload=event.payload_json or {}, counted=counted,
        )
        if outcome.error_type != "duplicate_action":
            scored.add(outcome.code)
        outcomes.append(outcome)
    return outcomes


def compute_score(scenario: dict[str, Any], events: list[TrainingActionEvent]) -> SimulationScore:
    return score_session(scenario, replay_outcomes(scenario, events))


async def advance(db: AsyncSession, sess: TrainingSession) -> str:
    """阶段推进（gate 不满足则拒绝）。"""
    scenario = get_scenario(sess.scenario_code)
    stage = _stage_value(sess)
    events = await load_events(db, sess.id)
    check_gate(scenario, stage, events)
    nxt = _next_stage(stage)
    sess.stage = TrainingStage(nxt)
    await db.commit()
    logger.info("仿真实训推进：session={} {}→{}", sess.id, stage, nxt)
    return nxt


async def complete(
    db: AsyncSession,
    sess: TrainingSession,
    service: AbilityProfileService | None = None,
) -> SimulationScore:
    """完成仿真实训：最终 gate 校验 → rubric 聚合 → EvaluationResult → 能力证据。"""
    if _stage_value(sess) != TrainingStage.record.value:
        raise SimulationStageError("仅在记录阶段可完成仿真实训")
    scenario = get_scenario(sess.scenario_code)
    events = await load_events(db, sess.id)
    check_gate(scenario, TrainingStage.record.value, events)

    score = compute_score(scenario, events)

    evaluation = (
        await db.execute(select(EvaluationResult).where(EvaluationResult.session_id == sess.id))
    ).scalar_one_or_none()
    strengths = [
        ability for ability, norm in score.dimension_scores.items() if norm >= 80
    ]
    if evaluation is None:
        evaluation = EvaluationResult(session_id=sess.id)
        db.add(evaluation)
    evaluation.final_score = score.total_score
    evaluation.rule_score = score.total_score  # 仿真实训 100% 规则评分
    evaluation.semantic_score = 0.0
    evaluation.llm_score = 0.0
    evaluation.ability_scores = dict(score.dimension_scores)
    evaluation.strengths = strengths
    evaluation.missing_points = score.missed_actions
    evaluation.error_types = sorted({e["error_type"] for e in score.errors if e["error_type"]})
    evaluation.explanation = (
        f"教学仿真实训《{scenario['title']}》：总分 {score.total_score}/100，"
        f"关键动作遗漏 {len(score.missed_critical)} 项，评分完全由行为事件与 Rubric 确定。"
    )
    evaluation.citations = [
        {"type": "scenario", "id": scenario["scenario_code"], "title": scenario["title"]}
    ]

    # 能力证据投递（P0-1 通道：operation_event / scenario_diagnosis）
    service = service or AbilityProfileService()
    source_map = abilities_for_evidence(scenario)
    for ability, norm in score.dimension_scores.items():
        source = source_map.get(ability, EvidenceSourceType.operation_event.value)
        result = await service.record_evidence(
            db,
            student_id=sess.student_id,
            ability_key=ability,
            source_type=source,
            raw_score=norm,
            source_id=sess.id,
            session_id=sess.id,
            metadata={
                "source": "simulation",
                "scenario_code": scenario["scenario_code"],
                "earned": score.dimension_earned.get(ability, 0.0),
                "critical_missed": score.missed_critical,
            },
        )
        if result is not None:  # §19：回传画像变化与置信度供完成页展示
            score.ability_updates.append(
                {
                    "ability_key": result.ability_key,
                    "before_score": result.before_score,
                    "after_score": result.after_score,
                    "confidence": result.confidence,
                    "evidence_count": result.evidence_count,
                }
            )

    sess.stage = TrainingStage.finished
    sess.finished = True
    sess.finished_at = datetime.now(UTC)
    await db.commit()
    logger.info(
        "仿真实训完成：session={} student={} total={} 维度数={}",
        sess.id, sess.student_id, score.total_score, len(score.dimension_scores),
    )
    return score


def runtime_state(
    sess: TrainingSession,
    events: list[TrainingActionEvent],
    evaluation: EvaluationResult | None,
) -> dict[str, Any]:
    """会话运行时视图（学生端安全数据 + 阶段进度）。"""
    scenario = get_scenario(sess.scenario_code)
    stage = _stage_value(sess)
    stage_cfg = (scenario.get("stages") or {}).get(stage) or {}
    done_codes = {e.event_code for e in events if e.is_expected}  # 执行过（不论得分）
    pending = [
        {"code": a.get("code"), "name": a.get("name"), "critical": bool(a.get("critical"))}
        for a in stage_cfg.get("actions") or []
        if a.get("code") not in done_codes
    ]
    if stage_cfg.get("options") or stage_cfg.get("required_fields"):
        submitted_code = stage_cfg.get("event_code")
        if any(e.event_code == submitted_code for e in events):
            pending = []
    out = {
        "session_id": sess.id,
        "scenario_code": sess.scenario_code,
        "stage": stage,
        "stage_flow": list(SIM_FLOW) + ["finished"],
        "stage_title": stage_cfg.get("title", "任务说明"),
        "stage_goal": stage_cfg.get("goal", ""),
        "allowed_event_types": stage_cfg.get("allowed_event_types") or [],
        "pending_actions": pending,
        "finished": sess.finished,
        "event_count": len(events),
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "event_code": e.event_code,
                "target_id": e.target_id,
                "sequence_no": e.sequence_no,
                "ability_key": e.ability_key,
                "raw_score": e.raw_score,
                "evidence_score": e.evidence_score,
                "is_expected": e.is_expected,
                "is_critical": e.is_critical,
                "error_type": e.error_type,
                "created_at": e.occurred_at.isoformat() if e.occurred_at else None,
            }
            for e in events
        ],
    }
    if sess.finished and evaluation:
        out["evaluation"] = {
            "final_score": evaluation.final_score,
            "dimension_scores": evaluation.ability_scores,
            "strengths": evaluation.strengths,
            "missing_points": evaluation.missing_points,
            "error_types": evaluation.error_types,
            "explanation": evaluation.explanation,
        }
    return out


def heuristic_hint(scenario: dict[str, Any], stage: str, events: list[TrainingActionEvent]) -> str:
    """确定性启发式提示（配置模板 + 未做的关键动作名，不含答案）。"""
    stage_cfg = (scenario.get("stages") or {}).get(stage) or {}
    templates = stage_cfg.get("hint_templates") or []
    template = templates[len(events) % len(templates)] if templates else "请继续按任务目标操作。"
    done_codes = {e.event_code for e in events if e.is_expected}
    missed_critical = [
        str(a.get("name"))
        for a in stage_cfg.get("actions") or []
        if a.get("critical") and a.get("code") not in done_codes
    ]
    hint = f"启发提示：{template}"
    if missed_critical:
        hint += f"（尚未完成的关键观察/动作：{'; '.join(missed_critical)}）"
    return hint
