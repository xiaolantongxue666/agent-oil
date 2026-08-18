"""教师端产业岗位分析与专业培养方案版本管理。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api import ok
from app.api.deps import DBSession, TeacherUser
from app.api.response import AppError
from app.models.curriculum import IndustryEvidence, ProgramAdjustmentProposal
from app.services.admin_governance import audit, enforce_feature
from app.services.program_analysis import ProgramAnalysisService, program_out

router = APIRouter(prefix="/teacher/programs", tags=["teacher-programs"])
service = ProgramAnalysisService()


class IndustryEvidenceBody(BaseModel):
    major: str = "油气储运工程"
    title: str = Field(min_length=2, max_length=255)
    source_name: str = ""
    source_type: str = "industry_report"
    source_no: str = ""
    source_url: str = ""
    published_at: datetime | None = None
    summary: str = ""
    themes: list[str] = []
    skills: list[str] = []
    confidence: str = "medium"
    enabled: bool = True


class IndustryEvidenceUpdateBody(BaseModel):
    title: str | None = None
    source_name: str | None = None
    source_type: str | None = None
    source_no: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    themes: list[str] | None = None
    skills: list[str] | None = None
    confidence: str | None = None
    enabled: bool | None = None


class ProposalCreateBody(BaseModel):
    months: int = Field(default=12, ge=3, le=36)


class ProposalUpdateBody(BaseModel):
    title: str | None = None
    actions: list[dict[str, Any]] | None = None
    review_note: str | None = None
    status: str | None = None


class ProposalPublishBody(BaseModel):
    confirm_reviewed: bool = False


def _evidence_out(item: IndustryEvidence) -> dict[str, Any]:
    return {
        "id": item.id,
        "major": item.major,
        "title": item.title,
        "source_name": item.source_name,
        "source_type": item.source_type,
        "source_no": item.source_no,
        "source_url": item.source_url,
        "published_at": item.published_at,
        "summary": item.summary,
        "themes": item.themes or [],
        "skills": item.skills or [],
        "confidence": item.confidence,
        "enabled": item.enabled,
        "created_at": item.created_at,
    }


def _proposal_out(item: ProgramAdjustmentProposal) -> dict[str, Any]:
    return {
        "id": item.id,
        "base_program_id": item.base_program_id,
        "target_version": item.target_version,
        "status": item.status,
        "title": item.title,
        "analysis_snapshot": item.analysis_snapshot or {},
        "actions": item.actions or [],
        "evidence_refs": item.evidence_refs or [],
        "generation_method": item.generation_method,
        "review_note": item.review_note,
        "created_by": item.created_by,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": item.reviewed_at,
        "published_program_id": item.published_program_id,
        "published_at": item.published_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("", summary="培养方案版本列表")
async def list_programs(user: TeacherUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "teacher_industry")
    return ok(await service.list_programs(session, int(user["user_id"])))


@router.get("/industry-evidence", summary="产业分析证据列表")
async def list_industry_evidence(
    user: TeacherUser,
    session: DBSession,
    major: str = Query(default="油气储运工程"),
) -> dict:
    await enforce_feature(session, user, "teacher_industry")
    stmt = (
        select(IndustryEvidence)
        .where(IndustryEvidence.major == major)
        .order_by(IndustryEvidence.published_at.desc(), IndustryEvidence.id.desc())
    )
    return ok([_evidence_out(item) for item in (await session.execute(stmt)).scalars().all()])


@router.post("/industry-evidence", summary="新增产业证据")
async def create_industry_evidence(
    body: IndustryEvidenceBody, user: TeacherUser, session: DBSession
) -> dict:
    await enforce_feature(session, user, "teacher_industry", write=True)
    if body.confidence not in {"low", "medium", "high"}:
        raise AppError("INVALID_CONFIDENCE", "证据置信度仅支持 low、medium、high")
    item = IndustryEvidence(**body.model_dump(), created_by=int(user["user_id"]))
    session.add(item)
    await audit(session, int(user["user_id"]), "industry_evidence.create", "industry_evidence", body.title)
    await session.commit()
    await session.refresh(item)
    return ok(_evidence_out(item))


@router.patch("/industry-evidence/{evidence_id}", summary="审核或更新产业证据")
async def update_industry_evidence(
    evidence_id: int,
    body: IndustryEvidenceUpdateBody,
    user: TeacherUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "teacher_industry", write=True)
    item = await session.get(IndustryEvidence, evidence_id)
    if not item:
        raise AppError("INDUSTRY_EVIDENCE_NOT_FOUND", "产业证据不存在", 404)
    payload = body.model_dump(exclude_unset=True)
    if payload.get("confidence") not in {None, "low", "medium", "high"}:
        raise AppError("INVALID_CONFIDENCE", "证据置信度仅支持 low、medium、high")
    for key, value in payload.items():
        setattr(item, key, value)
    await audit(session, int(user["user_id"]), "industry_evidence.update", "industry_evidence", item.id, payload)
    await session.commit()
    await session.refresh(item)
    return ok(_evidence_out(item))


@router.get("/proposals", summary="培养方案调整草案列表")
async def list_proposals(user: TeacherUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "teacher_industry")
    stmt = select(ProgramAdjustmentProposal).order_by(ProgramAdjustmentProposal.id.desc())
    return ok([_proposal_out(item) for item in (await session.execute(stmt)).scalars().all()])


@router.patch("/proposals/{proposal_id}", summary="编辑并审核培养方案调整草案")
async def update_proposal(
    proposal_id: int,
    body: ProposalUpdateBody,
    user: TeacherUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "teacher_industry", write=True)
    proposal = await session.get(ProgramAdjustmentProposal, proposal_id)
    if not proposal:
        raise AppError("PROGRAM_PROPOSAL_NOT_FOUND", "调整草案不存在", 404)
    if proposal.status == "published":
        raise AppError("PROGRAM_PROPOSAL_PUBLISHED", "已发布草案不可再次编辑", 409)
    payload = body.model_dump(exclude_unset=True)
    if payload.get("status") not in {None, "draft", "reviewed", "rejected"}:
        raise AppError("INVALID_PROPOSAL_STATUS", "草案状态仅支持 draft、reviewed、rejected")
    for key, value in payload.items():
        setattr(proposal, key, value)
    if payload.get("status") == "reviewed":
        proposal.reviewed_by = int(user["user_id"])
        proposal.reviewed_at = datetime.now().astimezone()
    await session.commit()
    await session.refresh(proposal)
    return ok(_proposal_out(proposal))


@router.post("/proposals/{proposal_id}/publish", summary="教师确认并发布培养方案新版本")
async def publish_proposal(
    proposal_id: int,
    body: ProposalPublishBody,
    user: TeacherUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "teacher_industry", write=True)
    if not body.confirm_reviewed:
        raise AppError("REVIEW_CONFIRMATION_REQUIRED", "发布前须确认已核验岗位和产业证据", 409)
    proposal = await session.get(ProgramAdjustmentProposal, proposal_id)
    if not proposal:
        raise AppError("PROGRAM_PROPOSAL_NOT_FOUND", "调整草案不存在", 404)
    if proposal.status == "published":
        raise AppError("PROGRAM_PROPOSAL_PUBLISHED", "该草案已经发布", 409)
    if not proposal.actions:
        raise AppError("PROGRAM_ACTIONS_REQUIRED", "草案至少需要一项调整行动", 409)
    program = await service.publish(session, proposal, int(user["user_id"]))
    await audit(session, int(user["user_id"]), "program.publish", "program_proposal", proposal.id, {"program_id": program.id})
    return ok(program_out(program))


@router.get("/{program_id}", summary="培养方案版本详情")
async def get_program(program_id: int, user: TeacherUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "teacher_industry")
    try:
        program = await service.get_program(session, program_id)
    except ValueError as exc:
        raise AppError("PROGRAM_NOT_FOUND", str(exc), 404) from exc
    return ok(program_out(program))


@router.get("/{program_id}/analysis", summary="查看产业岗位与课程能力差距")
async def get_program_analysis(
    program_id: int,
    user: TeacherUser,
    session: DBSession,
    months: int = Query(default=12, ge=3, le=36),
) -> dict:
    await enforce_feature(session, user, "analytics")
    try:
        program = await service.get_program(session, program_id)
    except ValueError as exc:
        raise AppError("PROGRAM_NOT_FOUND", str(exc), 404) from exc
    return ok(await service.analyze(session, program, months))


@router.post("/{program_id}/proposals", summary="依据产业岗位证据生成培养方案调整草案")
async def create_proposal(
    program_id: int,
    body: ProposalCreateBody,
    user: TeacherUser,
    session: DBSession,
) -> dict:
    await enforce_feature(session, user, "teacher_industry", write=True)
    try:
        program = await service.get_program(session, program_id)
    except ValueError as exc:
        raise AppError("PROGRAM_NOT_FOUND", str(exc), 404) from exc
    if program.status != "published":
        raise AppError("PROGRAM_NOT_CURRENT", "只能基于已发布的当前方案生成调整草案", 409)
    proposal = await service.create_proposal(session, program, body.months, int(user["user_id"]))
    return ok(_proposal_out(proposal))


__all__ = ["router"]
