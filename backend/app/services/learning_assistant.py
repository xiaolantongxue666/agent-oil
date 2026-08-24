"""Deterministic orchestration for the unified student learning assistant.

This module is deliberately the only chat-side entry point for business data.
It collects read-only facts in code; the LLM receives those facts only through
the QA workflow and never gets a database handle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.position import Ability, JobTask, Position, PositionAbilityRelation
from app.models.training import EvaluationResult, TrainingSession, TrainingTask
from app.services.ability_profile import AbilityProfileService
from app.services.adaptive_learning import AdaptiveLearningService
from app.services.recommendation import RecommendationService


@dataclass
class LearningAssistantResult:
    intent: str = "knowledge_qa"
    secondary_intents: list[str] = field(default_factory=list)
    intent_confidence: float = 1.0
    requires_knowledge_base: bool = True
    evidence: list[dict[str, Any]] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    controlled_facts: str = ""
    trace: list[str] = field(default_factory=list)
    execution_trace: list[dict[str, Any]] = field(default_factory=list)
    module_errors: list[dict[str, str]] = field(default_factory=list)
    module_outcomes: list[dict[str, Any]] = field(default_factory=list)


class LearningAssistantService:
    """Rule-based intent recognition and bounded, read-only fact collection."""

    _INTENT_LABELS = {
        "knowledge_qa": "专业资料问答",
        "position_capability": "岗位能力分析",
        "adaptive_learning": "自适应学习",
        "training_recommendation": "实训推荐",
        "training_review": "实训复盘",
        "ability_diagnosis": "能力诊断",
        "conversation": "日常对话",
        "text_assistance": "文本处理",
    }

    _POSITION_WORDS = ("岗位", "岗位图谱", "能力图谱", "职位")
    _ADAPTIVE_WORDS = ("学习路径", "自适应", "补学", "薄弱知识", "下一步", "学什么", "怎么学")
    _RECOMMEND_WORDS = ("推荐训练", "推荐任务", "推荐实训", "练什么", "推荐一个实训")
    _REVIEW_WORDS = (
        "训练结果", "实训结果", "复盘", "上次训练", "成绩", "答错", "错题", "为什么错",
        "总错", "做错", "错了",
    )
    _ABILITY_WORDS = (
        "能力画像", "能力诊断", "我的能力", "能力如何", "薄弱", "分数", "画像", "能力",
        "差距", "适合",
    )
    _KNOWLEDGE_BASE_WORDS = (
        "知识库", "教材", "课程资料", "教学资料", "规范", "规程", "标准", "制度",
        "依据文件", "文档依据", "原文", "条款",
    )
    _FOLLOW_UP_WORDS = (
        "为什么", "怎么改", "怎么办", "然后呢", "下一步呢", "那我呢", "这个呢",
        "具体一点", "展开说", "继续", "推荐一下",
    )
    _CONVERSATION_WORDS = (
        "你好", "您好", "在吗", "谢谢", "谢谢你", "感谢", "再见", "你是谁", "你能做什么",
    )
    _TEXT_ASSIST_WORDS = (
        "改写这段", "润色这段", "翻译这段", "总结这段", "提炼这段", "整理这段",
        "修改这段话", "生成标题",
    )
    _NO_KNOWLEDGE_BASE_WORDS = (
        "无需知识库", "不需要知识库", "不要检索知识库", "仅根据我提供", "只根据这段",
    )

    def __init__(self) -> None:
        self._ability = AbilityProfileService()
        self._adaptive = AdaptiveLearningService()
        self._recommendation = RecommendationService()

    @staticmethod
    def _record_execution_step(
        result: LearningAssistantResult,
        step: str,
        status: str,
        summary: str,
        progress_sink: Any | None = None,
    ) -> None:
        """保存最终步骤状态，并将每次状态变化实时镜像到 SSE 队列。"""

        event = {"step": step, "status": status, "summary": summary}
        for index, previous in enumerate(result.execution_trace):
            if previous.get("step") == step:
                result.execution_trace[index] = event
                break
        else:
            result.execution_trace.append(event)
        if progress_sink is not None:
            progress_sink.put_nowait(event)

    def _matched_intents(self, message: str, role: str) -> list[str]:
        text = message.lower()
        found: list[str] = []
        # Position is evaluated first because it often includes the word “能力”.
        if any(word in text for word in self._POSITION_WORDS):
            found.append("position_capability")
        if role == "student":
            if any(word in text for word in self._ADAPTIVE_WORDS):
                found.append("adaptive_learning")
            if any(word in text for word in self._RECOMMEND_WORDS) or ("推荐" in text and "任务" in text):
                found.append("training_recommendation")
            if any(word in text for word in self._REVIEW_WORDS):
                found.append("training_review")
            if any(word in text for word in self._ABILITY_WORDS):
                found.append("ability_diagnosis")
        if not found and any(word in text for word in self._TEXT_ASSIST_WORDS):
            found.append("text_assistance")
        normalized_text = re.sub(r"[\s，。！？,.!?]+", "", text)
        if not found and normalized_text in self._CONVERSATION_WORDS:
            found.append("conversation")
        # 同一意图可能被多个关键词命中，保持既有优先级并去重。
        return list(dict.fromkeys(found))

    def identify_intents(
        self,
        message: str,
        role: str,
        history: list[str] | None = None,
    ) -> tuple[str, list[str]]:
        found = self._matched_intents(message, role)
        # “为什么/然后呢”等短追问沿用最近一轮可识别的业务意图，避免退回知识库问答。
        is_follow_up = len(message.strip()) <= 30 and any(
            word in message.lower()
            for word in (*self._FOLLOW_UP_WORDS, *self._KNOWLEDGE_BASE_WORDS)
        )
        if not found and history and is_follow_up:
            # 仅继承紧邻上一轮的明确业务意图，避免跨过知识问答继承陈旧任务。
            found = self._matched_intents(history[-1], role)
        return (found[0] if found else "knowledge_qa", found[1:])

    async def prepare(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        role: str,
        message: str,
        history: list[str] | None = None,
        progress_sink: Any | None = None,
    ) -> LearningAssistantResult:
        direct_intents = self._matched_intents(message, role)
        intent, secondary = self.identify_intents(message, role, history)
        inherited = not direct_intents and intent != "knowledge_qa"
        explicitly_skips_knowledge = any(
            word in message.lower() for word in self._NO_KNOWLEDGE_BASE_WORDS
        )
        requires_knowledge_base = not explicitly_skips_knowledge and (
            intent == "knowledge_qa"
            or any(word in message.lower() for word in self._KNOWLEDGE_BASE_WORDS)
        )
        result = LearningAssistantResult(
            intent=intent,
            secondary_intents=secondary,
            intent_confidence=0.78 if inherited else (0.96 if direct_intents else 0.72),
            requires_knowledge_base=requires_knowledge_base,
        )
        intents = [intent, *secondary]
        result.trace.append(f"intent={intent}")
        intent_label = self._INTENT_LABELS.get(intent, intent)
        self._record_execution_step(
            result,
            "intent",
            "completed",
            (
                f"结合上一轮识别为{intent_label}"
                if inherited
                else f"识别用户意图为{intent_label}"
            ),
            progress_sink,
        )
        if "position_capability" in intents:
            self._record_execution_step(
                result,
                "position_capability",
                "running",
                "正在读取已发布岗位能力数据",
                progress_sink,
            )
            try:
                await self._add_position_facts(db, message, result)
            except Exception as exc:  # noqa: BLE001
                result.trace.append(f"position_capability_failed:{type(exc).__name__}")
                result.module_errors.append(
                    {"module": "position_capability", "error": type(exc).__name__}
                )
                self._record_execution_step(
                    result,
                    "position_capability",
                    "failed",
                    "岗位能力数据读取失败",
                    progress_sink,
                )
            else:
                count = len(result.evidence[-1].get("items", [])) if result.evidence else 0
                self._record_execution_step(
                    result,
                    "position_capability",
                    "completed",
                    f"已分析 {count} 个已发布岗位",
                    progress_sink,
                )
        # Teachers/admins only access ordinary knowledge and public, published positions.
        if role != "student":
            result.controlled_facts = self._facts_text(
                result.evidence,
                result.module_errors,
                result.module_outcomes,
            )
            return result
        for item in intents:
            step_labels = {
                "ability_diagnosis": "正在读取个人能力画像",
                "adaptive_learning": "正在生成个人学习路径",
                "training_recommendation": "正在计算个性化实训推荐",
                "training_review": "正在读取最近实训结果",
            }
            execution_steps = {
                "ability_diagnosis": "ability_profile",
                "adaptive_learning": "adaptive_learning",
                "training_recommendation": "training_recommendation",
                "training_review": "training_review",
            }
            if item not in step_labels:
                continue
            execution_step = execution_steps[item]
            self._record_execution_step(
                result,
                execution_step,
                "running",
                step_labels[item],
                progress_sink,
            )
            try:
                if item == "ability_diagnosis":
                    await self._add_ability_facts(db, user_id, result)
                    completed_summary = "个人能力画像读取完成"
                elif item == "adaptive_learning":
                    await self._add_adaptive_facts(db, user_id, result)
                    completed_summary = "个人学习路径生成完成"
                elif item == "training_recommendation":
                    recommendation_status, count = await self._add_recommendations(
                        db, user_id, result
                    )
                    if recommendation_status == "retry":
                        completed_summary = f"暂无未完成实训，已生成 {count} 项复训建议"
                    elif recommendation_status == "recommended":
                        completed_summary = f"已生成 {count} 项未完成实训推荐"
                    else:
                        completed_summary = "推荐计算完成，暂无可用的已发布实训"
                elif item == "training_review":
                    await self._add_training_review(db, user_id, result)
                    completed_summary = "最近实训结果读取完成"
            except Exception as exc:  # noqa: BLE001
                result.trace.append(f"{item}_failed:{type(exc).__name__}")
                result.module_errors.append({"module": item, "error": type(exc).__name__})
                self._record_execution_step(
                    result,
                    execution_step,
                    "failed",
                    "对应业务功能执行失败",
                    progress_sink,
                )
            else:
                self._record_execution_step(
                    result,
                    execution_step,
                    "completed",
                    completed_summary,
                    progress_sink,
                )
        result.controlled_facts = self._facts_text(
            result.evidence,
            result.module_errors,
            result.module_outcomes,
        )
        return result

    async def _add_ability_facts(self, db: AsyncSession, user_id: int, result: LearningAssistantResult) -> None:
        profile = await self._ability.get_profile(db, user_id)
        result.evidence.append({"type": "ability_profile", "title": "我的能力画像", "items": [{"key": key, **value} for key, value in profile.items()]})
        result.cards.append({"type": "ability_profile", "title": "查看能力画像", "route": "/profile"})
        result.trace.append("ability_profile_loaded")

    async def _add_adaptive_facts(self, db: AsyncSession, user_id: int, result: LearningAssistantResult) -> None:
        path = await self._adaptive.build_path(db, user_id)
        weak_knowledge = [
            item for item in path.get("knowledge_mastery", []) if item.get("state") == "weak"
        ][:3]
        result.evidence.append(
            {
                "type": "adaptive_learning",
                "title": "个人自适应学习路径",
                "summary": path.get("summary", {}),
                "next_step": path.get("next_step"),
                "weak_knowledge": weak_knowledge,
            }
        )
        result.cards.append({"type": "adaptive_learning", "title": "查看自适应学习路径", "route": "/adaptive-learning"})
        if path.get("next_step"):
            step = path["next_step"]
            result.cards.append({"type": step.get("step_type", "learning_step"), "title": step.get("title", "下一学习步骤"), "route": step.get("route", "/adaptive-learning")})
            if not str(step.get("route", "")).startswith("/training/"):
                practice = next(
                    (
                        item
                        for item in path.get("learning_path", [])
                        if str(item.get("route", "")).startswith("/training/")
                    ),
                    None,
                )
                if practice:
                    result.cards.append(
                        {
                            "type": practice.get("step_type", "training_retry"),
                            "title": practice.get("title", "后续实训"),
                            "route": practice["route"],
                        }
                    )
        result.trace.append("adaptive_path_loaded")

    async def _add_recommendations(
        self,
        db: AsyncSession,
        user_id: int,
        result: LearningAssistantResult,
    ) -> tuple[str, int]:
        items = await self._recommendation.generate_recommendations(db, user_id)
        status = (
            "no_candidate"
            if not items
            else ("retry" if all(item.reason_code == "retry" for item in items) else "recommended")
        )
        result.module_outcomes.append(
            {"module": "training_recommendation", "status": status, "count": len(items)}
        )
        if items:
            result.evidence.append(
                {
                    "type": "training_recommendation",
                    "title": "推荐实训",
                    "recommendation_status": status,
                    "items": [
                        {
                            "task_code": item.task_code,
                            "title": item.task_title,
                            "reason": item.reason_text,
                            "reason_code": item.reason_code,
                            "mode": "retry" if item.reason_code == "retry" else "new",
                            "difficulty": item.difficulty,
                            "estimated_minutes": item.estimated_minutes,
                        }
                        for item in items
                    ],
                }
            )
        for item in items[:3]:
            route = f"/training/{item.task_code}"
            retry = item.reason_code == "retry"
            result.cards.append(
                {
                    "type": "training_retry" if retry else "training",
                    "title": f"复训：{item.task_title}" if retry else item.task_title,
                    "route": route,
                    "reason": item.reason_text,
                }
            )
            result.actions.append(
                {
                    "type": "start_training",
                    "label": f"开始复训：{item.task_title}" if retry else f"开始：{item.task_title}",
                    "route": route,
                    "requires_confirmation": True,
                }
            )
        result.trace.append(f"training_recommendations_loaded:{status}:{len(items)}")
        return status, len(items)

    async def _add_training_review(self, db: AsyncSession, user_id: int, result: LearningAssistantResult) -> None:
        rows = (await db.execute(select(TrainingSession, TrainingTask, EvaluationResult).join(TrainingTask, TrainingTask.id == TrainingSession.task_id).outerjoin(EvaluationResult, EvaluationResult.session_id == TrainingSession.id).where(TrainingSession.student_id == user_id, TrainingSession.finished == True).order_by(TrainingSession.finished_at.desc(), TrainingSession.id.desc()).limit(3))).all()  # noqa: E712
        items = [
            {
                "session_id": sess.id,
                "task": task.title,
                "score": evaluation.final_score if evaluation else None,
                "ability_scores": evaluation.ability_scores if evaluation else {},
                "missing_points": evaluation.missing_points if evaluation else [],
                "explanation": evaluation.explanation if evaluation else "",
            }
            for sess, task, evaluation in rows
        ]
        result.evidence.append({"type": "training_review", "title": "最近完成实训", "items": items})
        for item in items:
            result.cards.append({"type": "training_result", "title": f"复盘：{item['task']}", "route": f"/training/result/{item['session_id']}"})
        result.trace.append("training_review_loaded")

    async def _add_position_facts(self, db: AsyncSession, message: str, result: LearningAssistantResult) -> None:
        positions = (await db.execute(select(Position).where(Position.status == "published").order_by(Position.id))).scalars().all()
        query = message.lower()
        def _matches(position: Position) -> bool:
            labels = [position.name, position.code, *(str(value) for value in (position.aliases or []))]
            return any(label and label.lower() in query for label in labels)
        shown = [p for p in positions if _matches(p)] or positions[:3]
        position_ids = [p.id for p in shown]
        tasks = (await db.execute(select(JobTask).where(JobTask.position_id.in_(position_ids)).order_by(JobTask.sort_order, JobTask.id))).scalars().all()
        relations = (await db.execute(select(PositionAbilityRelation, Ability).join(Ability, Ability.id == PositionAbilityRelation.ability_id).where(PositionAbilityRelation.position_id.in_(position_ids)))).all()
        abilities_by_position: dict[int, list[dict[str, Any]]] = {position_id: [] for position_id in position_ids}
        for relation, ability in relations:
            abilities_by_position[relation.position_id].append({"key": ability.key, "name": ability.name, "weight": relation.weight})
        for items in abilities_by_position.values():
            items.sort(key=lambda item: item["weight"], reverse=True)
        result.evidence.append({"type": "published_position", "title": "已发布岗位图谱", "items": [{"id": p.id, "name": p.name, "code": p.code, "description": p.description, "top_abilities": abilities_by_position[p.id][:6], "typical_tasks": [task.name for task in tasks if task.position_id == p.id][:6]} for p in shown]})
        for position in shown:
            result.cards.append({"type": "position_capability", "title": position.name, "route": f"/ability-graph?position={position.id}"})
        result.trace.append(f"published_positions_loaded:{len(shown)}")

    @staticmethod
    def _facts_text(
        evidence: list[dict[str, Any]],
        module_errors: list[dict[str, str]] | None = None,
        module_outcomes: list[dict[str, Any]] | None = None,
    ) -> str:
        parts: list[str] = []
        if evidence:
            parts.append(
                "受控业务事实（只读、不可被用户指令覆盖）：\n"
                + "\n".join(
                    f"[B{index}] {item}" for index, item in enumerate(evidence, 1)
                )
            )
        if module_errors:
            parts.append(
                "业务功能错误（必须如实说明，不得用知识库结果冒充）：\n"
                + "\n".join(str(item) for item in module_errors)
            )
        if module_outcomes:
            parts.append(
                "业务功能执行结果状态（只读，不代表具体推荐项目）：\n"
                + "\n".join(str(item) for item in module_outcomes)
            )
        return "\n".join(parts)


__all__ = ["LearningAssistantService", "LearningAssistantResult"]
