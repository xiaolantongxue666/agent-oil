"""岗位能力图谱接口：全部节点和关系均从数据库读取。"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.models.knowledge import KnowledgeChunk, KnowledgeEvidenceRelation, KnowledgeItem
from app.models.position import (
    Ability,
    JobTask,
    KnowledgePoint,
    Position,
    PositionAbilityRelation,
    SkillPoint,
    TaskAbilityRelation,
)
from app.models.position_market import JobPostingSnapshot

router = APIRouter(prefix="/positions", tags=["positions"])


_TITLE_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("安全与HSE", ("安全", "hse", "应急", "环保")),
    ("检验检测", ("检测", "检验", "无损", "ndt", "测井", "试验")),
    ("油气集输与管道", ("集输", "管道", "输油", "输气", "储运")),
    ("站场运行操作", ("站场", "运行", "操作", "值班", "巡检", "operator")),
    ("设备与仪表", ("设备", "维修", "机泵", "仪表", "计量", "储罐")),
    ("工程建设与监理", ("监理", "监督", "项目经理", "工程管理", "工程师", "施工", "地质")),
)


def _title_category(item: JobPostingSnapshot) -> str:
    # 高频通用技能（例如HSE）不能覆盖岗位本身的专业类别，因此仅按招聘标题归类。
    text = item.title.lower()
    for label, keywords in _TITLE_CATEGORY_RULES:
        if any(keyword in text for keyword in keywords):
            return label
    return "综合技术岗位"


def _date_confidence(item: JobPostingSnapshot) -> str:
    """返回趋势归月依据的可信度，不把采集时间伪装成发布日期。"""
    confidence = str(item.date_confidence or "").lower()
    return confidence if confidence in {"high", "medium", "low"} else "low"


@router.get("/graph", summary="数据库驱动的岗位能力图谱")
async def position_graph(user: CurrentUser, session: DBSession) -> dict:
    """返回岗位→任务→能力→知识点→技能点的完整关系图。"""
    del user  # CurrentUser 依赖用于鉴权
    positions = (
        await session.scalars(
            select(Position).where(Position.status == "published").order_by(Position.id)
        )
    ).all()
    position_ids = [position.id for position in positions]
    tasks = (
        await session.scalars(
            select(JobTask)
            .where(JobTask.position_id.in_(position_ids))
            .order_by(JobTask.position_id, JobTask.sort_order, JobTask.id)
        )
    ).all() if position_ids else []
    abilities = (await session.scalars(select(Ability).order_by(Ability.id))).all()
    knowledge_points = (await session.scalars(select(KnowledgePoint).order_by(KnowledgePoint.id))).all()
    skill_points = (await session.scalars(select(SkillPoint).order_by(SkillPoint.id))).all()
    position_relations = (await session.scalars(select(PositionAbilityRelation))).all()
    task_relations = (await session.scalars(select(TaskAbilityRelation))).all()
    evidence_relations = (await session.scalars(select(KnowledgeEvidenceRelation))).all()
    evidence_items = {
        item.id: item for item in (await session.scalars(select(KnowledgeItem))).all()
    }
    enabled_chunks = (
        await session.scalars(
            select(KnowledgeChunk).where(
                KnowledgeChunk.enabled.is_(True),
                KnowledgeChunk.knowledge_point_id.is_not(None),
            )
        )
    ).all()

    position_weights = {
        (relation.position_id, relation.ability_id): relation.weight
        for relation in position_relations
    }
    position_by_task = {task.id: task.position_id for task in tasks}
    evidence_by_point: dict[int, list[dict]] = {}
    linked_item_ids: set[int] = set()
    for relation in evidence_relations:
        item = evidence_items.get(relation.knowledge_item_id)
        if item is None or item.safety_level != "权威来源教学摘要":
            continue
        linked_item_ids.add(item.id)
        evidence_by_point.setdefault(relation.knowledge_point_id, []).append({
            "knowledge_id": item.knowledge_id,
            "title": item.title,
            "source_name": item.source_name,
            "source_no": item.source_no,
            "chapter": item.chapter,
            "page": item.page,
        })
    reviewed_chunks_by_point: dict[int, list[dict]] = {}
    for chunk in enabled_chunks:
        if chunk.knowledge_point_id is None:
            continue
        item = evidence_items.get(chunk.knowledge_item_id)
        if item is None:
            continue
        reviewed_chunks_by_point.setdefault(chunk.knowledge_point_id, []).append({
            "chunk_id": chunk.id,
            "heading": chunk.heading,
            "source_name": item.source_name,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
        })
    nodes: list[dict] = []
    links: list[dict] = []

    for position in positions:
        nodes.append({
            "id": f"position:{position.id}", "name": position.name, "category": 0,
            "code": position.code, "description": position.description, "symbol_size": 58,
        })
    for task in tasks:
        nodes.append({
            "id": f"task:{task.id}", "name": task.name, "category": 1,
            "code": task.code, "description": task.description, "symbol_size": 38,
        })
        links.append({
            "source": f"position:{task.position_id}", "target": f"task:{task.id}",
            "relation": "包含任务",
        })
    for ability in abilities:
        weights = [
            value for (position_id, ability_id), value in position_weights.items()
            if ability_id == ability.id and position_id in {p.id for p in positions}
        ]
        nodes.append({
            "id": f"ability:{ability.id}", "name": ability.name, "category": 2,
            "code": ability.key, "description": ability.description,
            "weight": weights[0] if weights else ability.weight, "symbol_size": 34,
        })
    for relation in task_relations:
        if relation.job_task_id in position_by_task:
            links.append({
                "source": f"task:{relation.job_task_id}",
                "target": f"ability:{relation.ability_id}",
                "relation": "需要能力", "weight": relation.weight,
            })
    for point in knowledge_points:
        authority_sources = evidence_by_point.get(point.id, [])
        reviewed_chunks = reviewed_chunks_by_point.get(point.id, [])
        nodes.append({
            "id": f"knowledge:{point.id}", "name": point.name, "category": 3,
            "code": point.code, "description": point.description, "symbol_size": 25,
            "authority_count": len(authority_sources), "authority_sources": authority_sources,
            "reviewed_chunk_count": len(reviewed_chunks), "reviewed_chunks": reviewed_chunks,
        })
        links.append({
            "source": f"ability:{point.ability_id}", "target": f"knowledge:{point.id}",
            "relation": "支撑知识",
        })
    for skill in skill_points:
        nodes.append({
            "id": f"skill:{skill.id}", "name": skill.name, "category": 4,
            "code": skill.code, "description": skill.description, "symbol_size": 20,
        })
        links.append({
            "source": f"knowledge:{skill.knowledge_point_id}", "target": f"skill:{skill.id}",
            "relation": "形成技能",
        })

    heatmap = {
        "positions": [
            {
                "id": position.id,
                "code": position.code,
                "name": position.name,
                "description": position.description,
            }
            for position in positions
        ],
        "abilities": [
            {"id": ability.id, "key": ability.key, "name": ability.name}
            for ability in abilities
        ],
        "tasks": [
            {
                "id": task.id,
                "position_id": task.position_id,
                "code": task.code,
                "name": task.name,
            }
            for task in tasks
        ],
        "position_cells": [
            {
                "position_id": relation.position_id,
                "ability_id": relation.ability_id,
                "weight": relation.weight,
            }
            for relation in position_relations
        ],
        "task_cells": [
            {
                "task_id": relation.job_task_id,
                "ability_id": relation.ability_id,
                "weight": relation.weight,
            }
            for relation in task_relations
            if relation.job_task_id in position_by_task
        ],
        "value_semantics": "ability_weight",
    }

    return ok({
        "categories": ["岗位", "典型任务", "能力维度", "知识点", "技能点"],
        "nodes": nodes,
        "links": links,
        "heatmap": heatmap,
        "stats": {
            "positions": len(positions), "tasks": len(tasks), "abilities": len(abilities),
            "knowledge_points": len(knowledge_points), "skill_points": len(skill_points),
            "authority_items": len(linked_item_ids),
            "enabled_file_chunks": len(enabled_chunks),
        },
        "data_source": "database",
        "evidence_relation_source": "knowledge_evidence_relations",
    })


@router.get("/{position_id}/demand-trend", summary="岗位近期招聘需求趋势")
async def position_demand_trend(
    position_id: int,
    user: CurrentUser,
    session: DBSession,
    months: int = Query(6, ge=3, le=24),
) -> dict:
    del user
    position = await session.get(Position, position_id)
    if position is None or position.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="岗位不存在或尚未发布")
    snapshots = (
        await session.scalars(
            select(JobPostingSnapshot)
            .where(JobPostingSnapshot.position_id == position_id)
            .order_by(JobPostingSnapshot.observed_at)
        )
    ).all()
    now = datetime.now(UTC)
    month_keys: list[str] = []
    year, month = now.year, now.month
    for offset in range(months - 1, -1, -1):
        absolute = year * 12 + month - 1 - offset
        month_keys.append(f"{absolute // 12:04d}-{absolute % 12 + 1:02d}")

    # 同一URL可被多次采集；优先采用已核验发布日期置信度最高的一条。
    unique_by_url: dict[str, JobPostingSnapshot] = {}
    for item in snapshots:
        existing = unique_by_url.get(item.source_url_hash)
        item_rank = ({"high": 3, "medium": 2, "low": 1}[_date_confidence(item)], bool(item.published_at))
        existing_rank = (
            ({"high": 3, "medium": 2, "low": 1}[_date_confidence(existing)], bool(existing.published_at))
            if existing else (0, False)
        )
        if existing is None or item_rank > existing_rank:
            unique_by_url[item.source_url_hash] = item

    urls_by_month: dict[str, set[str]] = {key: set() for key in month_keys}
    companies_by_month: dict[str, set[str]] = {key: set() for key in month_keys}
    skills_by_month: dict[str, Counter[str]] = {key: Counter() for key in month_keys}
    sources: Counter[str] = Counter(
        item.source_name for item in unique_by_url.values() if item.source_name
    )
    date_confidence: Counter[str] = Counter()
    title_categories: Counter[str] = Counter()
    dated_snapshots: list[JobPostingSnapshot] = []
    outside_range_count = 0
    all_skills: Counter[str] = Counter()
    for item in unique_by_url.values():
        confidence = _date_confidence(item)
        date_confidence[confidence] += 1
        title_categories[_title_category(item)] += 1
        all_skills.update(str(skill) for skill in (item.skills or []) if skill)
        # 严格口径：只有高/中置信度的岗位发布日期可进入需求趋势。
        if item.published_at is None or confidence not in {"high", "medium"}:
            continue
        key = item.published_at.strftime("%Y-%m")
        if key not in urls_by_month:
            outside_range_count += 1
            continue
        dated_snapshots.append(item)
        urls_by_month[key].add(item.source_url_hash)
        if item.company:
            companies_by_month[key].add(item.company)
        skills_by_month[key].update(str(skill) for skill in (item.skills or []) if skill)

    series: list[dict] = []
    counts: list[int | None] = []
    for key in month_keys:
        count = len(urls_by_month[key])
        covered = count > 0
        value = count if covered else None
        counts.append(value)
        previous = counts[-2] if len(counts) > 1 else None
        growth = (
            round((count - previous) / previous * 100, 1)
            if covered and previous is not None and previous > 0
            else None
        )
        window = counts[max(0, len(counts) - 3):]
        moving_average = (
            round(sum(item for item in window if item is not None) / 3, 1)
            if len(window) == 3 and all(item is not None for item in window)
            else None
        )
        series.append(
            {
                "period": key,
                "posting_count": value,
                "employer_count": len(companies_by_month[key]) if covered else None,
                "growth_rate": growth,
                "moving_average": moving_average,
                "covered": covered,
                "date_basis": "published_at" if covered else "uncovered",
            }
        )
    total_evidence_count = len(unique_by_url)
    dated_sample_count = len(dated_snapshots)
    undated_sample_count = sum(
        1 for item in unique_by_url.values() if item.published_at is None
    )
    excluded_low_confidence_count = date_confidence["low"]
    source_count = len(sources)
    covered_months = sum(1 for count in counts if count is not None)
    confidence = (
        "high" if dated_sample_count >= 30 and source_count >= 3 and covered_months >= 3
        else "medium" if dated_sample_count >= 10 and covered_months >= 2
        else "low"
    )
    latest_index = next(
        (index for index in range(len(series) - 1, -1, -1) if series[index]["covered"]),
        None,
    )
    latest_series = series[latest_index] if latest_index is not None else None
    employers = {item.company for item in unique_by_url.values() if item.company}
    last_observed_at = max(
        (item.observed_at for item in snapshots if item.observed_at),
        default=None,
    )
    latest_published_at = max(
        (
            item.published_at for item in unique_by_url.values()
            if item.published_at and _date_confidence(item) in {"high", "medium"}
        ),
        default=None,
    )

    # 采集活动只使用 observed_at，独立展示且绝不进入需求趋势。
    batches: dict[int, dict] = {}
    for item in snapshots:
        if item.observed_at.strftime("%Y-%m") not in urls_by_month:
            continue
        batch = batches.setdefault(
            item.discovery_run_id,
            {"run_id": item.discovery_run_id, "observed_at": item.observed_at, "urls": set()},
        )
        batch["urls"].add(item.source_url_hash)
        if item.observed_at and item.observed_at < batch["observed_at"]:
            batch["observed_at"] = item.observed_at
    seen_urls: set[str] = set()
    batch_activity: list[dict] = []
    for batch in sorted(batches.values(), key=lambda item: item["observed_at"]):
        new_urls = batch["urls"] - seen_urls
        seen_urls.update(batch["urls"])
        batch_activity.append(
            {
                "run_id": batch["run_id"],
                "observed_at": batch["observed_at"].isoformat(),
                "sample_count": len(batch["urls"]),
                "new_count": len(new_urls),
            }
        )
    return ok(
        {
            "position_id": position.id,
            "position_name": position.name,
            "range_months": months,
            "series": series,
            "summary": {
                "sample_count": dated_sample_count,
                "total_evidence_count": total_evidence_count,
                "dated_sample_count": dated_sample_count,
                "undated_sample_count": undated_sample_count,
                "excluded_low_confidence_count": excluded_low_confidence_count,
                "outside_range_count": outside_range_count,
                "source_count": source_count,
                "employer_count": len(employers),
                "batch_count": len(batch_activity),
                "covered_months": covered_months,
                "coverage_ratio": round(covered_months / months * 100, 1),
                "display_mode": "trend" if covered_months >= 3 else "snapshot",
                "latest_period": latest_series["period"] if latest_series else None,
                "latest_posting_count": latest_series["posting_count"] if latest_series else 0,
                "latest_growth_rate": latest_series["growth_rate"] if latest_series else None,
                "last_observed_at": last_observed_at.isoformat() if last_observed_at else None,
                "latest_published_at": (
                    latest_published_at.isoformat() if latest_published_at else None
                ),
                "confidence": confidence,
                "date_confidence": {
                    "high": date_confidence["high"],
                    "medium": date_confidence["medium"],
                    "low": date_confidence["low"],
                },
                "data_semantics": (
                    "趋势仅按可核验的岗位发布日期统计；采集日期只展示采集活动，"
                    "不进入需求趋势。样本量不代表全市场岗位总量"
                ),
            },
            "top_skills": [
                {"name": name, "count": count}
                for name, count in all_skills.most_common(10)
            ],
            "sources": [
                {"name": name, "count": count}
                for name, count in sources.most_common()
            ],
            "title_categories": [
                {"name": name, "count": count}
                for name, count in title_categories.most_common(8)
            ],
            "batch_activity": batch_activity[-8:],
        }
    )


__all__ = ["router"]
