"""教师岗位创建、公开数据发现、AI图谱分析与审核发布接口。"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api import ok
from app.api.deps import AdminUser, CurrentUser, DBSession
from app.db.session import AsyncSessionLocal
from app.models.position import JobTask, Position
from app.models.position_market import (
    JobPostingSnapshot,
    PositionAnalysisRun,
    PositionDiscoveryCandidate,
    PositionDiscoveryRun,
)
from app.services.admin_governance import audit, enforce_feature
from app.services.position_browser_agent import (
    BrowserAgentCancelled,
    PositionBrowserAgent,
    final_run_status,
    filter_duplicate_snapshots,
)
from app.services.position_discovery import (
    PositionDiscoveryService,
    PublicationDateEvidence,
    SearchHit,
    extract_publication_date,
)
from app.services.position_graph_analysis import (
    PositionGraphAnalysisService,
    normalize_graph_draft,
)

router = APIRouter(prefix="/teacher/positions", tags=["teacher-position-admin"])
_BROWSER_DISCOVERY_LOCK = asyncio.Lock()


def _require_teacher(user: CurrentUser) -> int:
    if user.get("role") not in {"teacher", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要教师权限")
    return int(user["user_id"])


def _analysis_out(analysis: PositionAnalysisRun | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "version": analysis.version,
        "status": analysis.status,
        "provider": analysis.provider,
        "evidence_count": analysis.evidence_count,
        "confidence": analysis.confidence,
        "result": analysis.result_json or {},
        "created_at": analysis.created_at.isoformat() if analysis.created_at else "",
        "reviewed_at": analysis.reviewed_at.isoformat() if analysis.reviewed_at else "",
        "published_at": analysis.published_at.isoformat() if analysis.published_at else "",
    }


class PositionCreateBody(BaseModel):
    code: str = Field(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(..., min_length=2, max_length=128)
    major: str = Field("油气储运工程", min_length=2, max_length=64)
    description: str = Field("", max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=10)


class PositionUpdateBody(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=128)
    major: str | None = Field(None, min_length=2, max_length=64)
    description: str | None = Field(None, max_length=1000)
    aliases: list[str] | None = Field(None, max_length=10)


class DiscoverBody(BaseModel):
    max_results: int = Field(20, ge=1, le=50)
    lookback_months: int = Field(0, ge=0, le=12)
    confirm_public_search: bool = False
    mode: Literal["fast", "browser"] = "fast"


class RefreshDatesBody(BaseModel):
    confirm_public_refresh: bool = False


class AnalysisUpdateBody(BaseModel):
    result: dict[str, Any]


class PublishBody(BaseModel):
    analysis_id: int | None = None
    confirm_reviewed: bool = False


def _discovery_run_out(run: PositionDiscoveryRun, *, lookback_months: int = 0) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "mode": run.mode,
        "stage": run.stage,
        "progress": run.progress,
        "cancel_requested": run.cancel_requested,
        "query_terms": run.query_terms or [],
        "source_domains": run.source_domains or [],
        "found_count": run.found_count,
        "saved_count": run.saved_count,
        "lookback_months": lookback_months,
        "stage_stats": run.stage_stats or {},
        "official_sources": run.official_sources or [],
        "diagnostic": run.diagnostic,
        "warnings": run.warnings or [],
        "error_summary": run.error_summary,
        "created_at": run.created_at.isoformat() if run.created_at else "",
        "completed_at": run.completed_at.isoformat() if run.completed_at else "",
    }


async def _existing_snapshot_hashes(session: DBSession, position_id: int) -> tuple[set[str], set[str]]:
    """查询该岗位已入库快照的 URL 与内容哈希，用于跨 run 去重。"""

    rows = (
        await session.execute(
            select(
                JobPostingSnapshot.source_url_hash,
                JobPostingSnapshot.content_hash,
            ).where(JobPostingSnapshot.position_id == position_id)
        )
    ).all()
    url_hashes = {str(row[0]) for row in rows if row[0]}
    content_hashes = {str(row[1]) for row in rows if row[1]}
    return url_hashes, content_hashes


def _candidate_out(candidate: PositionDiscoveryCandidate) -> dict[str, Any]:
    extracted = candidate.extracted_json or {}
    return {
        "id": candidate.id,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "title": str(extracted.get("title", "")),
        "validation_status": candidate.validation_status,
        "validation_errors": candidate.validation_errors or [],
        "confidence": candidate.confidence,
    }


async def fail_stale_discovery_runs() -> int:
    """服务启动时清理遗留采集任务：单进程部署下 queued/running 必然是中断残留。"""

    async with AsyncSessionLocal() as session:
        stale = (
            await session.scalars(
                select(PositionDiscoveryRun).where(
                    PositionDiscoveryRun.status.in_(["queued", "running"])
                )
            )
        ).all()
        if not stale:
            return 0
        now = datetime.now(UTC)
        for run in stale:
            run.status = "failed"
            run.stage = "failed"
            run.error_summary = "服务重启导致采集任务中断"
            run.diagnostic = "采集任务因服务重启中断，请重新发起采集"
            run.completed_at = now
        await session.commit()
        return len(stale)


async def _execute_browser_discovery(
    *,
    run_id: int,
    position_id: int,
    position_name: str,
    aliases: list[str],
    description: str,
    max_results: int,
    lookback_months: int,
) -> None:
    """在响应返回后运行浏览器任务；使用独立会话，避免请求会话已关闭。"""

    async with AsyncSessionLocal() as session:
        run = await session.get(PositionDiscoveryRun, run_id)
        if run is None:
            return
        run.status = "running"
        run.stage = "starting_browser"
        run.progress = 2
        await session.commit()

        async def update_progress(stage: str, progress: int, stats: dict[str, int]) -> None:
            await session.refresh(run, attribute_names=["cancel_requested"])
            if run.cancel_requested:
                raise BrowserAgentCancelled("教师已取消任务")
            run.stage = stage
            run.progress = max(0, min(progress, 100))
            run.stage_stats = stats
            await session.commit()

        async def should_cancel() -> bool:
            await session.refresh(run, attribute_names=["cancel_requested"])
            return bool(run.cancel_requested)

        try:
            run.stage = "waiting_browser"
            await session.commit()
            async with _BROWSER_DISCOVERY_LOCK:
                if await should_cancel():
                    raise BrowserAgentCancelled("教师已取消任务")
                result = await PositionBrowserAgent().discover(
                    position_name=position_name,
                    aliases=aliases,
                    description=description,
                    max_results=max_results,
                    lookback_months=lookback_months,
                    progress=update_progress,
                    should_cancel=should_cancel,
                )
            existing_url_hashes, existing_content_hashes = await _existing_snapshot_hashes(
                session, position_id
            )
            fresh_hits, duplicate_count = filter_duplicate_snapshots(
                result.hits, existing_url_hashes, existing_content_hashes
            )
            for candidate in result.candidates:
                session.add(
                    PositionDiscoveryCandidate(
                        run_id=run_id,
                        position_id=position_id,
                        source_name=candidate.source_name,
                        source_url=candidate.source_url,
                        source_url_hash=hashlib.sha256(candidate.source_url.encode()).hexdigest(),
                        extracted_json=candidate.extracted,
                        raw_content=candidate.raw_content,
                        validation_status=candidate.status,
                        validation_errors=candidate.errors,
                        confidence=candidate.confidence,
                    )
                )
            for item in fresh_hits:
                session.add(
                    JobPostingSnapshot(
                        position_id=position_id,
                        discovery_run_id=run_id,
                        **item,
                    )
                )
            run.query_terms = [position_name, *aliases]
            run.source_domains = sorted(
                {
                    str(urlparse(item["source_url"]).hostname or "")
                    for item in fresh_hits
                }
            )
            run.found_count = len(result.candidates)
            run.saved_count = len(fresh_hits)
            run.stage_stats = {**result.stage_stats, "duplicate_skipped": duplicate_count}
            run.official_sources = result.source_reports
            run.warnings = result.warnings
            run.diagnostic = (
                result.diagnostic
                if duplicate_count == 0
                else f"{result.diagnostic} 跨任务去重跳过 {duplicate_count} 条已入库岗位。"
            )
            run.error_summary = "\n".join(result.warnings[:10])
            run.status = final_run_status(len(fresh_hits), result.source_reports)
            run.stage = "completed"
            run.progress = 100
            run.completed_at = datetime.now(UTC)
            await session.commit()
        except BrowserAgentCancelled:
            await session.rollback()
            run = await session.get(PositionDiscoveryRun, run_id)
            if run is not None:
                run.status = "cancelled"
                run.stage = "cancelled"
                run.diagnostic = "教师已取消 AI 浏览器深度采集"
                run.completed_at = datetime.now(UTC)
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            run = await session.get(PositionDiscoveryRun, run_id)
            if run is not None:
                run.status = "failed"
                run.stage = "failed"
                run.error_summary = f"{type(exc).__name__}: {str(exc)[:500]}"
                run.diagnostic = "AI 浏览器深度采集失败，请检查 LLM、Chromium 和目标站点状态"
                run.completed_at = datetime.now(UTC)
                await session.commit()


@router.get("", summary="教师岗位配置列表")
async def list_positions(user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry")
    positions = (await session.scalars(select(Position).order_by(Position.id.desc()))).all()
    task_counts = dict(
        (
            await session.execute(
                select(JobTask.position_id, func.count(JobTask.id)).group_by(JobTask.position_id)
            )
        ).all()
    )
    snapshot_counts = dict(
        (
            await session.execute(
                select(JobPostingSnapshot.position_id, func.count(JobPostingSnapshot.id)).group_by(
                    JobPostingSnapshot.position_id
                )
            )
        ).all()
    )
    analyses = (
        await session.scalars(
            select(PositionAnalysisRun).order_by(
                PositionAnalysisRun.position_id,
                PositionAnalysisRun.version.desc(),
            )
        )
    ).all()
    latest_analysis: dict[int, PositionAnalysisRun] = {}
    for analysis in analyses:
        latest_analysis.setdefault(analysis.position_id, analysis)
    return ok(
        [
            {
                "id": position.id,
                "code": position.code,
                "name": position.name,
                "major": position.major,
                "description": position.description,
                "aliases": position.aliases or [],
                "status": position.status,
                "graph_version": position.graph_version,
                "source_summary": position.source_summary,
                "task_count": task_counts.get(position.id, 0),
                "snapshot_count": snapshot_counts.get(position.id, 0),
                "latest_analysis": _analysis_out(latest_analysis.get(position.id)),
                "published_at": position.published_at.isoformat() if position.published_at else "",
            }
            for position in positions
        ]
    )


@router.post("", summary="创建岗位草稿")
async def create_position(body: PositionCreateBody, user: CurrentUser, session: DBSession) -> dict:
    teacher_id = _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    code = body.code.strip().upper()
    duplicate = (
        await session.scalars(
            select(Position).where((Position.code == code) | (Position.name == body.name.strip()))
        )
    ).first()
    if duplicate:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="岗位编号或名称已存在")
    position = Position(
        code=code,
        name=body.name.strip(),
        major=body.major.strip(),
        description=body.description.strip(),
        aliases=list(dict.fromkeys(item.strip() for item in body.aliases if item.strip())),
        status="draft",
        source_summary="",
        graph_version=0,
        created_by=teacher_id,
    )
    session.add(position)
    await session.commit()
    await session.refresh(position)
    return ok({"id": position.id, "status": position.status})


@router.put("/{position_id}", summary="更新岗位草稿信息")
async def update_position(
    position_id: int,
    body: PositionUpdateBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    if body.name is not None:
        position.name = body.name.strip()
    if body.major is not None:
        position.major = body.major.strip()
    if body.description is not None:
        position.description = body.description.strip()
    if body.aliases is not None:
        position.aliases = list(
            dict.fromkeys(item.strip() for item in body.aliases if item.strip())
        )
    await session.commit()
    return ok({"id": position.id, "status": position.status})


@router.get("/{position_id}", summary="岗位配置详情")
async def position_detail(position_id: int, user: CurrentUser, session: DBSession) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry")
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    snapshots = (
        await session.scalars(
            select(JobPostingSnapshot)
            .where(JobPostingSnapshot.position_id == position_id)
            .order_by(JobPostingSnapshot.created_at.desc())
            .limit(50)
        )
    ).all()
    analyses = (
        await session.scalars(
            select(PositionAnalysisRun)
            .where(PositionAnalysisRun.position_id == position_id)
            .order_by(PositionAnalysisRun.version.desc())
        )
    ).all()
    discovery_runs = (
        await session.scalars(
            select(PositionDiscoveryRun)
            .where(PositionDiscoveryRun.position_id == position_id)
            .order_by(PositionDiscoveryRun.created_at.desc())
            .limit(10)
        )
    ).all()
    return ok(
        {
            "position": {
                "id": position.id,
                "code": position.code,
                "name": position.name,
                "major": position.major,
                "description": position.description,
                "aliases": position.aliases or [],
                "status": position.status,
                "graph_version": position.graph_version,
                "source_summary": position.source_summary,
            },
            "snapshots": [
                {
                    "id": item.id,
                    "title": item.title,
                    "company": item.company,
                    "region": item.region,
                    "source_name": item.source_name,
                    "source_url": item.source_url,
                    "published_at": item.published_at.isoformat() if item.published_at else "",
                    "published_at_raw": item.published_at_raw,
                    "published_at_source": item.published_at_source,
                    "date_confidence": item.date_confidence,
                    "date_parse_reason": item.date_parse_reason,
                    "observed_at": item.observed_at.isoformat() if item.observed_at else "",
                    "skills": item.skills or [],
                    "match_score": item.match_score,
                    "snippet": item.snippet,
                }
                for item in snapshots
            ],
            "discovery_runs": [_discovery_run_out(item) for item in discovery_runs],
            "analyses": [_analysis_out(item) for item in analyses],
        }
    )


@router.post("/{position_id}/refresh-dates", summary="重新核验岗位发布日期")
async def refresh_position_dates(
    position_id: int,
    body: RefreshDatesBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    if not body.confirm_public_refresh:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请确认重新访问公开招聘详情页以核验发布日期",
        )
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    snapshots = (
        await session.scalars(
            select(JobPostingSnapshot)
            .where(JobPostingSnapshot.position_id == position_id)
            .order_by(JobPostingSnapshot.created_at.desc())
        )
    ).all()
    groups: dict[str, list[JobPostingSnapshot]] = {}
    for snapshot in snapshots:
        groups.setdefault(snapshot.source_url_hash, []).append(snapshot)

    evidence_by_hash = {}
    hits_to_refresh: list[SearchHit] = []
    hash_by_url: dict[str, str] = {}
    for url_hash, items in groups.items():
        representative = items[0]
        if (
            representative.published_at is not None
            and representative.date_confidence == "high"
            and representative.published_at_source.startswith("official_api_")
        ):
            evidence_by_hash[url_hash] = PublicationDateEvidence(
                representative.published_at,
                representative.published_at_raw or representative.published_at.isoformat(),
                representative.published_at_source,
                "high",
                representative.date_parse_reason or "官方公开接口招聘开始时间",
            )
            continue
        stored = extract_publication_date(visible_text=representative.content or "")
        if stored.value is not None:
            evidence_by_hash[url_hash] = stored
            continue
        hits_to_refresh.append(
            SearchHit(
                title=representative.title,
                url=representative.source_url,
                snippet=representative.snippet,
                source_name=representative.source_name,
            )
        )
        hash_by_url[representative.source_url] = url_hash

    refreshed = await PositionDiscoveryService().inspect_publication_dates(hits_to_refresh)
    for url, evidence in refreshed.items():
        evidence_by_hash[hash_by_url[url]] = evidence

    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    dated_urls = 0
    for url_hash, items in groups.items():
        evidence = evidence_by_hash.get(url_hash) or extract_publication_date()
        confidence_counts[evidence.confidence] += 1
        if evidence.value is not None and evidence.confidence in {"high", "medium"}:
            dated_urls += 1
        for snapshot in items:
            snapshot.published_at = evidence.value
            snapshot.published_at_raw = evidence.raw
            snapshot.published_at_source = evidence.source
            snapshot.date_confidence = evidence.confidence
            snapshot.date_parse_reason = evidence.reason
            metadata = dict(snapshot.metadata_json or {})
            metadata["published_at_source"] = evidence.source
            metadata["date_confidence"] = evidence.confidence
            metadata["date_rechecked_at"] = datetime.now(UTC).isoformat()
            snapshot.metadata_json = metadata
    await session.commit()
    return ok(
        {
            "total_urls": len(groups),
            "dated_urls": dated_urls,
            "undated_urls": len(groups) - dated_urls,
            "refetched_urls": len(hits_to_refresh),
            "date_confidence": confidence_counts,
            "semantics": "仅核验岗位发布日期；采集日期不作为发布日期",
        }
    )


@router.post("/{position_id}/discover", summary="AI寻找公开岗位数据")
async def discover_position_data(
    position_id: int,
    body: DiscoverBody,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    if not body.confirm_public_search:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请确认仅检索公开招聘页面并由教师审核后使用",
        )
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    aliases = [str(item) for item in (position.aliases or [])]
    run = PositionDiscoveryRun(
        position_id=position.id,
        status="queued" if body.mode == "browser" else "running",
        mode=body.mode,
        stage="queued" if body.mode == "browser" else "searching",
        progress=0 if body.mode == "browser" else 5,
        query_terms=[position.name, *aliases],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    if body.mode == "browser":
        background_tasks.add_task(
            _execute_browser_discovery,
            run_id=run.id,
            position_id=position.id,
            position_name=position.name,
            aliases=aliases,
            description=position.description,
            max_results=body.max_results,
            lookback_months=body.lookback_months,
        )
        return ok(_discovery_run_out(run, lookback_months=body.lookback_months))
    try:
        result = await PositionDiscoveryService().discover(
            position_name=position.name,
            aliases=aliases,
            description=position.description,
            max_results=body.max_results,
            lookback_months=body.lookback_months,
        )
        run.query_terms = result.query_terms
        run.source_domains = result.source_domains
        run.found_count = len(result.hits)
        run.saved_count = len(result.hits)
        run.error_summary = "\n".join(
            [*result.errors[:10], *([result.diagnostic] if not result.hits else [])]
        )
        run.stage_stats = result.stage_stats
        run.official_sources = result.official_sources
        run.warnings = result.errors
        run.diagnostic = result.diagnostic
        run.status = final_run_status(len(result.hits), result.official_sources)
        run.stage = "completed"
        run.progress = 100
        run.completed_at = datetime.now(UTC)
        existing_url_hashes, existing_content_hashes = await _existing_snapshot_hashes(
            session, position.id
        )
        fresh_hits, duplicate_count = filter_duplicate_snapshots(
            result.hits, existing_url_hashes, existing_content_hashes
        )
        run.saved_count = len(fresh_hits)
        run.stage_stats = {**result.stage_stats, "duplicate_skipped": duplicate_count}
        for item in fresh_hits:
            session.add(
                JobPostingSnapshot(
                    position_id=position.id,
                    discovery_run_id=run.id,
                    **item,
                )
            )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.stage = "failed"
        run.error_summary = f"{type(exc).__name__}: {str(exc)[:500]}"
        run.completed_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"公开岗位数据检索失败：{type(exc).__name__}",
        ) from exc
    return ok(_discovery_run_out(run, lookback_months=body.lookback_months))


@router.get("/{position_id}/discovery-runs/{run_id}", summary="查询岗位采集任务状态")
async def discovery_run_status(
    position_id: int,
    run_id: int,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry")
    run = await session.get(PositionDiscoveryRun, run_id)
    if run is None or run.position_id != position_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="采集任务不存在")
    candidates = (
        await session.scalars(
            select(PositionDiscoveryCandidate)
            .where(PositionDiscoveryCandidate.run_id == run_id)
            .order_by(PositionDiscoveryCandidate.id)
            .limit(100)
        )
    ).all()
    payload = _discovery_run_out(run)
    payload["candidates"] = [_candidate_out(item) for item in candidates]
    return ok(payload)


@router.post("/{position_id}/discovery-runs/{run_id}/cancel", summary="取消岗位采集任务")
async def cancel_discovery_run(
    position_id: int,
    run_id: int,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    run = await session.get(PositionDiscoveryRun, run_id)
    if run is None or run.position_id != position_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="采集任务不存在")
    if run.status not in {"queued", "running"}:
        return ok(_discovery_run_out(run))
    run.cancel_requested = True
    run.stage = "cancelling"
    await session.commit()
    return ok(_discovery_run_out(run))


@router.post("/{position_id}/analyze", summary="依据招聘证据生成能力图谱草稿")
async def analyze_position(
    position_id: int,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    teacher_id = _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    await enforce_feature(session, user, "analytics", write=True)
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    raw_snapshots = (
        await session.scalars(
            select(JobPostingSnapshot)
            .where(JobPostingSnapshot.position_id == position.id)
            .order_by(JobPostingSnapshot.match_score.desc(), JobPostingSnapshot.created_at.desc())
            .limit(60)
        )
    ).all()
    snapshots: list[JobPostingSnapshot] = []
    seen_urls: set[str] = set()
    for snapshot in raw_snapshots:
        if snapshot.source_url_hash in seen_urls:
            continue
        seen_urls.add(snapshot.source_url_hash)
        snapshots.append(snapshot)
        if len(snapshots) >= 20:
            break
    try:
        draft, provider, confidence = await PositionGraphAnalysisService().generate(
            position=position,
            snapshots=snapshots,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    latest_version = (
        await session.scalar(
            select(func.max(PositionAnalysisRun.version)).where(
                PositionAnalysisRun.position_id == position.id
            )
        )
        or 0
    )
    analysis = PositionAnalysisRun(
        position_id=position.id,
        version=int(latest_version) + 1,
        status="draft",
        provider=provider,
        input_snapshot={
            "snapshot_ids": [item.id for item in snapshots],
            "source_urls": [item.source_url for item in snapshots],
        },
        result_json=draft,
        evidence_count=len(snapshots),
        confidence=confidence,
        created_by=teacher_id,
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    return ok(_analysis_out(analysis))


@router.put("/{position_id}/analyses/{analysis_id}", summary="教师修订图谱草稿")
async def update_analysis(
    position_id: int,
    analysis_id: int,
    body: AnalysisUpdateBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    position = await session.get(Position, position_id)
    analysis = await session.get(PositionAnalysisRun, analysis_id)
    if position is None or analysis is None or analysis.position_id != position.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图谱草稿不存在")
    if analysis.status == "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已发布版本不可直接修改")
    analysis.result_json = normalize_graph_draft(
        body.result,
        position_code=position.code,
        position_name=position.name,
    )
    analysis.status = "draft"
    await session.commit()
    return ok(_analysis_out(analysis))


@router.post("/{position_id}/publish", summary="教师审核并发布岗位图谱")
async def publish_position(
    position_id: int,
    body: PublishBody,
    user: CurrentUser,
    session: DBSession,
) -> dict:
    teacher_id = _require_teacher(user)
    await enforce_feature(session, user, "teacher_industry", write=True)
    if not body.confirm_reviewed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请确认已审核图谱草稿")
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    stmt = select(PositionAnalysisRun).where(PositionAnalysisRun.position_id == position.id)
    if body.analysis_id is not None:
        stmt = stmt.where(PositionAnalysisRun.id == body.analysis_id)
    analysis = (
        await session.scalars(stmt.order_by(PositionAnalysisRun.version.desc()).limit(1))
    ).one_or_none()
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="尚无可发布图谱草稿")
    try:
        counts = await PositionGraphAnalysisService().publish(
            session=session,
            position=position,
            analysis=analysis,
            reviewer_id=teacher_id,
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    await audit(session, teacher_id, "position.publish", "position", position.id, {"analysis_id": analysis.id})
    return ok(
        {
            "position_id": position.id,
            "analysis_id": analysis.id,
            "version": analysis.version,
            "status": "published",
            **counts,
            "training_tasks": counts["tasks"],
        }
    )


@router.post("/{position_id}/archive", summary="管理员归档岗位")
async def archive_position(position_id: int, user: AdminUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "teacher_industry", write=True)
    position = await session.get(Position, position_id)
    if position is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在")
    position.status = "archived"
    await audit(session, int(user["user_id"]), "position.archive", "position", position.id)
    await session.commit()
    return ok({"id": position.id, "status": position.status})


__all__ = ["router"]
