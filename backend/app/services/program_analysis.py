"""产业岗位证据驱动的培养方案分析与版本发布服务。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.curriculum import (
    CurriculumCourse,
    CurriculumProgram,
    IndustryEvidence,
    ProgramAdjustmentProposal,
)
from app.models.knowledge import KnowledgeItem
from app.models.position import Ability, Position, PositionAbilityRelation
from app.models.position_market import JobPostingSnapshot
from app.models.professional_group import Major


DEFAULT_MAJOR = "油气储运工程"
DEFAULT_PROGRAM_CODE = "OGTE-2026"

DEFAULT_COURSES: list[dict[str, Any]] = [
    {
        "course_code": "OG-101",
        "name": "油气储运工程基础",
        "category": "专业基础课",
        "total_hours": 64,
        "practice_hours": 16,
        "ability_weights": {"process_understanding": 0.55, "standard_recording": 0.25, "safety_awareness": 0.20},
        "knowledge_points": ["油气性质", "储运流程", "工程识图"],
    },
    {
        "course_code": "OG-202",
        "name": "油气管道输送工艺",
        "category": "专业核心课",
        "total_hours": 64,
        "practice_hours": 24,
        "ability_weights": {"process_understanding": 0.45, "instrument_parameter": 0.30, "abnormal_detection": 0.25},
        "knowledge_points": ["管输工艺", "输送参数", "运行调节"],
    },
    {
        "course_code": "OG-203",
        "name": "储运设备运行与维护",
        "category": "专业核心课",
        "total_hours": 56,
        "practice_hours": 28,
        "ability_weights": {"equipment_recognition": 0.55, "abnormal_detection": 0.30, "safety_awareness": 0.15},
        "knowledge_points": ["泵与压缩机", "阀门", "设备巡检"],
    },
    {
        "course_code": "OG-204",
        "name": "储运仪表与自动化",
        "category": "专业核心课",
        "total_hours": 48,
        "practice_hours": 24,
        "ability_weights": {"instrument_parameter": 0.55, "abnormal_detection": 0.25, "standard_recording": 0.20},
        "knowledge_points": ["检测仪表", "自动控制", "参数分析"],
    },
    {
        "course_code": "OG-205",
        "name": "油气储运安全与 HSE",
        "category": "专业核心课",
        "total_hours": 48,
        "practice_hours": 24,
        "ability_weights": {"safety_awareness": 0.60, "abnormal_detection": 0.25, "standard_recording": 0.15},
        "knowledge_points": ["风险辨识", "作业许可", "应急处置"],
    },
    {
        "course_code": "OG-301",
        "name": "站场运行综合实训",
        "category": "集中实践课",
        "total_hours": 80,
        "practice_hours": 80,
        "ability_weights": {
            "process_understanding": 0.15,
            "equipment_recognition": 0.15,
            "instrument_parameter": 0.15,
            "abnormal_detection": 0.20,
            "safety_awareness": 0.20,
            "standard_recording": 0.15,
        },
        "knowledge_points": ["站场运行", "巡检操作", "异常工况", "规范记录"],
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _course_out(course: CurriculumCourse) -> dict[str, Any]:
    return {
        "id": course.id,
        "course_code": course.course_code,
        "name": course.name,
        "category": course.category,
        "total_hours": course.total_hours,
        "practice_hours": course.practice_hours,
        "practice_ratio": round(course.practice_hours / course.total_hours * 100, 1) if course.total_hours else 0,
        "ability_weights": course.ability_weights or {},
        "knowledge_points": course.knowledge_points or [],
        "position_ids": course.position_ids or [],
        "assessment_method": course.assessment_method,
        "enabled": course.enabled,
        "sort_order": course.sort_order,
    }


def program_out(program: CurriculumProgram) -> dict[str, Any]:
    courses = sorted(program.courses or [], key=lambda item: (item.sort_order, item.id))
    return {
        "id": program.id,
        "program_code": program.program_code,
        "major": program.major,
        "major_id": program.major_id,
        "name": program.name,
        "version": program.version,
        "status": program.status,
        "objectives": program.objectives,
        "graduation_requirements": program.graduation_requirements or [],
        "source_period_months": program.source_period_months,
        "change_summary": program.change_summary,
        "parent_program_id": program.parent_program_id,
        "published_at": program.published_at,
        "courses": [_course_out(course) for course in courses],
    }


class ProgramAnalysisService:
    """专业层闭环；此服务刻意不查询任何学生或实训结果表。"""

    async def ensure_baseline(self, db: AsyncSession, teacher_id: int) -> CurriculumProgram:
        stmt = (
            select(CurriculumProgram)
            .where(CurriculumProgram.program_code == DEFAULT_PROGRAM_CODE)
            .order_by(CurriculumProgram.version.desc())
            .options(selectinload(CurriculumProgram.courses))
        )
        current = (await db.execute(stmt)).scalars().first()
        if current:
            return current

        current = CurriculumProgram(
            program_code=DEFAULT_PROGRAM_CODE,
            major=DEFAULT_MAJOR,
            name="油气储运工程专业人才培养方案",
            version=1,
            status="published",
            objectives="面向油气储运生产、管输与站场运行岗位群，培养具备安全意识、规范操作和数字化分析能力的高素质技术技能人才。",
            graduation_requirements=[
                "掌握油气储运工艺、设备与仪表基础知识",
                "能够完成站场巡检、参数监控和异常识别",
                "遵守 HSE、作业许可和标准化记录要求",
            ],
            created_by=teacher_id,
            reviewed_by=teacher_id,
            published_at=_now(),
            change_summary="系统初始化的培养方案基线，后续版本必须由产业岗位证据草案经教师审核后发布。",
            # P0-3 兼容：专业已建库时挂接 major_id（旧库无 majors 则保持空，字符串 major 仍是权威）
            major_id=(
                await db.execute(select(Major.id).where(Major.name == DEFAULT_MAJOR))
            ).scalars().first(),
        )
        db.add(current)
        await db.flush()
        for index, payload in enumerate(DEFAULT_COURSES, start=1):
            db.add(CurriculumCourse(program_id=current.id, sort_order=index, **payload))
        await db.commit()
        return await self.get_program(db, current.id)

    async def get_program(self, db: AsyncSession, program_id: int) -> CurriculumProgram:
        stmt = (
            select(CurriculumProgram)
            .where(CurriculumProgram.id == program_id)
            .options(selectinload(CurriculumProgram.courses))
        )
        program = (await db.execute(stmt)).scalars().first()
        if not program:
            raise ValueError("培养方案不存在")
        return program

    async def list_programs(self, db: AsyncSession, teacher_id: int) -> list[dict[str, Any]]:
        await self.ensure_baseline(db, teacher_id)
        stmt = (
            select(CurriculumProgram)
            .order_by(CurriculumProgram.version.desc())
            .options(selectinload(CurriculumProgram.courses))
        )
        return [program_out(item) for item in (await db.execute(stmt)).scalars().all()]

    async def analyze(self, db: AsyncSession, program: CurriculumProgram, months: int) -> dict[str, Any]:
        months = max(3, min(months, 36))
        cutoff = _now() - timedelta(days=months * 31)
        positions = (
            await db.execute(
                select(Position).where(Position.major == program.major, Position.status == "published")
            )
        ).scalars().all()
        position_ids = [item.id for item in positions]

        snapshots: list[JobPostingSnapshot] = []
        if position_ids:
            snapshots = (
                await db.execute(
                    select(JobPostingSnapshot).where(
                        JobPostingSnapshot.position_id.in_(position_ids),
                        JobPostingSnapshot.published_at.is_not(None),
                        JobPostingSnapshot.published_at >= cutoff,
                        JobPostingSnapshot.date_confidence.in_(["high", "medium"]),
                    )
                )
            ).scalars().all()
        # 跨采集批次按原始网页去重，避免重复抓取放大岗位需求。
        unique_snapshots: dict[str, JobPostingSnapshot] = {}
        for item in snapshots:
            previous = unique_snapshots.get(item.source_url_hash)
            if previous is None or item.observed_at > previous.observed_at:
                unique_snapshots[item.source_url_hash] = item
        snapshots = list(unique_snapshots.values())

        snapshot_counts = Counter(item.position_id for item in snapshots)
        position_names = {item.id: item.name for item in positions}
        skills = Counter(str(skill).strip() for item in snapshots for skill in (item.skills or []) if str(skill).strip())

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
        abilities = (await db.execute(select(Ability).order_by(Ability.id))).scalars().all()
        ability_names = {item.key: item.name for item in abilities}

        demand_raw: defaultdict[str, float] = defaultdict(float)
        for relation, ability in relations:
            # 至少赋 1 个证据单位，使已发布但暂缺招聘样本的岗位图谱仍进入结构分析。
            demand_raw[ability.key] += max(1, snapshot_counts.get(relation.position_id, 0)) * relation.weight
        if not demand_raw:
            for ability in abilities:
                demand_raw[ability.key] = ability.weight or 1.0
        demand_total = sum(demand_raw.values()) or 1.0
        demand_share = {key: value / demand_total * 100 for key, value in demand_raw.items()}

        coverage_raw: defaultdict[str, float] = defaultdict(float)
        total_hours = 0
        practice_hours = 0
        covered_terms: set[str] = set()
        for course in program.courses:
            if not course.enabled:
                continue
            total_hours += course.total_hours
            practice_hours += course.practice_hours
            covered_terms.update(str(term).strip() for term in (course.knowledge_points or []) if str(term).strip())
            for key, weight in (course.ability_weights or {}).items():
                coverage_raw[str(key)] += course.total_hours * float(weight or 0)
        coverage_total = sum(coverage_raw.values()) or 1.0
        coverage_share = {key: value / coverage_total * 100 for key, value in coverage_raw.items()}

        all_keys = sorted(set(demand_share) | set(coverage_share))
        ability_gaps = [
            {
                "ability_key": key,
                "ability_name": ability_names.get(key, key),
                "demand_share": round(demand_share.get(key, 0), 1),
                "curriculum_share": round(coverage_share.get(key, 0), 1),
                "gap": round(demand_share.get(key, 0) - coverage_share.get(key, 0), 1),
            }
            for key in all_keys
        ]
        ability_gaps.sort(key=lambda item: item["gap"], reverse=True)

        evidence = (
            await db.execute(
                select(IndustryEvidence)
                .where(
                    IndustryEvidence.major == program.major,
                    IndustryEvidence.enabled == True,  # noqa: E712
                    IndustryEvidence.published_at.is_not(None),
                    IndustryEvidence.published_at >= cutoff,
                )
                .order_by(IndustryEvidence.published_at.desc(), IndustryEvidence.id.desc())
            )
        ).scalars().all()
        authoritative = (
            await db.execute(
                select(KnowledgeItem)
                .where(
                    KnowledgeItem.major == program.major,
                    KnowledgeItem.source_no != "",
                    KnowledgeItem.source_type.in_([
                        "standard",
                        "policy",
                        "regulation",
                        "industry_report",
                        "national_occupational_standard",
                        "national_standard",
                        "law",
                    ]),
                )
                .order_by(KnowledgeItem.id)
                .limit(100)
            )
        ).scalars().all()

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
                "sample_count": snapshot_counts.get(item.id, 0),
                "graph_version": item.graph_version,
            }
            for item in positions
        ]
        position_rows.sort(key=lambda item: item["sample_count"], reverse=True)

        evidence_refs: list[dict[str, Any]] = []
        for item in snapshots[:80]:
            evidence_refs.append({
                "type": "job_posting",
                "id": item.id,
                "title": item.title,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "published_at": item.published_at,
                "position_name": position_names.get(item.position_id, ""),
            })
        for item in evidence:
            evidence_refs.append({
                "type": "industry_evidence",
                "id": item.id,
                "title": item.title,
                "source_name": item.source_name,
                "source_no": item.source_no,
                "source_url": item.source_url,
                "published_at": item.published_at,
            })
        for item in authoritative:
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
        return {
            "scope": {
                "major": program.major,
                "months": months,
                "cutoff": cutoff,
                "data_boundary": "仅使用岗位招聘、岗位能力图谱、产业证据和权威知识；不读取学生实训成绩。",
            },
            "summary": {
                "position_count": len(positions),
                "job_sample_count": len(snapshots),
                "job_sample_month_count": dated_month_count,
                "industry_evidence_count": len(evidence),
                "authoritative_evidence_count": len(authoritative),
                "total_course_hours": total_hours,
                "practice_hours": practice_hours,
                "practice_ratio": round(practice_hours / total_hours * 100, 1) if total_hours else 0,
                "confidence": data_confidence,
                "confidence_basis": (
                    "高：至少20条有效岗位样本、覆盖3个月且至少5条产业证据；"
                    "中：至少3条有效岗位样本、覆盖2个月且至少3条产业证据；否则为低。"
                ),
            },
            "positions": position_rows,
            "ability_gaps": ability_gaps,
            "top_skills": [{"name": name, "count": count} for name, count in skills.most_common(12)],
            "uncovered_skills": uncovered_skills,
            "industry_themes": [{"name": name, "count": count} for name, count in industry_terms.most_common(12)],
            "evidence_refs": evidence_refs,
            "generated_at": _now(),
        }

    def build_actions(self, analysis: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for index, gap in enumerate(analysis.get("ability_gaps", [])):
            if gap["gap"] <= 1.5 or len(actions) >= 3:
                continue
            actions.append({
                "id": f"ability-{gap['ability_key']}",
                "type": "strengthen_ability",
                "priority": "high" if gap["gap"] >= 5 else "medium",
                "target": gap["ability_name"],
                "target_ability": gap["ability_key"],
                "reason": f"岗位需求占比 {gap['demand_share']}%，课程覆盖占比 {gap['curriculum_share']}%，存在 {gap['gap']} 个百分点差距。",
                "suggestion": f"在专业核心课或综合实训中强化「{gap['ability_name']}」任务、学时与考核权重。",
                "hours_delta": 4 if index else 8,
                "completed": False,
            })
        for item in analysis.get("uncovered_skills", [])[:3]:
            actions.append({
                "id": f"skill-{len(actions) + 1}",
                "type": "add_skill_module",
                "priority": "medium",
                "target": item["name"],
                "target_ability": "",
                "reason": f"近期开源招聘证据出现 {item['count']} 次，当前课程知识点未明确覆盖。",
                "suggestion": f"将「{item['name']}」纳入最相关核心课的教学模块和过程性考核。",
                "hours_delta": 2,
                "completed": False,
            })
        if analysis.get("summary", {}).get("practice_ratio", 0) < 40:
            actions.append({
                "id": "practice-ratio",
                "type": "increase_practice",
                "priority": "medium",
                "target": "实践教学占比",
                "target_ability": "",
                "reason": f"当前实践学时占比为 {analysis['summary']['practice_ratio']}%。",
                "suggestion": "优先将新增学时配置到站场运行综合实训和设备仪表实践环节。",
                "hours_delta": 8,
                "completed": False,
            })
        if not actions:
            actions.append({
                "id": "maintain-monitoring",
                "type": "monitor",
                "priority": "low",
                "target": "培养方案持续监测",
                "target_ability": "",
                "reason": "当前证据未显示显著能力覆盖缺口。",
                "suggestion": "保持现有课程结构，下一采集周期复核岗位样本和产业标准变化。",
                "hours_delta": 0,
                "completed": False,
            })
        return actions

    async def create_proposal(
        self, db: AsyncSession, program: CurriculumProgram, months: int, teacher_id: int
    ) -> ProgramAdjustmentProposal:
        analysis = await self.analyze(db, program, months)
        persisted_analysis = jsonable_encoder(analysis)
        proposal = ProgramAdjustmentProposal(
            base_program_id=program.id,
            target_version=program.version + 1,
            status="draft",
            title=f"{program.major}培养方案 V{program.version + 1} 调整草案",
            analysis_snapshot=persisted_analysis,
            actions=self.build_actions(analysis),
            evidence_refs=persisted_analysis.get("evidence_refs", []),
            created_by=teacher_id,
        )
        db.add(proposal)
        await db.commit()
        await db.refresh(proposal)
        return proposal

    async def publish(
        self, db: AsyncSession, proposal: ProgramAdjustmentProposal, teacher_id: int
    ) -> CurriculumProgram:
        base = await self.get_program(db, proposal.base_program_id)
        latest_version = (
            await db.execute(
                select(CurriculumProgram.version)
                .where(CurriculumProgram.program_code == base.program_code)
                .order_by(CurriculumProgram.version.desc())
            )
        ).scalars().first() or base.version
        target_version = max(proposal.target_version, latest_version + 1)
        new_program = CurriculumProgram(
            program_code=base.program_code,
            major=base.major,
            major_id=base.major_id,
            name=base.name,
            version=target_version,
            status="published",
            objectives=base.objectives,
            graduation_requirements=list(base.graduation_requirements or []),
            source_period_months=base.source_period_months,
            change_summary="；".join(str(item.get("suggestion", "")) for item in (proposal.actions or []) if item.get("suggestion")),
            parent_program_id=base.id,
            created_by=teacher_id,
            reviewed_by=teacher_id,
            published_at=_now(),
        )
        db.add(new_program)
        await db.flush()

        actions = proposal.actions or []
        for course in base.courses:
            weights = dict(course.ability_weights or {})
            knowledge_points = list(course.knowledge_points or [])
            total_hours = course.total_hours
            practice_hours = course.practice_hours
            assessment = course.assessment_method
            for action in actions:
                if action.get("type") == "strengthen_ability" and action.get("target_ability") in weights:
                    key = str(action["target_ability"])
                    weights[key] = float(weights.get(key, 0)) + 0.08
                    weight_sum = sum(float(value) for value in weights.values()) or 1
                    weights = {name: round(float(value) / weight_sum, 4) for name, value in weights.items()}
                    assessment = f"{assessment}；强化{action.get('target')}岗位任务考核"
                elif action.get("type") == "add_skill_module" and course.category in {"专业核心课", "集中实践课"}:
                    target = str(action.get("target", "")).strip()
                    if target and target not in knowledge_points:
                        knowledge_points.append(target)
                        break
                elif action.get("type") == "increase_practice" and course.category == "集中实践课":
                    delta = max(0, int(action.get("hours_delta", 0)))
                    total_hours += delta
                    practice_hours += delta
            db.add(CurriculumCourse(
                program_id=new_program.id,
                course_code=course.course_code,
                name=course.name,
                category=course.category,
                total_hours=total_hours,
                practice_hours=min(practice_hours, total_hours),
                ability_weights=weights,
                knowledge_points=knowledge_points,
                position_ids=list(course.position_ids or []),
                assessment_method=assessment,
                enabled=course.enabled,
                sort_order=course.sort_order,
            ))
        base.status = "archived"
        proposal.status = "published"
        proposal.reviewed_by = teacher_id
        proposal.reviewed_at = _now()
        proposal.published_program_id = new_program.id
        proposal.published_at = _now()
        await db.commit()
        return await self.get_program(db, new_program.id)


__all__ = ["ProgramAnalysisService", "program_out"]
