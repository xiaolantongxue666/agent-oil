"""专业群/专业级产业-课程能力聚合分析（P0-3 Phase 5，§26~§28）。

在既有 ProgramAnalysisService（program 级，按字符串 major 匹配岗位）之上做群级上卷：

- 产业需求 industry_demand：群内全部已发布岗位的招聘样本数 × 岗位-能力关系权重
  （与 program 级同口径：缺招聘样本的岗位至少记 1 个证据单位，保证结构分析可运行）；
- 课程供给 curriculum_supply：群内各专业每个培养方案 code 的最新已发布版本课程
  （学时 × 课程能力权重），历史版本不计入，避免重复放大供给；
- gap = industry_demand − curriculum_supply（百分点）；
- 共享/特色能力：由 Major.ability_weights 的跨专业分布规则判定（确定性规则，非模型判断）；
- 课程能力矩阵：CurriculumCourse.ability_weights 按相对最强课程归一为 5 分制。

数据边界与 program 级 analyze() 一致：只读岗位图谱、招聘快照、产业证据与课程，
刻意不查询任何学生或实训结果表。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.response import AppError
from app.models.curriculum import CurriculumProgram, IndustryEvidence
from app.models.knowledge import KnowledgeItem
from app.models.position import Ability, Position, PositionAbilityRelation
from app.models.position_market import JobPostingSnapshot
from app.models.professional_group import Major, ProfessionalGroup
from app.services.program_analysis import ProgramAnalysisService

# 共享/特色能力判定阈值（百分比权重，§25；确定性规则，教师可解释）
SHARED_ABILITY_MAX_SPREAD = 10.0  # 全部专业权重极差 ≤ 10 → 群共享能力
SPECIFIC_ABILITY_MARGIN = 5.0  # 群内最大权重领先第二名 ≥ 5 → 领先专业特色能力
# 课程能力矩阵：相对最强课程归一满分
MATRIX_MAX_SCORE = 5.0

AUTHORITATIVE_SOURCE_TYPES = (
    "standard",
    "policy",
    "regulation",
    "industry_report",
    "national_occupational_standard",
    "national_standard",
    "law",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _classify_abilities(
    majors: list[Major], ability_names: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按 Major.ability_weights 跨专业分布判定共享/特色能力（§25）。

    - 共享：六维键在群内每个专业的权重极差 ≤ SHARED_ABILITY_MAX_SPREAD；
    - 特色：某专业权重为群内最大且领先第二名 ≥ SPECIFIC_ABILITY_MARGIN。
    权重缺失的专业按 0 计（未配置视为不侧重）。
    """
    keys: set[str] = set()
    for major in majors:
        keys.update((major.ability_weights or {}).keys())
    shared: list[dict[str, Any]] = []
    specific: list[dict[str, Any]] = []
    for key in sorted(keys):
        values = [float((m.ability_weights or {}).get(key, 0)) for m in majors]
        if not values:
            continue
        spread = max(values) - min(values)
        if spread <= SHARED_ABILITY_MAX_SPREAD:
            shared.append({
                "ability_key": key,
                "ability_name": ability_names.get(key, key),
                "weight_range": [min(values), max(values)],
                "rule": f"全部专业权重极差 {round(spread, 1)} ≤ {SHARED_ABILITY_MAX_SPREAD}",
            })
        top = max(values)
        second = sorted(values, reverse=True)[1] if len(values) > 1 else 0.0
        if top - second >= SPECIFIC_ABILITY_MARGIN and top > 0:
            leaders = [
                {"major_id": m.id, "major_name": m.name, "weight": float((m.ability_weights or {}).get(key, 0))}
                for m in majors
                if abs(float((m.ability_weights or {}).get(key, 0)) - top) < 1e-9
            ]
            # 并列最大不构成"特色"（无唯一领先者）
            if len(leaders) == 1:
                specific.append({
                    "ability_key": key,
                    "ability_name": ability_names.get(key, key),
                    "rule": f"领先第二名 {round(top - second, 1)} ≥ {SPECIFIC_ABILITY_MARGIN}",
                    **leaders[0],
                })
    return shared, specific


def _latest_published_programs(programs: list[CurriculumProgram]) -> list[CurriculumProgram]:
    """每个 program_code 只保留版本最高的已发布方案，历史版本不重复计入供给。"""
    latest: dict[str, CurriculumProgram] = {}
    for program in programs:
        previous = latest.get(program.program_code)
        if previous is None or program.version > previous.version:
            latest[program.program_code] = program
    return list(latest.values())


class ProfessionalGroupAnalysisService:
    """专业群/专业层聚合分析；与 program 级服务共用同一数据边界。"""

    async def get_group(self, db: AsyncSession, group_id: int) -> ProfessionalGroup:
        group = await db.get(ProfessionalGroup, group_id)
        if not group:
            raise AppError("PROFESSIONAL_GROUP_NOT_FOUND", "专业群不存在", 404)
        return group

    async def get_major(self, db: AsyncSession, major_id: int) -> Major:
        major = await db.get(Major, major_id)
        if not major:
            raise AppError("MAJOR_NOT_FOUND", "专业不存在", 404)
        return major

    async def load_group_majors(self, db: AsyncSession, group: ProfessionalGroup) -> list[Major]:
        stmt = (
            select(Major)
            .where(Major.professional_group_id == group.id, Major.status == "published")
            .order_by(Major.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def _load_abilities(self, db: AsyncSession) -> dict[str, str]:
        rows = (await db.execute(select(Ability).order_by(Ability.id))).scalars().all()
        return {item.key: item.name for item in rows}

    async def _load_positions(self, db: AsyncSession, majors: list[Major]) -> list[Position]:
        """兼容双轨：major_id 精确匹配或旧字符串 major 名称匹配（Phase 4 兼容约定）。"""
        if not majors:
            return []
        major_ids = [m.id for m in majors]
        major_names = [m.name for m in majors]
        stmt = (
            select(Position)
            .where(
                or_(Position.major_id.in_(major_ids), Position.major.in_(major_names)),
                Position.status == "published",
            )
            .order_by(Position.id)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def _load_supply_programs(self, db: AsyncSession, majors: list[Major]) -> list[CurriculumProgram]:
        if not majors:
            return []
        major_ids = [m.id for m in majors]
        major_names = [m.name for m in majors]
        stmt = (
            select(CurriculumProgram)
            .where(
                or_(
                    CurriculumProgram.major_id.in_(major_ids),
                    CurriculumProgram.major.in_(major_names),
                ),
                CurriculumProgram.status == "published",
            )
            .options(selectinload(CurriculumProgram.courses))
            .order_by(CurriculumProgram.version.desc())
        )
        programs = list((await db.execute(stmt)).scalars().all())
        return _latest_published_programs(programs)

    async def analyze_scope(
        self,
        db: AsyncSession,
        *,
        majors: list[Major],
        months: int,
        group: ProfessionalGroup | None = None,
    ) -> dict[str, Any]:
        """群级/专业级统一聚合：group 传 None 时为单专业视图。"""
        months = max(3, min(months, 36))
        cutoff = _now() - timedelta(days=months * 31)
        ability_names = await self._load_abilities(db)
        positions = await self._load_positions(db, majors)
        position_ids = [p.id for p in positions]
        position_names = {p.id: p.name for p in positions}
        major_by_name = {m.name: m for m in majors}
        major_name_by_id = {m.id: m.name for m in majors}

        # ---- 产业需求侧：招聘快照（date_confidence 过滤 + 跨批次按 (网页,岗位) 去重，同 program 级口径） ----
        snapshots: list[JobPostingSnapshot] = []
        if position_ids:
            snapshots = list(
                (
                    await db.execute(
                        select(JobPostingSnapshot).where(
                            JobPostingSnapshot.position_id.in_(position_ids),
                            JobPostingSnapshot.published_at.is_not(None),
                            JobPostingSnapshot.published_at >= cutoff,
                            JobPostingSnapshot.date_confidence.in_(["high", "medium"]),
                        )
                    )
                ).scalars().all()
            )
        # 需求样本业务身份 = (网页, 岗位)：同 URL 同岗位计一次；同 URL 不同岗位各计一条独立证据。
        unique_snapshots: dict[tuple[str, int], JobPostingSnapshot] = {}
        for item in snapshots:
            key = (item.source_url_hash, item.position_id)
            previous = unique_snapshots.get(key)
            if previous is None or item.observed_at > previous.observed_at:
                unique_snapshots[key] = item
        snapshots = list(unique_snapshots.values())
        snapshot_counts = Counter(item.position_id for item in snapshots)
        skills = Counter(
            str(skill).strip()
            for item in snapshots
            for skill in (item.skills or [])
            if str(skill).strip()
        )

        relations: list[tuple[PositionAbilityRelation, Ability]] = []
        if position_ids:
            relations = list(
                (
                    await db.execute(
                        select(PositionAbilityRelation, Ability)
                        .join(Ability, Ability.id == PositionAbilityRelation.ability_id)
                        .where(PositionAbilityRelation.position_id.in_(position_ids))
                    )
                ).all()
            )

        demand_raw: defaultdict[str, float] = defaultdict(float)
        major_demand_raw: defaultdict[int, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
        position_major_id: dict[int, int | None] = {}
        for position in positions:
            # 岗位归属专业：优先 major_id，回退字符串名称
            position_major_id[position.id] = position.major_id or (
                major_by_name[position.major].id if position.major in major_by_name else None
            )
        for relation, ability in relations:
            # 产业需求只由真实有效招聘样本驱动：0 样本岗位贡献 0；无样本岗位仍出现在 position_rows[].sample_count。
            weight_unit = snapshot_counts.get(relation.position_id, 0) * relation.weight
            demand_raw[ability.key] += weight_unit
            owner_major = position_major_id.get(relation.position_id)
            if owner_major is not None:
                major_demand_raw[owner_major][ability.key] += weight_unit
        if not relations:
            # 完全没有岗位-能力关系时的兜底：保持结构可分析（与 program 级一致）；
            # 注意“有关系但样本全为 0”不走此兜底——那正是证据缺失的诚实呈现。
            for key in ability_names:
                demand_raw[key] = 1.0
        demand_total = sum(demand_raw.values()) or 1.0
        industry_demand = {key: value / demand_total * 100 for key, value in demand_raw.items()}

        # ---- 课程供给侧：各专业最新已发布方案课程 ----
        programs = await self._load_supply_programs(db, majors)
        supply_raw: defaultdict[str, float] = defaultdict(float)
        total_hours = 0
        practice_hours = 0
        course_count = 0
        covered_terms: set[str] = set()
        course_contribution: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for program in programs:
            for course in program.courses:
                if not course.enabled:
                    continue
                total_hours += course.total_hours
                practice_hours += course.practice_hours
                course_count += 1
                covered_terms.update(
                    str(term).strip() for term in (course.knowledge_points or []) if str(term).strip()
                )
                for key, weight in (course.ability_weights or {}).items():
                    key = str(key)
                    contribution = course.total_hours * float(weight or 0)
                    supply_raw[key] += contribution
                    if contribution > 0:
                        course_contribution[key].append({
                            "course_id": course.id,
                            "course_name": course.name,
                            "program_name": program.name,
                            "major_name": major_name_by_id.get(program.major_id, program.major),
                            "total_hours": course.total_hours,
                            "weight": float(weight or 0),
                            "hours_weighted": round(contribution, 1),
                        })
        supply_total = sum(supply_raw.values()) or 1.0
        curriculum_supply = {key: value / supply_total * 100 for key, value in supply_raw.items()}
        for rows in course_contribution.values():
            rows.sort(key=lambda item: item["hours_weighted"], reverse=True)

        # ---- 能力 Gap（§27：gap = industry_demand − curriculum_supply） ----
        all_keys = sorted(set(industry_demand) | set(curriculum_supply))
        ability_gaps = [
            {
                "ability_key": key,
                "ability_name": ability_names.get(key, key),
                "demand_share": round(industry_demand.get(key, 0), 1),
                "curriculum_share": round(curriculum_supply.get(key, 0), 1),
                "gap": round(industry_demand.get(key, 0) - curriculum_supply.get(key, 0), 1),
                "covered_by": course_contribution.get(key, []),
            }
            for key in all_keys
        ]
        ability_gaps.sort(key=lambda item: item["gap"], reverse=True)
        course_gaps = [
            {
                "ability_key": item["ability_key"],
                "ability_name": item["ability_name"],
                "gap": item["gap"],
                "demand_share": item["demand_share"],
                "curriculum_share": item["curriculum_share"],
                "has_coverage": bool(item["covered_by"]),
                "covered_by": item["covered_by"][:4],
            }
            for item in ability_gaps
            if item["gap"] > 0
        ]

        # ---- 产业证据与权威知识（按专业名称并集） ----
        major_names = [m.name for m in majors]
        evidence: list[IndustryEvidence] = []
        authoritative: list[KnowledgeItem] = []
        if major_names:
            evidence = list(
                (
                    await db.execute(
                        select(IndustryEvidence)
                        .where(
                            IndustryEvidence.major.in_(major_names),
                            IndustryEvidence.enabled == True,  # noqa: E712
                            IndustryEvidence.published_at.is_not(None),
                            IndustryEvidence.published_at >= cutoff,
                        )
                        .order_by(IndustryEvidence.published_at.desc(), IndustryEvidence.id.desc())
                    )
                ).scalars().all()
            )
            authoritative = list(
                (
                    await db.execute(
                        select(KnowledgeItem)
                        .where(
                            KnowledgeItem.major.in_(major_names),
                            KnowledgeItem.source_no != "",
                            KnowledgeItem.source_type.in_(AUTHORITATIVE_SOURCE_TYPES),
                        )
                        .order_by(KnowledgeItem.id)
                        .limit(100)
                    )
                ).scalars().all()
            )
        industry_terms = Counter(
            str(term).strip()
            for item in evidence
            for term in [*(item.themes or []), *(item.skills or [])]
            if str(term).strip()
        )
        uncovered_skills = [
            {"name": name, "count": count}
            for name, count in skills.most_common(12)
            if not any(name in term or term in name for term in covered_terms)
        ][:6]

        position_rows = [
            {
                "id": item.id,
                "name": item.name,
                "major_name": major_name_by_id.get(position_major_id.get(item.id), item.major),
                "sample_count": snapshot_counts.get(item.id, 0),
                "graph_version": item.graph_version,
            }
            for item in positions
        ]
        position_rows.sort(key=lambda item: item["sample_count"], reverse=True)

        # ---- 各专业视图：需求画像 + 链接计数 + 定位权重 ----
        major_rows: list[dict[str, Any]] = []
        for major in majors:
            major_raw = major_demand_raw.get(major.id, {})
            major_total = sum(major_raw.values())
            major_rows.append({
                "id": major.id,
                "code": major.code,
                "name": major.name,
                "is_core_major": major.is_core_major,
                "ability_weights": major.ability_weights or {},
                "description": major.description,
                "position_count": sum(
                    1 for pid, mid in position_major_id.items() if mid == major.id
                ),
                "program_count": sum(1 for p in programs if p.major_id == major.id),
                "demand_share": {
                    key: round(value / major_total * 100, 1) for key, value in major_raw.items()
                }
                if major_total
                else {},
            })

        shared_abilities, major_specific_abilities = _classify_abilities(majors, ability_names)

        evidence_refs: list[dict[str, Any]] = []
        for item in snapshots[:60]:
            evidence_refs.append({
                "type": "job_posting",
                "id": item.id,
                "title": item.title,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "published_at": item.published_at,
                "position_name": position_names.get(item.position_id, ""),
            })
        for item in evidence[:20]:
            evidence_refs.append({
                "type": "industry_evidence",
                "id": item.id,
                "title": item.title,
                "source_name": item.source_name,
                "source_no": item.source_no,
                "source_url": item.source_url,
                "published_at": item.published_at,
            })
        for item in authoritative[:40]:
            evidence_refs.append({
                "type": "authoritative_knowledge",
                "id": item.id,
                "title": item.title,
                "source_name": item.source_name,
                "source_no": item.source_no,
                "page": item.page,
                "knowledge_id": item.knowledge_id,
            })

        dated_month_count = len({item.published_at.strftime("%Y-%m") for item in snapshots})
        if len(snapshots) >= 20 and dated_month_count >= 3 and len(evidence) >= 5:
            data_confidence = "high"
        elif len(snapshots) >= 3 and dated_month_count >= 2 and len(evidence) >= 3:
            data_confidence = "medium"
        else:
            data_confidence = "low"

        scope_target = (
            {"type": "group", "id": group.id, "code": group.code, "name": group.name}
            if group
            else {"type": "major", "id": majors[0].id, "code": majors[0].code, "name": majors[0].name}
        )
        analysis: dict[str, Any] = {
            "scope": {
                "target": scope_target,
                "major_count": len(majors),
                "months": months,
                "cutoff": cutoff,
                "data_boundary": "仅使用岗位招聘、岗位能力图谱、产业证据和权威知识；不读取学生实训成绩。",
            },
            "summary": {
                "major_count": len(majors),
                "position_count": len(positions),
                "job_sample_count": len(snapshots),
                "job_sample_month_count": dated_month_count,
                "industry_evidence_count": len(evidence),
                "authoritative_evidence_count": len(authoritative),
                "course_count": course_count,
                "total_course_hours": total_hours,
                "practice_hours": practice_hours,
                "practice_ratio": round(practice_hours / total_hours * 100, 1) if total_hours else 0,
                "confidence": data_confidence,
                "confidence_basis": (
                    "高：至少20条有效岗位样本、覆盖3个月且至少5条产业证据；"
                    "中：至少3条有效岗位样本、覆盖2个月且至少3条产业证据；否则为低。"
                ),
            },
            "majors": major_rows,
            "positions": position_rows,
            "shared_abilities": shared_abilities,
            "major_specific_abilities": major_specific_abilities,
            "industry_demand": {key: round(value, 1) for key, value in industry_demand.items()},
            "curriculum_supply": {key: round(value, 1) for key, value in curriculum_supply.items()},
            "ability_gaps": ability_gaps,
            "top_skills": [{"name": name, "count": count} for name, count in skills.most_common(12)],
            "uncovered_skills": uncovered_skills,
            "industry_themes": [
                {"name": name, "count": count} for name, count in industry_terms.most_common(12)
            ],
            "course_gaps": course_gaps,
            "evidence_refs": evidence_refs,
            "generated_at": _now(),
        }
        # §34 培养建议：复用 program 级规则化 build_actions（结构化草案，仍走教师审核）
        analysis["recommendations"] = ProgramAnalysisService().build_actions(analysis)
        return analysis

    async def analyze_group(self, db: AsyncSession, group_id: int, months: int) -> dict[str, Any]:
        group = await self.get_group(db, group_id)
        majors = await self.load_group_majors(db, group)
        if not majors:
            raise AppError("GROUP_MAJORS_EMPTY", "该专业群尚未配置专业", 409)
        return await self.analyze_scope(db, majors=majors, months=months, group=group)

    async def analyze_major(self, db: AsyncSession, major_id: int, months: int) -> dict[str, Any]:
        major = await self.get_major(db, major_id)
        return await self.analyze_scope(db, majors=[major], months=months)

    async def course_matrix(self, db: AsyncSession, group_id: int) -> dict[str, Any]:
        """课程 × 六维能力矩阵（§32）：值来自 CurriculumCourse.ability_weights，
        按群内相对最强课程归一为 0~5 分（MATRIX_MAX_SCORE），前端不写死任何分值。"""
        group = await self.get_group(db, group_id)
        majors = await self.load_group_majors(db, group)
        major_name_by_id = {m.id: m.name for m in majors}
        ability_names = await self._load_abilities(db)
        programs = await self._load_supply_programs(db, majors)

        rows: list[dict[str, Any]] = []
        max_weight = 0.0
        for program in programs:
            for course in program.courses:
                if not course.enabled:
                    continue
                weights = {str(k): float(v or 0) for k, v in (course.ability_weights or {}).items()}
                max_weight = max(max_weight, *weights.values()) if weights else max_weight
                rows.append({
                    "course_id": course.id,
                    "course_code": course.course_code,
                    "name": course.name,
                    "category": course.category,
                    "total_hours": course.total_hours,
                    "practice_hours": course.practice_hours,
                    "program_id": program.id,
                    "program_name": program.name,
                    "major_id": program.major_id,
                    "major_name": major_name_by_id.get(program.major_id, program.major),
                    "weights": weights,
                    "knowledge_points": course.knowledge_points or [],
                })
        for row in rows:
            row["cells"] = {
                key: round(MATRIX_MAX_SCORE * weight / max_weight, 1) if max_weight else 0.0
                for key, weight in row.pop("weights").items()
            }
        return {
            "group": {"id": group.id, "code": group.code, "name": group.name},
            "abilities": [{"key": key, "name": name} for key, name in ability_names.items()],
            "max_score": MATRIX_MAX_SCORE,
            "basis": "分值 = 5 × 课程能力权重 / 群内最大课程能力权重，来源 CurriculumCourse.ability_weights，非前端写死。",
            "courses": rows,
            "generated_at": _now(),
        }


__all__ = [
    "MATRIX_MAX_SCORE",
    "ProfessionalGroupAnalysisService",
    "SPECIFIC_ABILITY_MARGIN",
    "SHARED_ABILITY_MAX_SPREAD",
]
