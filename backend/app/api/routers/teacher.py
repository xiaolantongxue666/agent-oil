"""教师管理路由（PHASE 12）。

端点：
- GET  /api/teacher/students        — 学生列表 + 概览统计
- GET  /api/teacher/students/{id}   — 单个学生画像
- GET  /api/teacher/students/{id}/history — 学生训练历史
- GET  /api/teacher/tasks           — 全部任务（含草稿）
- POST /api/teacher/tasks           — 新建任务
- PUT  /api/teacher/tasks/{id}      — 更新任务
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.core.enums import ABILITY_CN, AbilityKey, TaskStatus
from app.llm import get_gateway
from app.models.ability import AbilityScore
from app.models.position import Ability
from app.models.training import (
    EvaluationResult,
    TeachingPlan,
    TrainingChoiceAnswer,
    TrainingOption,
    TrainingQuestion,
    TrainingSession,
    TrainingTask,
)
from app.models.user import User, UserRole
from app.services.admin_governance import audit, enforce_feature
from app.services.knowledge_evidence import KnowledgeEvidenceService
from app.services.training_question_generator import TrainingQuestionGenerator

router = APIRouter(prefix="/teacher", tags=["teacher"])


def _require_teacher(user: CurrentUser) -> None:
    role = user.get("role", "")
    if role not in ("teacher", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要教师权限")


# ---------- 学生列表 ----------
@router.get("/students", summary="学生列表")
async def list_students(user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics")
    stmt = select(User).where(User.role == UserRole.student).order_by(User.id)
    students = (await session.execute(stmt)).scalars().all()

    # 预加载 ability id→key 映射
    ability_stmt = select(Ability).order_by(Ability.id)
    abilities = (await session.execute(ability_stmt)).scalars().all()
    ability_map = {a.id: a.key for a in abilities}

    out = []
    for s in students:
        # 完成训练数
        cnt_stmt = (
            select(func.count())
            .select_from(TrainingSession)
            .where(TrainingSession.student_id == s.id, TrainingSession.finished == True)  # noqa: E712
        )
        completed_count = (await session.execute(cnt_stmt)).scalar() or 0

        # 能力总分（平均）
        score_stmt = select(AbilityScore).where(AbilityScore.student_id == s.id)
        scores = (await session.execute(score_stmt)).scalars().all()
        total_score = 0.0
        weakest: str | None = None
        weakest_score = 999.0
        if scores:
            total_score = sum(sc.score for sc in scores) / len(scores)
            for sc in scores:
                if sc.score < weakest_score:
                    weakest_score = sc.score
                    weakest = ability_map.get(sc.ability_id)

        out.append(
            {
                "id": s.id,
                "username": s.username,
                "real_name": s.real_name,
                "student_no": s.student_no or "",
                "class_name": s.class_name or "",
                "total_score": round(total_score, 1),
                "completed_count": completed_count,
                "weakest_ability": weakest,
            }
        )
    return ok(out)


# ---------- 学生画像 ----------
@router.get("/students/{student_id}", summary="学生画像")
async def student_profile(student_id: int, user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics")
    stmt = select(User).where(User.id == student_id, User.role == UserRole.student)
    student = (await session.execute(stmt)).scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="学生不存在")

    # 能力画像
    from app.services.ability_profile import AbilityProfileService

    svc = AbilityProfileService()
    profile = await svc.get_profile(session, student_id)
    radar = await svc.get_radar_data(session, student_id)

    # 训练统计
    cnt_stmt = (
        select(func.count())
        .select_from(TrainingSession)
        .where(TrainingSession.student_id == student_id, TrainingSession.finished == True)  # noqa: E712
    )
    completed_count = (await session.execute(cnt_stmt)).scalar() or 0

    avg_stmt = (
        select(func.avg(EvaluationResult.final_score))
        .join(TrainingSession, TrainingSession.id == EvaluationResult.session_id)
        .where(TrainingSession.student_id == student_id)
    )
    avg_score = (await session.execute(avg_stmt)).scalar() or 0

    return ok(
        {
            "id": student.id,
            "username": student.username,
            "real_name": student.real_name,
            "student_no": student.student_no or "",
            "class_name": student.class_name or "",
            "profile": profile,
            "radar": radar,
            "completed_count": completed_count,
            "avg_score": round(float(avg_score), 1),
        }
    )


# ---------- 学生训练历史 ----------
@router.get("/students/{student_id}/history", summary="学生训练历史")
async def student_history(student_id: int, user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics")
    stmt = (
        select(TrainingSession)
        .options(
            selectinload(TrainingSession.task),
            selectinload(TrainingSession.evaluation),
        )
        .where(TrainingSession.student_id == student_id)
        .order_by(TrainingSession.created_at.desc())
        .limit(50)
    )
    sessions = (await session.execute(stmt)).scalars().all()
    out = []
    for s in sessions:
        out.append(
            {
                "id": s.id,
                "task_title": s.task.title if s.task else "",
                "task_code": s.task.code if s.task else "",
                "finished": s.finished,
                "stage": s.stage.value if hasattr(s.stage, "value") else str(s.stage),
                "attempt_count": s.attempt_count,
                "final_score": s.evaluation.final_score if s.evaluation else None,
                "created_at": s.created_at.isoformat() if s.created_at else "",
            }
        )
    return ok(out)


# ---------- 任务管理 ----------
@router.get("/tasks", summary="全部任务（含草稿）")
async def list_tasks(user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "training")
    stmt = select(TrainingTask).options(selectinload(TrainingTask.questions)).order_by(TrainingTask.id)
    tasks = (await session.execute(stmt)).scalars().all()
    out = []
    for t in tasks:
        st = t.status.value if hasattr(t.status, "value") else str(t.status)
        out.append(
            {
                "id": t.id,
                "code": t.code,
                "title": t.title,
                "description": t.description,
                "difficulty": t.difficulty,
                "target_abilities": t.target_abilities or [],
                "estimated_minutes": t.estimated_minutes,
                "max_follow_ups": t.max_follow_ups,
                "mode": "choice",
                "question_count": len(
                    [
                        question
                        for question in t.questions
                        if question.active and question.status == "published"
                    ]
                ),
                "required_points": t.required_points or [],
                "reference_points": t.reference_points or [],
                "scenario": t.scenario or {},
                "status": st,
            }
        )
    return ok(out)


class TaskCreateBody(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    difficulty: int = Field(2, ge=1, le=5)
    target_abilities: list[str] = Field(default_factory=list)
    estimated_minutes: int = Field(15, ge=5, le=120)
    max_follow_ups: int = Field(3, ge=1, le=5)
    required_points: list[str] = Field(default_factory=list)
    reference_points: list[str] = Field(default_factory=list)
    scenario: dict[str, Any] = Field(default_factory=dict)


@router.post("/tasks", summary="新建任务")
async def create_task(body: TaskCreateBody, user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "training", write=True)
    existing = (
        await session.execute(select(TrainingTask).where(TrainingTask.code == body.code))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务编号已存在")

    task = TrainingTask(
        code=body.code,
        title=body.title,
        description=body.description,
        difficulty=body.difficulty,
        target_abilities=body.target_abilities,
        estimated_minutes=body.estimated_minutes,
        max_follow_ups=body.max_follow_ups,
        required_points=body.required_points,
        reference_points=body.reference_points,
        scenario=body.scenario,
        status=TaskStatus.draft,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return ok({"id": task.id, "code": task.code, "title": task.title})


class TaskUpdateBody(BaseModel):
    title: str | None = None
    description: str | None = None
    difficulty: int | None = None
    target_abilities: list[str] | None = None
    estimated_minutes: int | None = None
    max_follow_ups: int | None = None
    required_points: list[str] | None = None
    reference_points: list[str] | None = None
    scenario: dict[str, Any] | None = None
    status: str | None = None


@router.put("/tasks/{task_id}", summary="更新任务")
async def update_task(
    task_id: int, body: TaskUpdateBody, user: CurrentUser, session: DBSession
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "training", write=True)
    task = (
        await session.execute(select(TrainingTask).where(TrainingTask.id == task_id))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    if body.title is not None:
        task.title = body.title
    if body.description is not None:
        task.description = body.description
    if body.difficulty is not None:
        task.difficulty = body.difficulty
    if body.target_abilities is not None:
        task.target_abilities = body.target_abilities
    if body.estimated_minutes is not None:
        task.estimated_minutes = body.estimated_minutes
    if body.max_follow_ups is not None:
        task.max_follow_ups = body.max_follow_ups
    if body.required_points is not None:
        task.required_points = body.required_points
    if body.reference_points is not None:
        task.reference_points = body.reference_points
    if body.scenario is not None:
        task.scenario = body.scenario
    if body.status is not None:
        task.status = TaskStatus(body.status)

    await session.commit()
    await session.refresh(task)
    return ok({"id": task.id, "code": task.code, "title": task.title})


# ---------- AI 题库草稿与教师审核 ----------
class QuestionGenerateBody(BaseModel):
    count: int = Field(3, ge=1, le=10)
    difficulty: int | None = Field(None, ge=1, le=5)
    focus_points: list[str] = Field(default_factory=list, max_length=20)
    generation_mode: str = Field("ai", pattern="^(ai|local_rule)$")
    confirm_external: bool = False


class QuestionOptionBody(BaseModel):
    key: str = Field(..., min_length=1, max_length=8)
    content: str = Field(..., min_length=1, max_length=1000)
    score: int = Field(..., ge=0, le=100)
    feedback: str = Field("", max_length=2000)
    is_correct: bool = False


class QuestionUpdateBody(BaseModel):
    stem: str = Field(..., min_length=5, max_length=2000)
    ability_key: str = Field(..., min_length=1, max_length=64)
    knowledge_point: str = Field(..., min_length=1, max_length=128)
    explanation: str = Field(..., min_length=5, max_length=3000)
    options: list[QuestionOptionBody] = Field(..., min_length=4, max_length=4)


def _question_admin_out(question: TrainingQuestion) -> dict:
    return {
        "id": question.id,
        "task_id": question.task_id,
        "code": question.code,
        "stem": question.stem,
        "ability_key": question.ability_key,
        "knowledge_point": question.knowledge_point,
        "explanation": question.explanation,
        "sort_order": question.sort_order,
        "max_score": question.max_score,
        "active": question.active,
        "status": question.status,
        "batch_code": question.batch_code,
        "generated_by_ai": question.generated_by_ai,
        "generation_meta": question.generation_meta or {},
        "reviewed_by": question.reviewed_by,
        "reviewed_at": question.reviewed_at.isoformat() if question.reviewed_at else "",
        "options": [
            {
                "id": option.id,
                "key": option.option_key,
                "content": option.content,
                "score": option.score,
                "feedback": option.feedback,
                "is_correct": option.is_correct,
            }
            for option in sorted(question.options or [], key=lambda item: item.option_key)
        ],
    }


def _validate_question_options(options: list[QuestionOptionBody]) -> None:
    keys = [item.key.upper() for item in options]
    if sorted(keys) != ["A", "B", "C", "D"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="选项必须为 A、B、C、D 且不能重复")
    correct = [item for item in options if item.is_correct]
    if len(correct) != 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="每道单选题必须且只能有一个正确选项")
    if correct[0].score != 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="正确选项分值必须为 100")
    if any(not item.is_correct and item.score >= 100 for item in options):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非正确选项分值必须低于 100")


@router.get("/tasks/{task_id}/questions", summary="教师查看任务题库与审核批次")
async def list_task_questions(
    task_id: int,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "training")
    task = (
        await session.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.questions).selectinload(TrainingQuestion.options))
            .where(TrainingTask.id == task_id)
        )
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    questions = sorted(task.questions, key=lambda item: (item.created_at, item.sort_order), reverse=True)
    batches: dict[str, dict[str, Any]] = {}
    for question in questions:
        batch = batches.setdefault(
            question.batch_code,
            {
                "batch_code": question.batch_code,
                "status": question.status,
                "question_count": 0,
                "generated_by_ai": question.generated_by_ai,
                "generation_meta": question.generation_meta or {},
                "created_at": question.created_at.isoformat() if question.created_at else "",
            },
        )
        batch["question_count"] += 1
    evidence = await KnowledgeEvidenceService().get_for_task(session, task)
    citations = [
        {
            key: item.get(key)
            for key in ("knowledge_id", "title", "source_name", "source_no", "chapter", "page")
        }
        for item in evidence
    ]
    return ok(
        {
            "task": {
                "id": task.id,
                "code": task.code,
                "title": task.title,
                "difficulty": task.difficulty,
                "target_abilities": task.target_abilities or [],
                "knowledge_points": task.knowledge_points or [],
                "required_points": task.required_points or [],
            },
            "items": [_question_admin_out(question) for question in questions],
            "batches": sorted(batches.values(), key=lambda item: item["created_at"], reverse=True),
            "evidence_citations": citations,
        }
    )


@router.post("/tasks/{task_id}/questions/generate", summary="依据任务和权威知识生成题库草稿")
async def generate_task_questions(
    task_id: int,
    body: QuestionGenerateBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "training", write=True)
    task = (
        await session.execute(select(TrainingTask).where(TrainingTask.id == task_id))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    evidence = await KnowledgeEvidenceService().get_for_task(session, task)
    focus_points = [item.strip() for item in body.focus_points if item.strip()]
    generator = TrainingQuestionGenerator()
    if body.generation_mode == "ai":
        provider_name = get_gateway().provider_name
        if provider_name != "mock" and not body.confirm_external:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "AI 生成会将本任务元数据及关联权威知识摘要发送至当前配置的外部模型服务。"
                    "请教师确认数据发送授权，或改用本地规则模板。"
                ),
            )
        generation = await generator.generate(
            task,
            evidence,
            count=body.count,
            difficulty=body.difficulty or task.difficulty,
            focus_points=focus_points,
        )
    else:
        generation = generator.generate_offline(
            task,
            evidence,
            count=body.count,
            difficulty=body.difficulty or task.difficulty,
            focus_points=focus_points,
        )
    batch_code = f"ai-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    citations = [
        {
            key: item.get(key)
            for key in ("knowledge_id", "title", "source_name", "source_no", "chapter", "page")
        }
        for item in evidence
    ]
    generation_meta = {
        "provider": generation.provider,
        "used_fallback": generation.used_fallback,
        "attempts": generation.attempts,
        "warning": generation.warning,
        "difficulty": body.difficulty or task.difficulty,
        "focus_points": body.focus_points,
        "generation_mode": body.generation_mode,
        "external_transfer_confirmed": bool(body.generation_mode == "ai" and body.confirm_external),
        "evidence_citations": citations,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    questions: list[TrainingQuestion] = []
    for index, draft in enumerate(generation.questions, 1):
        question = TrainingQuestion(
            task_id=task.id,
            code=f"{task.code}-{batch_code[-6:]}-Q{index:02d}",
            stem=draft.stem,
            ability_key=draft.ability_key,
            knowledge_point=draft.knowledge_point,
            explanation=draft.explanation,
            sort_order=index,
            max_score=100,
            active=False,
            status="draft",
            batch_code=batch_code,
            generated_by_ai=body.generation_mode == "ai",
            generation_meta=generation_meta,
        )
        question.options = [
            TrainingOption(
                option_key=option.key,
                content=option.content,
                score=option.score,
                feedback=option.feedback,
                is_correct=option.is_correct,
            )
            for option in draft.options
        ]
        session.add(question)
        questions.append(question)
    await session.commit()
    return ok(
        {
            "batch_code": batch_code,
            "question_count": len(questions),
            "provider": generation.provider,
            "used_fallback": generation.used_fallback,
            "warning": generation.warning,
            "items": [_question_admin_out(question) for question in questions],
        }
    )


@router.put("/questions/{question_id}", summary="教师编辑题库草稿")
async def update_question_draft(
    question_id: int,
    body: QuestionUpdateBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "training", write=True)
    _validate_question_options(body.options)
    if body.ability_key not in {item.value for item in AbilityKey}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="能力维度无效")
    question = (
        await session.execute(
            select(TrainingQuestion)
            .options(selectinload(TrainingQuestion.options))
            .where(TrainingQuestion.id == question_id)
        )
    ).scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题目不存在")
    if question.status != "draft":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只能编辑尚未发布的题库草稿")
    question.stem = body.stem.strip()
    question.ability_key = body.ability_key
    question.knowledge_point = body.knowledge_point.strip()
    question.explanation = body.explanation.strip()
    for existing in list(question.options):
        await session.delete(existing)
    await session.flush()
    question.options = [
        TrainingOption(
            option_key=option.key.upper(),
            content=option.content.strip(),
            score=option.score,
            feedback=option.feedback.strip(),
            is_correct=option.is_correct,
        )
        for option in body.options
    ]
    # P1-2 效果评估：教师修订 AI 草稿题目（区分"一次通过"与"修改后通过"）
    if question.generated_by_ai:
        await audit(
            session,
            int(user["user_id"]),
            "question_draft.modify",
            "training_question",
            question.id,
            {"batch_code": question.batch_code},
        )
    await session.commit()
    return ok(_question_admin_out(question))


@router.post(
    "/tasks/{task_id}/questions/batches/{batch_code}/publish",
    summary="审核并发布整批题库",
)
async def publish_question_batch(
    task_id: int,
    batch_code: str,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "training", write=True)
    task = (
        await session.execute(
            select(TrainingTask)
            .options(selectinload(TrainingTask.questions).selectinload(TrainingQuestion.options))
            .where(TrainingTask.id == task_id)
        )
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    batch = [question for question in task.questions if question.batch_code == batch_code]
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="题库批次不存在")
    if any(question.status != "draft" for question in batch):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有草稿批次可以审核发布")
    for question in batch:
        options = [
            QuestionOptionBody(
                key=option.option_key,
                content=option.content,
                score=option.score,
                feedback=option.feedback,
                is_correct=option.is_correct,
            )
            for option in question.options
        ]
        _validate_question_options(options)
        if not question.stem.strip() or not question.explanation.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"题目 {question.code} 信息不完整")

    for question in task.questions:
        if question.status == "published" and question.batch_code != batch_code:
            question.status = "archived"
            question.active = False
    reviewed_at = datetime.now(UTC)
    for index, question in enumerate(sorted(batch, key=lambda item: item.sort_order), 1):
        question.status = "published"
        question.active = True
        question.sort_order = index
        question.reviewed_by = int(user["user_id"])
        question.reviewed_at = reviewed_at
    task.max_follow_ups = len(batch)
    # P1-2 效果评估：批次级审核判定入审计日志（AI 批次用于"一次通过率"分母/分子统计）
    ai_count = sum(1 for question in batch if question.generated_by_ai)
    await audit(
        session,
        int(user["user_id"]),
        "question_batch.publish",
        "question_batch",
        batch_code,
        {"task_id": task.id, "question_count": len(batch), "ai_generated_count": ai_count},
    )
    await session.commit()
    return ok(
        {
            "batch_code": batch_code,
            "status": "published",
            "question_count": len(batch),
            "reviewed_at": reviewed_at.isoformat(),
        }
    )


# ---------- 班级实训结果与课堂实施复盘（不修改专业培养方案） ----------
def _ability_label(key: str) -> str:
    try:
        return ABILITY_CN.get(AbilityKey(key), key)
    except ValueError:
        return key


def _result_load_options():
    return (
        selectinload(TrainingSession.task),
        selectinload(TrainingSession.evaluation),
        selectinload(TrainingSession.choice_answers).selectinload(TrainingChoiceAnswer.question),
        selectinload(TrainingSession.choice_answers).selectinload(TrainingChoiceAnswer.option),
    )


async def _load_training_result_rows(session: DBSession, class_name: str = ""):
    stmt = (
        select(TrainingSession, User)
        .join(User, User.id == TrainingSession.student_id)
        .options(*_result_load_options())
        .where(TrainingSession.finished == True)  # noqa: E712
        .order_by(TrainingSession.finished_at.desc())
    )
    if class_name:
        stmt = stmt.where(User.class_name == class_name)
    return (await session.execute(stmt)).all()


def _training_result_out(training_session: TrainingSession, student: User) -> dict:
    evaluation = training_session.evaluation
    answers = sorted(
        training_session.choice_answers or [],
        key=lambda answer: answer.question.sort_order if answer.question else 0,
    )
    correct_count = sum(1 for answer in answers if answer.option and answer.option.is_correct)
    ability_scores = evaluation.ability_scores if evaluation else {}
    weakest_key = min(ability_scores, key=ability_scores.get) if ability_scores else ""
    return {
        "id": training_session.id,
        "student_id": student.id,
        "student_name": student.real_name or student.username,
        "student_no": student.student_no or "",
        "class_name": student.class_name or "",
        "task_code": training_session.task.code if training_session.task else "",
        "task_title": training_session.task.title if training_session.task else "",
        "final_score": evaluation.final_score if evaluation else 0,
        "question_count": len(answers),
        "correct_count": correct_count,
        "correct_rate": round(correct_count * 100 / len(answers), 1) if answers else 0,
        "ability_scores": ability_scores or {},
        "weakest_ability": weakest_key,
        "weakest_ability_name": _ability_label(weakest_key) if weakest_key else "",
        "finished_at": training_session.finished_at.isoformat() if training_session.finished_at else "",
        "answer_records": [
            {
                "question_code": answer.question.code if answer.question else "",
                "stem": answer.question.stem if answer.question else "",
                "knowledge_point": answer.question.knowledge_point if answer.question else "",
                "selected_option": answer.option.option_key if answer.option else "",
                "selected_content": answer.option.content if answer.option else "",
                "score": answer.score,
                "is_correct": bool(answer.option and answer.option.is_correct),
                "feedback": answer.option.feedback if answer.option else "",
            }
            for answer in answers
        ],
    }


async def _build_training_analysis(session: DBSession, class_name: str = "") -> dict:
    rows = await _load_training_result_rows(session, class_name)
    scores = [float(item.evaluation.final_score) for item, _ in rows if item.evaluation]
    students = {student.id for _, student in rows}

    ability_values: dict[str, list[float]] = {}
    task_values: dict[str, dict[str, Any]] = {}
    question_values: dict[int, dict[str, Any]] = {}
    for training_session, _student in rows:
        if training_session.evaluation:
            for key, value in (training_session.evaluation.ability_scores or {}).items():
                ability_values.setdefault(key, []).append(float(value))
        if training_session.task and training_session.evaluation:
            task = task_values.setdefault(
                training_session.task.code,
                {"task_code": training_session.task.code, "task_title": training_session.task.title, "scores": []},
            )
            task["scores"].append(float(training_session.evaluation.final_score))
        for answer in training_session.choice_answers or []:
            question = answer.question
            if not question:
                continue
            stat = question_values.setdefault(
                question.id,
                {
                    "question_code": question.code,
                    "stem": question.stem,
                    "knowledge_point": question.knowledge_point,
                    "ability_key": question.ability_key,
                    "attempts": 0,
                    "wrong_count": 0,
                },
            )
            stat["attempts"] += 1
            if not answer.option or not answer.option.is_correct:
                stat["wrong_count"] += 1

    ability_summary = sorted(
        [
            {
                "key": key,
                "name": _ability_label(key),
                "average_score": round(sum(values) / len(values), 1),
                "sample_count": len(values),
            }
            for key, values in ability_values.items()
        ],
        key=lambda item: item["average_score"],
    )
    task_summary = sorted(
        [
            {
                "task_code": value["task_code"],
                "task_title": value["task_title"],
                "average_score": round(sum(value["scores"]) / len(value["scores"]), 1),
                "completion_count": len(value["scores"]),
            }
            for value in task_values.values()
        ],
        key=lambda item: item["average_score"],
    )
    common_errors = sorted(
        [
            {
                **value,
                "wrong_rate": round(value["wrong_count"] * 100 / value["attempts"], 1),
            }
            for value in question_values.values()
            if value["wrong_count"] > 0
        ],
        key=lambda item: (item["wrong_rate"], item["wrong_count"]),
        reverse=True,
    )[:8]

    actions = []
    for index, ability in enumerate([item for item in ability_summary if item["average_score"] < 75][:3], 1):
        related_tasks = [
            item["task_code"]
            for item in task_summary
            if item["average_score"] < 75
        ][:3]
        actions.append(
            {
                "id": f"ability-{index}",
                "priority": "high" if ability["average_score"] < 60 else "medium",
                "target": ability["name"],
                "reason": f"该维度平均 {ability['average_score']} 分，低于 75 分教学关注线",
                "strategy": f"增加“{ability['name']}”情境辨析与错题讲评，并安排分层再训练。",
                "task_codes": related_tasks,
                "completed": False,
            }
        )
    for index, error in enumerate(common_errors[:3], 1):
        actions.append(
            {
                "id": f"error-{index}",
                "priority": "high" if error["wrong_rate"] >= 60 else "medium",
                "target": error["knowledge_point"] or error["question_code"],
                "reason": f"题目“{error['stem']}”错误率 {error['wrong_rate']}%",
                "strategy": "课前回顾对应权威知识，课堂进行选项辨析，课后用同能力变式题复测。",
                "task_codes": [],
                "completed": False,
            }
        )
    if not rows:
        actions.append(
            {
                "id": "baseline-1",
                "priority": "medium",
                "target": "建立实训基线",
                "reason": "当前筛选范围暂无已完成实训数据",
                "strategy": "先组织学生完成基础任务，再依据首轮结果制定分层课堂实施计划。",
                "task_codes": ["TT-01", "TT-02"],
                "completed": False,
            }
        )

    return {
        "class_name": class_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "student_count": len(students),
            "completed_count": len(rows),
            "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "pass_rate": round(sum(1 for score in scores if score >= 60) * 100 / len(scores), 1) if scores else 0,
        },
        "ability_summary": ability_summary,
        "task_summary": task_summary,
        "common_errors": common_errors,
        "recommended_actions": actions,
    }


@router.get("/training-results", summary="查看学生实训结果")
async def training_results(
    user: CurrentUser,
    session: DBSession,
    class_name: str = "",
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics")
    rows = await _load_training_result_rows(session, class_name)
    return ok([_training_result_out(training_session, student) for training_session, student in rows])


@router.get("/training-analysis", summary="按最新实训结果动态分析教学重点")
async def training_analysis(
    user: CurrentUser,
    session: DBSession,
    class_name: str = "",
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics")
    return ok(await _build_training_analysis(session, class_name))


class TeachingPlanGenerateBody(BaseModel):
    class_name: str = Field("", max_length=64)
    title: str = Field("", max_length=200)


class TeachingPlanUpdateBody(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    status: str | None = None
    actions: list[dict[str, Any]] | None = None
    notes: str | None = Field(None, max_length=8000)


def _plan_out(plan: TeachingPlan) -> dict:
    return {
        "id": plan.id,
        "title": plan.title,
        "class_name": plan.class_name,
        "status": plan.status,
        "analysis_snapshot": plan.analysis_snapshot or {},
        "actions": plan.actions or [],
        "notes": plan.notes,
        "generated_at": plan.generated_at.isoformat() if plan.generated_at else "",
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else "",
    }


@router.get("/teaching-plans", summary="班级教学实施改进计划列表")
async def list_teaching_plans(user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics")
    stmt = select(TeachingPlan).where(TeachingPlan.teacher_id == int(user["user_id"])).order_by(
        TeachingPlan.updated_at.desc()
    )
    plans = (await session.execute(stmt)).scalars().all()
    return ok([_plan_out(plan) for plan in plans])


@router.post("/teaching-plans/generate", summary="依据班级实训数据生成课堂实施改进计划")
async def generate_teaching_plan(
    body: TeachingPlanGenerateBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics", write=True)
    analysis = await _build_training_analysis(session, body.class_name.strip())
    scope = body.class_name.strip() or "全部班级"
    plan = TeachingPlan(
        teacher_id=int(user["user_id"]),
        title=body.title.strip() or f"{scope}课堂实施改进计划",
        class_name=body.class_name.strip(),
        status="draft",
        analysis_snapshot=analysis,
        actions=analysis["recommended_actions"],
        notes="本方案由当前已完成的选择题实训数据生成，教师确认后执行。",
        generated_at=datetime.now(UTC),
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return ok(_plan_out(plan))


@router.patch("/teaching-plans/{plan_id}", summary="教师调整并保存班级实施改进计划")
async def update_teaching_plan(
    plan_id: int,
    body: TeachingPlanUpdateBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "analytics", write=True)
    plan = (
        await session.execute(
            select(TeachingPlan).where(
                TeachingPlan.id == plan_id,
                TeachingPlan.teacher_id == int(user["user_id"]),
            )
        )
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="班级实施改进计划不存在")
    if body.title is not None:
        plan.title = body.title
    if body.status is not None:
        if body.status not in {"draft", "active", "completed"}:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="班级实施改进计划状态无效")
        plan.status = body.status
    if body.actions is not None:
        plan.actions = body.actions
    if body.notes is not None:
        plan.notes = body.notes
    await session.commit()
    await session.refresh(plan)
    return ok(_plan_out(plan))


__all__ = ["router"]
