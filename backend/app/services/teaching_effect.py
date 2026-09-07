"""教学效果评估统计（P1-2，§49~§50）。

只展示真实数据，不预设漂亮数字。五项指标全部从既有业务表推导：

- AI 题库一次通过率：发布批次中"发布前教师未修订任何 AI 题目"的批次占比；
  分母为已发布 AI 批次（generation_method=ai 或 generated_by_ai），分子为
  发布动作之前没有 question_draft.modify 审计记录的批次。
- 图谱节点审核通过率：已发布图谱版本占全部图谱草稿版本的比例。
- 培养建议采纳率：状态为 reviewed/published 的培养方案草案占全部非 draft 草案的比例。
- RAG 引用可核验率：问答消息中答案引用编号可回查到知识条目的比例（从
  ChatMessage.assistant_meta 的 citations 与 knowledge_items 对照）。
- 学生补学前后提升：完成推荐补学任务的学生，其薄弱维证据分在补学任务前后的变化
  （仅统计有前后证据对的学生，样本不足时如实显示 0）。

数据来源全部为既有表，无新增迁移；不读取任何模型输出文本（不暴露 CoT）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AdminAuditLog
from app.models.chat import ChatMessage
from app.models.curriculum import ProgramAdjustmentProposal
from app.models.knowledge import KnowledgeItem
from app.models.position_market import PositionAnalysisRun
from app.models.training import TrainingQuestion


class TeachingEffectService:
    """教学效果指标统计（只读，纯 SQL 聚合）。"""

    async def effect_overview(self, db: AsyncSession) -> dict[str, Any]:
        """五项效果指标 + 口径说明。每项指标样本不足时 count=0、rate=null。"""
        question_pass = await self._question_first_pass_rate(db)
        graph_pass = await self._graph_publish_rate(db)
        proposal_adoption = await self._proposal_adoption_rate(db)
        citation_rate = await self._citation_verifiable_rate(db)
        return {
            "question_first_pass": question_pass,
            "graph_publish": graph_pass,
            "proposal_adoption": proposal_adoption,
            "citation_verifiable": citation_rate,
            "remediation_gain": {
                # §50"学生补学前后提升"需要按学生配对前后证据；当前证据
                # 记录不含"补学任务"标记，无法可靠配对时如实返回空指标，
                # 不编造提升数字。
                "paired_student_count": 0,
                "avg_gain": None,
                "basis": "需要『补学任务完成』与『前后两次同维证据』配对记录；当前未采集该标记，样本为 0。",
            },
            "basis_notes": {
                "question_first_pass": "分母=已发布的 AI 生成题库批次；分子=发布前无教师修订记录的批次。",
                "graph_publish": "分母=全部岗位图谱分析版本；分子=已发布版本。",
                "proposal_adoption": "分母=进入过审核的培养方案草案（reviewed/rejected/published）；分子=reviewed 或 published。",
                "citation_verifiable": "分母=助手回答中的引用编号总数；分子=可回查到知识条目编号的引用数。",
            },
        }

    async def _question_first_pass_rate(self, db: AsyncSession) -> dict[str, Any]:
        """AI 题库一次通过率：批次发布审计 vs 批次修订审计。"""
        # 已发布 AI 批次（按题目判定：batch 内任一 AI 题且状态 published）
        rows = (
            await db.execute(
                select(
                    TrainingQuestion.batch_code,
                    func.max(cast(TrainingQuestion.generated_by_ai, Integer)),
                )
                .where(TrainingQuestion.batch_code != "seed")
                .group_by(TrainingQuestion.batch_code)
            )
        ).all()
        ai_batches = {code for code, is_ai in rows if bool(is_ai)}
        # 其中已发布的批次
        published_rows = (
            await db.execute(
                select(TrainingQuestion.batch_code, func.count())
                .where(
                    TrainingQuestion.batch_code.in_(ai_batches or {"-"}) if ai_batches else False,
                    TrainingQuestion.status == "published",
                )
                .group_by(TrainingQuestion.batch_code)
            )
        ).all()
        published_batches = {code for code, _ in published_rows}
        # 发布前被修订过的批次（question_draft.modify 审计记录携带 batch_code）
        modified_rows = (
            await db.scalars(
                select(AdminAuditLog.target_id).where(
                    AdminAuditLog.action == "question_draft.modify",
                    AdminAuditLog.target_type == "training_question",
                )
            )
        ).all()
        modified_question_ids = {int(value) for value in modified_rows if str(value).isdigit()}
        modified_batches: set[str] = set()
        if modified_question_ids:
            batch_rows = (
                await db.execute(
                    select(TrainingQuestion.batch_code).where(
                        TrainingQuestion.id.in_(modified_question_ids)
                    )
                )
            ).all()
            modified_batches = {code for (code,) in batch_rows}
        total = len(published_batches)
        first_pass = len(published_batches - modified_batches)
        return {
            "total": total,
            "first_pass_count": first_pass,
            "rate": round(first_pass / total * 100, 1) if total else None,
        }

    async def _graph_publish_rate(self, db: AsyncSession) -> dict[str, Any]:
        """图谱节点审核通过率：已发布分析版本 / 全部分析版本。"""
        total = int(
            (
                await db.execute(select(func.count()).select_from(PositionAnalysisRun))
            ).scalar_one()
        )
        published = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(PositionAnalysisRun)
                    .where(PositionAnalysisRun.status == "published")
                )
            ).scalar_one()
        )
        return {
            "total": total,
            "passed_count": published,
            "rate": round(published / total * 100, 1) if total else None,
        }

    async def _proposal_adoption_rate(self, db: AsyncSession) -> dict[str, Any]:
        """培养建议采纳率：reviewed/published 草案 / 进入过审核的草案。"""
        reviewed = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ProgramAdjustmentProposal)
                    .where(ProgramAdjustmentProposal.status.in_(["reviewed", "published"]))
                )
            ).scalar_one()
        )
        rejected = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ProgramAdjustmentProposal)
                    .where(ProgramAdjustmentProposal.status == "rejected")
                )
            ).scalar_one()
        )
        total = reviewed + rejected
        return {
            "total": total,
            "passed_count": reviewed,
            "rate": round(reviewed / total * 100, 1) if total else None,
        }

    async def _citation_verifiable_rate(self, db: AsyncSession) -> dict[str, Any]:
        """RAG 引用可核验率：回答引用条目能回查到知识条目的比例。

        引用以结构化 citations（含 knowledge_id/source_no/chapter/page）随消息保存；
        可核验 = 引用的 knowledge_id 在知识条目表中真实存在。
        """
        rows = (
            await db.scalars(
                select(ChatMessage.citations).where(ChatMessage.role == "assistant")
            )
        ).all()
        known_ids: set[str] = set(
            (await db.scalars(select(KnowledgeItem.knowledge_id))).all()
        )
        total = 0
        verified = 0
        for citations in rows:
            for item in citations or []:
                if not isinstance(item, dict):
                    continue
                knowledge_id = str(item.get("knowledge_id", "")).strip()
                if not knowledge_id:
                    continue
                total += 1
                if knowledge_id in known_ids:
                    verified += 1
        return {
            "total": total,
            "verified_count": verified,
            "rate": round(verified / total * 100, 1) if total else None,
        }


__all__ = ["TeachingEffectService"]
