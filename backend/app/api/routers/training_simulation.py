"""P0-2 操作型仿真实训路由。

端点：
- GET  /api/training/simulation                       — 可用仿真场景列表
- GET  /api/training/simulation/{code}                — 场景详情（学生视图，已剔除答案键）
- POST /api/training/simulation/{code}/start          — 开始仿真实训会话
- GET  /api/training/simulation/sessions/{id}         — 会话运行时状态
- POST /api/training/simulation/sessions/{id}/events  — 提交行为事件（服务端判分）
- POST /api/training/simulation/sessions/{id}/advance — 推进阶段（gate 校验）
- POST /api/training/simulation/sessions/{id}/hint    — 确定性启发式提示（不给答案）
- POST /api/training/simulation/sessions/{id}/complete— 完成并生成评价 + 能力证据

评分全部由 行为事件 + 状态机 + Rubric 确定，LLM 不参与。
注册顺序必须早于 training 路由（避免 GET /training/{session_id} 遮蔽列表路径）。

角色隔离：场景目录（列表/详情）为已治理的只读元数据；
一切会话级端点（start/会话状态/事件/推进/提示/完成）在服务端强制 student 角色，
与前端路由 meta 的 student 声明一致——teacher/admin 无法通过 API 进入学生仿真流程。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api import ok
from app.api.deps import CurrentUser, DBSession, StudentUser
from app.models.training import EvaluationResult, TrainingSession
from app.scenarios import ScenarioConfigError, get_scenario, load_scenarios, student_view
from app.schemas.training_simulation import SimulationEventRequest
from app.services import simulation_session as sim
from app.services.admin_governance import enforce_feature

router = APIRouter(prefix="/training/simulation", tags=["training-simulation"])


@router.get("", summary="可用仿真实训场景列表")
async def list_simulations(user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training")
    out = []
    for code, scenario in load_scenarios().items():
        out.append(
            {
                "scenario_code": code,
                "title": scenario["title"],
                "description": scenario["description"],
                "difficulty": scenario.get("difficulty", 2),
                "estimated_minutes": scenario.get("estimated_minutes", 20),
                "target_abilities": scenario.get("target_abilities", []),
                "teaching_simulation": True,
                "disclaimer": scenario.get("disclaimer", ""),
            }
        )
    return ok(out)


@router.get("/{scenario_code}", summary="仿真实训场景详情（学生视图）")
async def get_simulation(scenario_code: str, user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training")
    try:
        scenario = get_scenario(scenario_code)
    except ScenarioConfigError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ok(student_view(scenario))


@router.post("/{scenario_code}/start", summary="开始仿真实训")
async def start_simulation(
    scenario_code: str, user: StudentUser, session: DBSession
) -> dict:
    await enforce_feature(session, user, "training", write=True)
    uid = int(user["user_id"])
    try:
        sess = await sim.start_session(session, uid, scenario_code)
    except ScenarioConfigError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ok(sim.runtime_state(sess, [], None))


async def _load_sim_session(session_id: int, uid: int, db) -> TrainingSession:
    sess = (
        await db.execute(
            select(TrainingSession).where(
                TrainingSession.id == session_id,
                TrainingSession.student_id == uid,
            )
        )
    ).scalar_one_or_none()
    if sess is None or not sess.scenario_code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="仿真实训会话不存在")
    return sess


@router.get("/sessions/{session_id}", summary="仿真实训会话状态")
async def get_sim_session(session_id: int, user: StudentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training")
    uid = int(user["user_id"])
    sess = await _load_sim_session(session_id, uid, session)
    events = await sim.load_events(session, sess.id)
    evaluation = (
        await session.execute(
            select(EvaluationResult).where(EvaluationResult.session_id == sess.id)
        )
    ).scalar_one_or_none()
    return ok(sim.runtime_state(sess, events, evaluation))


@router.post("/sessions/{session_id}/events", summary="提交行为事件")
async def submit_event(
    session_id: int,
    body: SimulationEventRequest,
    user: StudentUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "training", write=True)
    uid = int(user["user_id"])
    sess = await _load_sim_session(session_id, uid, session)
    try:
        event = await sim.record_event(
            session,
            sess,
            event_type=body.event_type,
            event_code=body.event_code,
            target_type=body.target_type,
            target_id=body.target_id,
            payload=body.payload,
        )
    except sim.SimulationStageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    events = await sim.load_events(session, sess.id)
    return ok(
        {
            "event": {
                "id": event.id,
                "event_type": event.event_type,
                "event_code": event.event_code,
                "raw_score": event.raw_score,
                "evidence_score": event.evidence_score,
                "is_expected": event.is_expected,
                "is_critical": event.is_critical,
                "error_type": event.error_type,
            },
            "runtime": sim.runtime_state(sess, events, None),
        }
    )


@router.post("/sessions/{session_id}/advance", summary="推进实训阶段")
async def advance_session(session_id: int, user: StudentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training", write=True)
    uid = int(user["user_id"])
    sess = await _load_sim_session(session_id, uid, session)
    try:
        await sim.advance(session, sess)
    except sim.SimulationStageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    events = await sim.load_events(session, sess.id)
    return ok(sim.runtime_state(sess, events, None))


@router.post("/sessions/{session_id}/hint", summary="启发式提示（不含答案）")
async def session_hint(session_id: int, user: StudentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training")
    uid = int(user["user_id"])
    sess = await _load_sim_session(session_id, uid, session)
    scenario = get_scenario(sess.scenario_code)
    events = await sim.load_events(session, sess.id)
    stage = sess.stage.value if hasattr(sess.stage, "value") else str(sess.stage)
    return ok({"hint": sim.heuristic_hint(scenario, stage, events)})


@router.post("/sessions/{session_id}/complete", summary="完成仿真实训并生成评价")
async def complete_session(session_id: int, user: StudentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training", write=True)
    uid = int(user["user_id"])
    sess = await _load_sim_session(session_id, uid, session)
    try:
        score = await sim.complete(session, sess)
    except sim.SimulationStageError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    scenario = get_scenario(sess.scenario_code)
    events = await sim.load_events(session, sess.id)
    evaluation = (
        await session.execute(
            select(EvaluationResult).where(EvaluationResult.session_id == sess.id)
        )
    ).scalar_one_or_none()
    source_map = sim.abilities_for_evidence(scenario)
    updates = {u["ability_key"]: u for u in score.ability_updates}
    return ok(
        {
            "total_score": score.total_score,
            "dimension_scores": score.dimension_scores,
            "errors": score.errors,
            "missed_actions": score.missed_actions,
            "missed_critical": score.missed_critical,
            "critical_evidence": [
                {
                    "event_code": e.event_code,
                    "event_type": e.event_type,
                    "raw_score": e.raw_score,
                    "error_type": e.error_type,
                }
                for e in events
                if e.is_critical
            ],
            "ability_evidence": [
                {
                    "ability_key": ability,
                    "source_type": source_map.get(ability, "operation_event"),
                    "score": norm,
                    "earned": score.dimension_earned.get(ability, 0.0),
                    # §19 能力变化 / 置信度（证据被画像采纳时才有值）
                    "before_score": updates.get(ability, {}).get("before_score"),
                    "after_score": updates.get(ability, {}).get("after_score"),
                    "confidence": updates.get(ability, {}).get("confidence"),
                    "evidence_count": updates.get(ability, {}).get("evidence_count"),
                }
                for ability, norm in score.dimension_scores.items()
            ],
            "feedback_summary": {
                "explanation": evaluation.explanation if evaluation else "",
                "strengths": evaluation.strengths if evaluation else [],
                "disclaimer": scenario.get("disclaimer", ""),
            },
        }
    )
