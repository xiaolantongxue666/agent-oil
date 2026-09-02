"""比赛总览聚合（P0-4 Phase 7，§35~§39）。

为"比赛模式首页"提供一条可下钻的主链聚合视图：

- 顶部指标（§30 口径）：专业群/专业/岗位/典型任务/能力/课程/岗位证据计数 + 主要缺口；
- 真实发现案例（§38）：取群级分析中 Gap 最大的能力，展示产业需求、课程供给、Gap
  百分比与产生需求 Top 岗位——全部来自 `ProfessionalGroupAnalysisService.analyze_group`
  现有确定性计算，不重新发明口径、不读学生数据、不经 LLM；
- 证据下钻（§39）：该 Gap 能力关联的招聘快照（含企业/来源/发布日期/技能词）与
  权威知识条目，直接取自 analyze 结果的 evidence_refs 之外的原始表查询，保证字段可追溯；
- 实训映射（§40 第 7~8 环）：把 Gap 能力映射到已发布的仿真实训场景
  （场景 JSON 的 target_abilities），供首页跳转实训入口。

数据边界与群级分析一致：只读岗位图谱、招聘快照、产业证据、课程与场景配置；
刻意不查询任何学生/实训/能力证据表。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.response import AppError
from app.models.position import Ability, JobTask, Position, PositionAbilityRelation
from app.models.position_market import JobPostingSnapshot
from app.scenarios import load_scenarios
from app.services.professional_group_analysis import ProfessionalGroupAnalysisService


def _now() -> datetime:
    return datetime.now(UTC)


class CompetitionOverviewService:
    """比赛总览聚合服务；复用群级分析结果，只做编排与下钻装配。"""

    def __init__(self) -> None:
        self._analysis = ProfessionalGroupAnalysisService()

    async def build_overview(self, db: AsyncSession, group_id: int, months: int) -> dict[str, Any]:
        """构建比赛首页聚合视图。任何字段缺失时结构完整但计数为 0，不抛非预期异常。"""
        analysis = await self._analysis.analyze_group(db, group_id, months)
        majors = await self._analysis.load_group_majors(db, await self._analysis.get_group(db, group_id))

        metrics = await self._build_metrics(db, analysis, majors)
        discovery = self._pick_discovery(analysis)
        evidence = await self._load_case_evidence(db, analysis, discovery)
        scenario = self._map_scenario(discovery["ability_key"])
        return {
            "group": analysis["scope"]["target"],
            "metrics": metrics,
            "discovery": discovery,
            "evidence": evidence,
            "scenario": scenario,
            "generated_at": _now(),
        }

    async def _build_metrics(
        self,
        db: AsyncSession,
        analysis: dict[str, Any],
        majors: list,
    ) -> dict[str, Any]:
        """顶部指标（§30）：群级分析计数 + 典型任务/能力节点数 + 主要缺口。"""
        major_ids = [m.id for m in majors]
        task_count = 0
        ability_count = 0
        if major_ids:
            # 典型任务/能力节点按群内岗位的归属专业统计（与 analyze_group 同一岗位集合）
            position_ids_rows = (
                await db.execute(
                    select(Position.id).where(
                        Position.major_id.in_(major_ids) | Position.major.in_([m.name for m in majors]),
                        Position.status == "published",
                    )
                )
            ).all()
            position_ids = [row[0] for row in position_ids_rows]
            if position_ids:
                task_count = int(
                    (
                        await db.execute(
                            select(func.count())
                            .select_from(JobTask)
                            .where(JobTask.position_id.in_(position_ids))
                        )
                    ).scalar_one()
                )
                ability_count = int(
                    (
                        await db.execute(
                            select(func.count())
                            .select_from(PositionAbilityRelation)
                            .where(PositionAbilityRelation.position_id.in_(position_ids))
                        )
                    ).scalar_one()
                )

        summary = analysis["summary"]
        top_gap = analysis["ability_gaps"][0] if analysis["ability_gaps"] else None
        return {
            "group_count": 1,
            "major_count": summary["major_count"],
            "position_count": summary["position_count"],
            "task_count": task_count,
            "ability_node_count": ability_count,
            "course_count": summary["course_count"],
            "job_sample_count": summary["job_sample_count"],
            "industry_evidence_count": summary["industry_evidence_count"],
            "authoritative_evidence_count": summary["authoritative_evidence_count"],
            "top_gap_ability": top_gap["ability_name"] if top_gap else "",
            "top_gap_value": top_gap["gap"] if top_gap else 0.0,
            "data_confidence": summary["confidence"],
        }

    def _pick_discovery(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """真实发现案例（§38）：Gap 最大的能力 + 需求占比 + 供给占比 + 需求来源岗位。"""
        gaps = analysis.get("ability_gaps", [])
        if not gaps:
            raise AppError("COMPETITION_NO_ANALYSIS", "暂无可分析的群级能力数据", 409)
        top = gaps[0]
        demand_positions = [
            {"id": p["id"], "name": p["name"], "major_name": p["major_name"], "sample_count": p["sample_count"]}
            for p in analysis.get("positions", [])
        ][:5]
        return {
            "ability_key": top["ability_key"],
            "ability_name": top["ability_name"],
            "demand_share": top["demand_share"],
            "curriculum_share": top["curriculum_share"],
            "gap": top["gap"],
            "covered_by": top.get("covered_by", [])[:3],
            "uncovered_skills": analysis.get("uncovered_skills", [])[:4],
            "demand_positions": demand_positions,
            "months": analysis["scope"]["months"],
            "data_confidence": analysis["summary"]["confidence"],
        }

    async def _load_case_evidence(
        self,
        db: AsyncSession,
        analysis: dict[str, Any],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """§39 证据链下钻：该能力关联岗位的招聘快照 + 权威知识（可追溯字段直出）。"""
        ability_key = discovery["ability_key"]
        ability = (
            await db.execute(select(Ability).where(Ability.key == ability_key))
        ).scalars().first()
        postings: list[dict[str, Any]] = []
        knowledge: list[dict[str, Any]] = []
        if ability is not None:
            position_ids = list(
                (
                    await db.execute(
                        select(PositionAbilityRelation.position_id).where(
                            PositionAbilityRelation.ability_id == ability.id
                        )
                    )
                ).scalars().all()
            )
            if position_ids:
                rows = (
                    await db.execute(
                        select(JobPostingSnapshot)
                        .where(
                            JobPostingSnapshot.position_id.in_(position_ids),
                            JobPostingSnapshot.published_at.is_not(None),
                            JobPostingSnapshot.date_confidence.in_(["high", "medium"]),
                        )
                        .order_by(JobPostingSnapshot.published_at.desc())
                        .limit(6)
                    )
                ).scalars().all()
                postings = [
                    {
                        "id": item.id,
                        "title": item.title,
                        "company": item.company,
                        "source_name": item.source_name,
                        "source_url": item.source_url,
                        "published_at": item.published_at,
                        "observed_at": item.observed_at,
                        "date_confidence": item.date_confidence,
                        "skills": item.skills or [],
                        "snippet": item.snippet[:160],
                    }
                    for item in rows
                ]
            # 权威知识条目：从群级分析 evidence_refs 中按类型过滤（已含来源编号/页码）
            knowledge = [
                ref
                for ref in analysis.get("evidence_refs", [])
                if ref.get("type") == "authoritative_knowledge"
            ][:4]
        return {
            "ability_key": ability_key,
            "job_postings": postings,
            "authoritative_knowledge": knowledge,
        }

    def _map_scenario(self, ability_key: str) -> dict[str, Any] | None:
        """Gap 能力 → 已发布仿真实训场景（§40 第 7~8 环的跳转入口）。"""
        for code, scenario in load_scenarios().items():
            targets = scenario.get("target_abilities", [])
            if ability_key in targets:
                return {
                    "scenario_code": code,
                    "title": scenario["title"],
                    "difficulty": scenario.get("difficulty", 2),
                    "estimated_minutes": scenario.get("estimated_minutes", 20),
                    "teaching_simulation": True,
                    "disclaimer": scenario.get("disclaimer", ""),
                }
        return None


__all__ = ["CompetitionOverviewService"]
