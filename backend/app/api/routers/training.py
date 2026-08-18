"""数据驱动的选择题实训路由。

链路：选择任务 → 读取数据库题库 → 逐题选择 → 规则评分 → 能力画像更新。
训练评分不调用大模型，题目、选项、分值和反馈均可审计。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.core.enums import TaskStatus, TrainingStage
from app.core.logging import logger
from app.models.training import (
    EvaluationResult,
    StudentAnswer,
    TrainingChoiceAnswer,
    TrainingQuestion,
    TrainingScenario,
    TrainingSession,
    TrainingTask,
)
from app.schemas.training import (
    TrainingChoiceSubmitRequest,
    TrainingSessionOut,
    TrainingStartRequest,
    TrainingTaskOut,
)
from app.services.admin_governance import enforce_feature
from app.services.knowledge_evidence import KnowledgeEvidenceService

router = APIRouter(prefix="/training", tags=["training"])


def _session_questions(sess: TrainingSession) -> list[TrainingQuestion]:
    """锁定会话开始时的题库批次，教师发布新版时不影响进行中的学生。"""
    task_questions = sess.task.questions if sess.task else []
    if sess.question_batch_code:
        selected = [item for item in task_questions if item.batch_code == sess.question_batch_code]
    else:
        selected = [
            item for item in task_questions if item.active and item.status == "published"
        ]
    return sorted(selected, key=lambda item: item.sort_order)


def _question_out(question: TrainingQuestion | None) -> dict | None:
    """学生作答前只返回选项内容，不泄露分值和正确答案。"""
    if question is None:
        return None
    return {
        "id": question.id,
        "code": question.code,
        "stem": question.stem,
        "ability_key": question.ability_key,
        "knowledge_point": question.knowledge_point,
        "sort_order": question.sort_order,
        "generated_by_ai": question.generated_by_ai,
        "options": [
            {"id": option.id, "key": option.option_key, "content": option.content}
            for option in sorted(question.options or [], key=lambda item: item.option_key)
        ],
    }


def _answer_record(answer: TrainingChoiceAnswer) -> dict:
    question = answer.question
    option = answer.option
    max_score = question.max_score if question else 100
    return {
        "question_id": answer.question_id,
        "question_code": question.code if question else "",
        "stem": question.stem if question else "",
        "ability_key": question.ability_key if question else "",
        "knowledge_point": question.knowledge_point if question else "",
        "selected_option_id": answer.option_id,
        "selected_option_key": option.option_key if option else "",
        "selected_option_content": option.content if option else "",
        "score": answer.score,
        "max_score": max_score,
        "is_correct": bool(option and option.is_correct),
        "feedback": option.feedback if option else "",
        "explanation": question.explanation if question else "",
    }


def _session_to_out(
    sess: TrainingSession,
    evidence_citations: list[dict] | None = None,
    last_feedback: dict | None = None,
) -> TrainingSessionOut:
    task = sess.task
    scenario_text = ""
    if task and isinstance(task.scenario, dict):
        scenario_text = task.scenario.get("scenario_text", "")

    questions = _session_questions(sess)
    answer_records = [
        _answer_record(answer)
        for answer in sorted(sess.choice_answers or [], key=lambda item: item.question.sort_order)
    ]
    answered_ids = {answer.question_id for answer in (sess.choice_answers or [])}
    current_question = next((question for question in questions if question.id not in answered_ids), None)

    eval_out = None
    citations = evidence_citations or []
    if sess.evaluation:
        evaluation = sess.evaluation
        citations = evaluation.citations or citations
        eval_out = {
            "final_score": evaluation.final_score,
            "rule_score": evaluation.rule_score,
            "semantic_score": evaluation.semantic_score,
            "llm_score": evaluation.llm_score,
            "ability_scores": evaluation.ability_scores or {},
            "strengths": evaluation.strengths or [],
            "missing_points": evaluation.missing_points or [],
            "error_types": evaluation.error_types or [],
            "explanation": evaluation.explanation,
            "citations": citations,
            "scoring_mode": "database_choice_rule",
        }

    messages = [
        {
            "role": "student",
            "content": f"{item['selected_option_key']}. {item['selected_option_content']}",
            "round": str(index + 1),
        }
        for index, item in enumerate(answer_records)
    ]
    current_stem = current_question.stem if current_question and not sess.finished else ""
    return TrainingSessionOut(
        id=sess.id,
        task_code=task.code if task else "",
        task_title=task.title if task else "",
        stage=sess.stage.value if isinstance(sess.stage, TrainingStage) else str(sess.stage),
        attempt_count=len(answer_records),
        follow_up_count=len(answer_records),
        max_follow_ups=len(questions),
        finished=sess.finished,
        current_coach_question=current_stem,
        mode="choice",
        question_count=len(questions),
        answered_count=len(answer_records),
        current_question=_question_out(current_question) if not sess.finished else None,
        answer_records=answer_records,
        last_answer_feedback=last_feedback,
        scenario_text=scenario_text,
        messages=messages,
        evidence_citations=citations,
        evaluation=eval_out,
        created_at=sess.created_at.isoformat() if sess.created_at else "",
    )


def _session_options():
    return (
        selectinload(TrainingSession.task)
        .selectinload(TrainingTask.questions)
        .selectinload(TrainingQuestion.options),
        selectinload(TrainingSession.answers),
        selectinload(TrainingSession.choice_answers).selectinload(TrainingChoiceAnswer.question),
        selectinload(TrainingSession.choice_answers).selectinload(TrainingChoiceAnswer.option),
        selectinload(TrainingSession.evaluation),
    )


async def _load_session(session_id: int, uid: int, db: DBSession) -> TrainingSession:
    stmt = select(TrainingSession).options(*_session_options()).where(
        TrainingSession.id == session_id,
        TrainingSession.student_id == uid,
    )
    sess = (await db.execute(stmt)).scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="实训会话不存在")
    return sess


@router.get("/tasks", summary="可用选择题实训任务列表")
async def list_tasks(user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training")
    stmt = (
        select(TrainingTask)
        .options(selectinload(TrainingTask.questions))
        .where(TrainingTask.status == TaskStatus.published)
        .order_by(TrainingTask.id)
    )
    tasks = (await session.execute(stmt)).scalars().all()
    out = []
    for task in tasks:
        question_count = len(
            [question for question in task.questions if question.active and question.status == "published"]
        )
        if question_count == 0:
            continue
        out.append(
            TrainingTaskOut(
                id=task.id,
                code=task.code,
                title=task.title,
                description=task.description,
                difficulty=task.difficulty,
                target_abilities=task.target_abilities or [],
                estimated_minutes=task.estimated_minutes,
                max_follow_ups=question_count,
                mode="choice",
                question_count=question_count,
            ).model_dump()
        )
    return ok(out)


@router.get("/sessions", summary="我的实训会话列表")
async def list_sessions(user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training")
    uid = int(user["user_id"])
    stmt = (
        select(TrainingSession)
        .options(*_session_options())
        .where(TrainingSession.student_id == uid)
        .order_by(TrainingSession.created_at.desc())
    )
    sessions = (await session.execute(stmt)).scalars().all()
    return ok([_session_to_out(item).model_dump() for item in sessions])


@router.post("/start", summary="开始选择题实训")
async def start_training(body: TrainingStartRequest, user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training", write=True)
    uid = int(user["user_id"])
    stmt = (
        select(TrainingTask)
        .options(selectinload(TrainingTask.questions).selectinload(TrainingQuestion.options))
        .where(TrainingTask.code == body.task_code, TrainingTask.status == TaskStatus.published)
    )
    task = (await session.execute(stmt)).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="训练任务不存在")
    questions = sorted(
        [item for item in task.questions if item.active and item.status == "published"],
        key=lambda item: item.sort_order,
    )
    if not questions or any(not item.options for item in questions):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该任务尚未配置完整的选择题题库")

    scenario_stmt = select(TrainingScenario).where(TrainingScenario.task_id == task.id)
    scenario = (await session.execute(scenario_stmt)).scalar_one_or_none()
    scenario_data = dict(task.scenario or {})
    if scenario:
        scenario_data["scenario_text"] = scenario.scenario_text
        scenario_data["conditions"] = scenario.conditions or {}
    if not scenario_data.get("scenario_text"):
        scenario_data["scenario_text"] = f"【教学模拟】请完成“{task.title}”岗位情境选择题。"
    task.scenario = scenario_data

    evidence = await KnowledgeEvidenceService().get_for_task(session, task)
    citations = _evidence_citations(evidence)
    sess = TrainingSession(
        student_id=uid,
        task_id=task.id,
        stage=TrainingStage.answering,
        max_follow_ups=len(questions),
        current_coach_question=questions[0].stem,
        question_batch_code=questions[0].batch_code,
    )
    session.add(sess)
    await session.commit()
    sess = await _load_session(sess.id, uid, session)
    return ok(_session_to_out(sess, citations).model_dump())


@router.post("/{session_id}/answer-choice", summary="提交选择题答案")
async def submit_choice(
    session_id: int,
    body: TrainingChoiceSubmitRequest,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "training", write=True)
    uid = int(user["user_id"])
    sess = await _load_session(session_id, uid, session)
    if sess.finished:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="实训已完成")

    questions = _session_questions(sess)
    answered_ids = {item.question_id for item in sess.choice_answers}
    current = next((item for item in questions if item.id not in answered_ids), None)
    if current is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="没有待作答题目")
    if body.question_id != current.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请按题目顺序作答")
    option = next((item for item in current.options if item.id == body.option_id), None)
    if option is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="选项不属于当前题目")

    round_num = len(sess.choice_answers) + 1
    choice_answer = TrainingChoiceAnswer(
        session=sess,
        question_id=current.id,
        option_id=option.id,
        score=min(max(option.score, 0), current.max_score),
        question=current,
        option=option,
    )
    session.add(choice_answer)
    session.add(
        StudentAnswer(
            session_id=sess.id,
            round=round_num,
            content=f"{option.option_key}. {option.content}",
            is_follow_up=False,
        )
    )
    # 通过 relationship 挂入当前会话，避免同一 AsyncSession 身份映射返回旧集合，
    # 从而确保响应中的 current_question 立即推进到下一题。
    all_answers = list(sess.choice_answers)
    sess.attempt_count = len(all_answers)
    sess.follow_up_count = len(all_answers)

    remaining = [item for item in questions if item.id not in answered_ids and item.id != current.id]
    feedback = {
        "question_id": current.id,
        "selected_option_key": option.option_key,
        "score": choice_answer.score,
        "max_score": current.max_score,
        "is_correct": option.is_correct,
        "feedback": option.feedback,
        "explanation": current.explanation,
    }
    evidence = await KnowledgeEvidenceService().get_for_task(session, sess.task)
    citations = _evidence_citations(evidence)

    if remaining:
        sess.stage = TrainingStage.answering
        sess.current_coach_question = remaining[0].stem
    else:
        sess.stage = TrainingStage.finished
        sess.finished = True
        sess.finished_at = datetime.now(UTC)
        sess.current_coach_question = ""
        evaluation_data = _build_evaluation(all_answers, citations)
        evaluation = EvaluationResult(session_id=sess.id, **evaluation_data)
        sess.evaluation = evaluation
        session.add(evaluation)
        await _update_ability_profile(evaluation_data, sess, session)

    await session.commit()
    sess = await _load_session(session_id, uid, session)
    return ok(_session_to_out(sess, citations, feedback).model_dump())


@router.post("/{session_id}/submit", summary="旧版文本作答入口（已停用）", deprecated=True)
async def submit_legacy(session_id: int, user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training", write=True)
    uid = int(user["user_id"])
    await _load_session(session_id, uid, session)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="文本问答实训已升级为选择题，请刷新页面后选择选项作答",
    )


@router.get("/{session_id}", summary="实训会话详情")
async def get_session(session_id: int, user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "training")
    uid = int(user["user_id"])
    sess = await _load_session(session_id, uid, session)
    citations = sess.evaluation.citations if sess.evaluation else _evidence_citations(
        await KnowledgeEvidenceService().get_for_task(session, sess.task)
    )
    return ok(_session_to_out(sess, citations).model_dump())


def _build_evaluation(answers: list[TrainingChoiceAnswer], citations: list[dict]) -> dict:
    """按题库配置确定性评分，不调用 LLM。"""
    total_score = sum(answer.score for answer in answers)
    total_max = sum(answer.question.max_score for answer in answers) or 1
    final_score = round(total_score * 100 / total_max)

    ability_points: dict[str, list[float]] = defaultdict(list)
    for answer in answers:
        ability = answer.question.ability_key or "general"
        max_score = answer.question.max_score or 100
        ability_points[ability].append(answer.score * 100 / max_score)
    ability_scores = {
        key: round(sum(values) / len(values)) for key, values in ability_points.items() if key != "general"
    }
    strengths = [key for key, value in ability_scores.items() if value >= 80]
    missing_points = [
        answer.question.knowledge_point or answer.question.stem
        for answer in answers
        if answer.score < answer.question.max_score * 0.6
    ]
    error_types = ["knowledge_choice_error"] if missing_points else []
    correct_count = sum(1 for answer in answers if answer.option.is_correct)
    explanation = (
        f"本次共完成 {len(answers)} 道岗位情境选择题，答对 {correct_count} 道。"
        f"成绩由数据库选项分值确定，得分 {final_score} 分；不使用语义相似度或大模型评分。"
    )
    return {
        "final_score": final_score,
        "rule_score": final_score,
        "semantic_score": 0,
        "llm_score": 0,
        "ability_scores": ability_scores,
        "strengths": strengths,
        "missing_points": missing_points,
        "error_types": error_types,
        "explanation": explanation,
        "citations": citations,
    }


def _evidence_citations(evidence: list[dict]) -> list[dict]:
    keys = (
        "knowledge_id",
        "title",
        "source_name",
        "source_no",
        "chapter",
        "page",
        "is_teaching_simulation",
    )
    return [{key: item.get(key) for key in keys} for item in evidence]


async def _update_ability_profile(
    evaluation_data: dict, sess: TrainingSession, session: DBSession
) -> None:
    try:
        from app.services.ability_profile import AbilityProfileService

        await AbilityProfileService().update_from_training(
            db=session,
            student_id=sess.student_id,
            session_id=sess.id,
            target_abilities=(sess.task.target_abilities if sess.task else []) or [],
            final_score=float(evaluation_data["final_score"]),
            ability_scores=evaluation_data["ability_scores"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("能力画像更新失败（不影响训练完成）：{}", exc)


__all__ = ["router"]
