"""自适应学习路径（P0-5 Phase 6 升级：统一消费 AbilityEvidence）。

§41：补强判定不再只看 TrainingChoiceAnswer 明细，统一读取 AbilityEvidence
（知识测验 / 情境选择 / 仿真实操 / 情境诊断 / 教师评价五类证据）。
§42：学习路径同时考虑——知识答题表现（知识点粒度）、近期表现（近段平均）、
历史趋势（近段 vs 前段）、能力置信度（AbilityScore.confidence）。
§43：薄弱 + 置信度达标 + 最近连续低分操作/诊断证据 → 生成确定性四段链：
相关知识点 → 案例学习 → 低一级难度训练 → 原仿真实训重练。
§44：安全优先规则保留并配置化（adaptive_safety_*），全部为业务层规则，
不调用 LLM。知识点掌握度部分沿用选择题明细（证据无 knowledge_point 维度）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.models.ability import AbilityScore
from app.models.ability_evidence import AbilityEvidence
from app.models.position import Ability
from app.models.training import (
    TrainingChoiceAnswer,
    TrainingQuestion,
    TrainingSession,
    TrainingTask,
)
from app.scenarios import load_scenarios

# 操作型证据（§42"操作型实训表现"）：仿真实操 + 情境诊断
OPERATIONAL_SOURCES = frozenset({"operation_event", "scenario_diagnosis"})


def _simulation_scenario_code(task: Any) -> str | None:
    """R045：按任务真实类型判型——仿真任务的 scenario 元数据由 seed 配置驱动生成
    （{"simulation": true, "scenario_code": ...}），且无选择题题库。"""
    meta = getattr(task, "scenario", None)
    if not isinstance(meta, dict) or not meta.get("simulation"):
        return None
    code = str(meta.get("scenario_code") or "").strip()
    return code or None


def _task_activity(task: Any) -> tuple[str, str]:
    """返回 (activity_type, route)：只使用前端既有路由，不新增 shortcut。

    - simulation → /simulation/{scenario_code}（仿真工作台，simulation start）
    - choice     → /training/{task.code}（选择题实训）
    """
    sim_code = _simulation_scenario_code(task)
    if sim_code is not None:
        return "simulation", f"/simulation/{sim_code}"
    return "choice", f"/training/{getattr(task, 'code', '')}"


def _launchable_tasks(tasks: list[Any], scenario_codes: set[str]) -> list[Any]:
    """过滤出真实可启动任务（与 /training/tasks 列表及 /training/start 的门槛一致）：

    - 仿真任务：其 scenario_code 必须在当前场景目录可加载（否则 start 404/409）；
    - 选择题任务：至少一道启用且已发布的题，且每题都有选项（否则 start 409"题库不完整"）。
    发布候选数据不迎合路由：路由按任务真实可启动性生成。
    """
    out: list[Any] = []
    for task in tasks:
        sim_code = _simulation_scenario_code(task)
        if sim_code is not None:
            if sim_code in scenario_codes:
                out.append(task)
            continue
        questions = [
            q
            for q in (getattr(task, "questions", None) or [])
            if getattr(q, "active", True) and str(getattr(q, "status", "") or "") == "published"
        ]
        if questions and all(getattr(q, "options", None) for q in questions):
            out.append(task)
    return out


def summarize_evidence(
    items: list[tuple[float, str, dict[str, Any]]],
    *,
    trend_window: int = 2,
    trend_delta: float = 5.0,
    low_score: float = 60.0,
    recent_op_low_count: int = 2,
) -> dict[str, Any]:
    """把某能力维度的证据时间线（旧→新）汇总为确定性规则信号（纯函数）。

    返回：
    - count / types：证据条数与来源类型集合；
    - recent_avg：最近 trend_window 条表现分平均（None = 无证据）；
    - trend：insufficient | improving | stable | declining（近段 vs 前段平均）；
    - recent_low_ops：末尾连续低分的操作/诊断证据条数（非操作证据不打断也不累计）；
    - last_scenario_code：最近一条带 scenario_code 元数据的场景编码（重练入口）。
    """
    scores = [float(score) for score, _, _ in items]
    types = {source for _, source, _ in items}
    recent_avg = round(sum(scores[-trend_window:]) / min(trend_window, len(scores)), 1) if scores else None

    trend = "insufficient"
    if len(scores) >= trend_window * 2:
        recent = scores[-trend_window:]
        prior = scores[-trend_window * 2 : -trend_window]
        recent_mean = sum(recent) / len(recent)
        prior_mean = sum(prior) / len(prior)
        if recent_mean - prior_mean > trend_delta:
            trend = "improving"
        elif prior_mean - recent_mean > trend_delta:
            trend = "declining"
        else:
            trend = "stable"

    low_ops = 0
    last_scenario: str | None = None
    for score, source, meta in reversed(items):
        if last_scenario is None and meta.get("scenario_code"):
            last_scenario = str(meta["scenario_code"])
        if source not in OPERATIONAL_SOURCES:
            continue
        if float(score) < low_score:
            low_ops += 1
        else:
            break
    return {
        "count": len(items),
        "types": sorted(types),
        "recent_avg": recent_avg,
        "trend": trend,
        "recent_low_ops": min(low_ops, recent_op_low_count) if low_ops >= recent_op_low_count else low_ops,
        "meets_recent_op_low": low_ops >= recent_op_low_count,
        "last_scenario_code": last_scenario,
    }


def plan_evidence_chain(
    *,
    ability_key: str,
    ability_name: str,
    score: float,
    confidence: str,
    evidence: dict[str, Any],
    tasks: list[TrainingTask],
    available_scenario_codes: set[str] | None = None,
) -> list[dict[str, Any]] | None:
    """§43 证据优先链（纯规则，不经过模型）。

    触发条件（三条同时满足）：能力分低于薄弱阈值、证据置信度 ≥ medium、
    最近连续操作/诊断证据低分达到配置条数。不满足返回 None。
    满足则产出：相关知识点补学 → 案例学习 → 低一级难度训练 → 原仿真场景重练。

    R045：训练步骤按任务真实类型路由（仿真→/simulation，选择题→/training）；
    available_scenario_codes 提供时，重练目标场景不可加载则不生成该步骤。
    """
    settings = get_settings()
    if score >= settings.adaptive_weak_threshold:
        return None
    if confidence not in {"medium", "high"}:
        return None
    if not evidence.get("meets_recent_op_low"):
        return None

    safety_critical = ability_key == "safety_awareness"
    matched = [task for task in tasks if ability_key in (task.target_abilities or [])]
    knowledge_point = "综合知识"
    if matched:
        points = [p for task in matched for p in (task.knowledge_points or []) if p]
        if points:
            knowledge_point = points[0]
    reason_stats = (
        f"最近操作/诊断证据连续 {settings.adaptive_recent_op_low_count}+ 条低于 "
        f"{settings.adaptive_evidence_low_score:.0f} 分（近段平均 {evidence.get('recent_avg')}），"
        f"置信度 {confidence}，按证据优先链补强。"
    )
    chain: list[dict[str, Any]] = [
        {
            "step_type": "knowledge_review",
            "title": f"补学：{knowledge_point}",
            "reason": f"针对「{ability_name}」的证据缺口先补基础知识。{reason_stats}",
            "priority": "证据优先补强",
            "knowledge_point": knowledge_point,
            "target_ability": ability_key,
            "difficulty": 1,
            "estimated_minutes": 10,
            "route": f"/knowledge?query={knowledge_point}",
            "safety_critical": safety_critical,
            "evidence_driven": True,
        },
        {
            "step_type": "case_learning",
            "title": f"案例学习：{ability_name}典型处置案例",
            "reason": f"通过站场案例建立「{ability_name}」的情境判断参照。{reason_stats}",
            "priority": "证据优先补强",
            "knowledge_point": knowledge_point,
            "target_ability": ability_key,
            "difficulty": 1,
            "estimated_minutes": 15,
            "route": f"/knowledge?query={ability_name} 案例",
            "safety_critical": safety_critical,
            "evidence_driven": True,
        },
    ]
    if matched:
        # 低一级难度训练：薄弱分越低目标难度越低（<30 → 1，<60 → 2）
        target_difficulty = 1 if score < 30 else 2
        task = min(matched, key=lambda t: (abs(t.difficulty - target_difficulty), t.id))
        activity_type, activity_route = _task_activity(task)
        chain.append(
            {
                "step_type": "training_retry",
                "title": f"降档训练：{task.title}",
                "reason": f"以难度 {task.difficulty} 的同能力任务巩固后再回原难度。{reason_stats}",
                "priority": "证据优先补强",
                "knowledge_point": knowledge_point,
                "target_ability": ability_key,
                "task_id": task.id,
                "task_code": task.code,
                "activity_type": activity_type,
                "difficulty": task.difficulty,
                "estimated_minutes": task.estimated_minutes,
                "route": activity_route,
                "safety_critical": safety_critical,
                "evidence_driven": True,
            }
        )
    scenario_code = evidence.get("last_scenario_code")
    if scenario_code and (
        available_scenario_codes is None or str(scenario_code) in available_scenario_codes
    ):
        chain.append(
            {
                "step_type": "simulation_retry",
                "title": "重练：岗位仿真实训（原场景）",
                "reason": f"回到产生低分证据的仿真实训「{scenario_code}」重做，验证补学效果。",
                "priority": "证据优先补强",
                "knowledge_point": knowledge_point,
                "target_ability": ability_key,
                "difficulty": 2,
                "estimated_minutes": 20,
                "route": f"/simulation/{scenario_code}",
                "safety_critical": safety_critical,
                "evidence_driven": True,
            }
        )
    return chain


class AdaptiveLearningService:
    """学生层闭环；不产生或修改专业培养方案。"""

    async def build_path(self, db: AsyncSession, student_id: int) -> dict[str, Any]:
        settings = get_settings()
        answer_rows = list(
            (
                await db.execute(
                    select(TrainingChoiceAnswer, TrainingQuestion)
                    .join(TrainingQuestion, TrainingQuestion.id == TrainingChoiceAnswer.question_id)
                    .join(TrainingSession, TrainingSession.id == TrainingChoiceAnswer.session_id)
                    .where(
                        TrainingSession.student_id == student_id,
                        TrainingSession.finished == True,  # noqa: E712
                    )
                    .order_by(TrainingChoiceAnswer.created_at, TrainingChoiceAnswer.id)
                )
            ).all()
        )
        abilities = (await db.execute(select(Ability).order_by(Ability.id))).scalars().all()
        score_rows = (
            await db.execute(select(AbilityScore).where(AbilityScore.student_id == student_id))
        ).scalars().all()
        score_map = {item.ability_id: item for item in score_rows}

        # §41 统一证据层：最近 N 条证据按能力分组（时间正序）
        evidence_rows = list(
            (
                await db.execute(
                    select(AbilityEvidence)
                    .where(AbilityEvidence.student_id == student_id)
                    .order_by(AbilityEvidence.created_at.desc(), AbilityEvidence.id.desc())
                    .limit(settings.adaptive_evidence_limit)
                )
            ).scalars().all()
        )
        evidence_items: defaultdict[str, list[tuple[float, str, dict[str, Any]]]] = defaultdict(list)
        for row in reversed(evidence_rows):  # 还原为旧→新
            evidence_items[row.ability_key].append(
                (float(row.final_score), str(row.source_type), row.metadata_json or {})
            )
        evidence_state = {
            key: summarize_evidence(
                items,
                trend_window=settings.adaptive_trend_window,
                trend_delta=settings.adaptive_trend_delta,
                low_score=settings.adaptive_evidence_low_score,
                recent_op_low_count=settings.adaptive_recent_op_low_count,
            )
            for key, items in evidence_items.items()
        }
        ability_name_map = {item.key: item.name for item in abilities}

        ability_state = [
            {
                "key": ability.key,
                "name": ability.name,
                "score": round(score_map.get(ability.id).score, 1) if ability.id in score_map else 0,
                "attempt_count": score_map.get(ability.id).attempt_count if ability.id in score_map else 0,
                "state": self._state(round(score_map.get(ability.id).score, 1) if ability.id in score_map else 0),
                # P0-1/P0-5：置信度与证据汇总（来自画像与统一证据表）
                "confidence": score_map[ability.id].confidence if ability.id in score_map else "low",
                "evidence_count": score_map[ability.id].evidence_count if ability.id in score_map else 0,
                "growth_xp": score_map[ability.id].growth_xp if ability.id in score_map else 0,
                "trend": evidence_state.get(ability.key, {}).get("trend", "insufficient"),
                "recent_avg": evidence_state.get(ability.key, {}).get("recent_avg"),
            }
            for ability in abilities
        ]

        grouped: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
        for answer, question in answer_rows:
            point = (question.knowledge_point or "综合知识").strip()
            normalized = max(0.0, min(100.0, answer.score / max(1, question.max_score) * 100))
            grouped[(point, question.ability_key or "")].append(normalized)

        mastery_items: list[dict[str, Any]] = []
        for (point, ability_key), values in grouped.items():
            # 越近的作答权重越高，路径会随最新实训结果动态调整。
            weights = [0.85 ** (len(values) - index - 1) for index in range(len(values))]
            score = sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)
            recent = values[-settings.adaptive_recent_answer_window :]
            # §44 安全优先（阈值入配置）：近期安全类低分，或安全操作证据连续低分
            critical = ability_key == "safety_awareness" and any(
                value < settings.adaptive_safety_score_floor for value in recent
            )
            if ability_key == "safety_awareness" and evidence_state.get(ability_key, {}).get("meets_recent_op_low"):
                critical = True
            if critical:
                score = min(score, 59.0)
            evidence_info = evidence_state.get(ability_key, {})
            mastery_items.append({
                "knowledge_point": point,
                "ability_key": ability_key,
                "ability_name": ability_name_map.get(ability_key, ability_key or "综合能力"),
                "mastery_score": round(score, 1),
                "attempt_count": len(values),
                "wrong_count": sum(value < 60 for value in values),
                "recent_scores": [round(value, 1) for value in recent],
                "safety_critical": critical,
                "state": self._state(score),
                # P0-5：该知识点所属能力维度的证据信号（§42）
                "evidence_confidence": score_map_confidence(score_map, abilities, ability_key),
                "evidence_trend": evidence_info.get("trend", "insufficient"),
                "recent_low_ops": evidence_info.get("recent_low_ops", 0),
            })
        mastery_items.sort(key=lambda item: (not item["safety_critical"], item["mastery_score"], -item["attempt_count"]))

        tasks = (
            await db.execute(
                select(TrainingTask)
                .options(
                    selectinload(TrainingTask.questions).selectinload(TrainingQuestion.options)
                )
                .where(TrainingTask.status == TaskStatus.published)
                .order_by(TrainingTask.difficulty, TrainingTask.id)
            )
        ).scalars().all()
        # R045：推荐步骤只指向真实可启动的活动（仿真场景可加载 / 选择题题库完整）
        scenario_codes = set(load_scenarios().keys())
        launchable = _launchable_tasks(list(tasks), scenario_codes)
        steps: list[dict[str, Any]] = []

        # §43 证据驱动链（安全维度排序在前），置于知识点步骤之前
        score_by_key = {item["key"]: item["score"] for item in ability_state}
        confidence_by_key = {item["key"]: item["confidence"] for item in ability_state}
        chain_abilities = sorted(
            evidence_state,
            key=lambda key: (key != "safety_awareness", score_by_key.get(key, 0.0)),
        )
        max_steps = settings.adaptive_recent_answer_window * 4  # 12：证据链 + 知识点补学总预算
        step_seq = 0
        for ability_key in chain_abilities:
            chain = plan_evidence_chain(
                ability_key=ability_key,
                ability_name=ability_name_map.get(ability_key, ability_key),
                score=float(score_by_key.get(ability_key, 0.0)),
                confidence=str(confidence_by_key.get(ability_key, "low")),
                evidence=evidence_state[ability_key],
                tasks=launchable,
                available_scenario_codes=scenario_codes,
            )
            if not chain:
                continue
            for step in chain:
                if len(steps) >= max_steps:
                    break
                step_seq += 1
                steps.append({"id": f"step-{step_seq}", **step})

        for mastery in mastery_items:
            if mastery["mastery_score"] >= 80 or len(steps) >= max_steps:
                continue
            priority = "必须先修" if mastery["safety_critical"] else "优先补强" if mastery["mastery_score"] < 60 else "巩固提升"
            step_seq += 1
            steps.append({
                "id": f"knowledge-{step_seq}",
                "step_type": "knowledge_review",
                "title": f"补学：{mastery['knowledge_point']}",
                "reason": f"该知识点当前掌握度 {mastery['mastery_score']}%，最近实训错答 {mastery['wrong_count']} 次。",
                "priority": priority,
                "knowledge_point": mastery["knowledge_point"],
                "target_ability": mastery["ability_key"],
                "difficulty": 1 if mastery["mastery_score"] < 40 else 2,
                "estimated_minutes": 10,
                "route": f"/knowledge?query={mastery['knowledge_point']}",
                "safety_critical": mastery["safety_critical"],
            })
            candidates = [
                task for task in launchable
                if mastery["knowledge_point"] in (task.knowledge_points or [])
                or mastery["ability_key"] in (task.target_abilities or [])
            ]
            if candidates and len(steps) < max_steps:
                target_difficulty = 1 if mastery["mastery_score"] < 30 else 2 if mastery["mastery_score"] < 60 else 3
                candidates.sort(key=lambda item: (abs(item.difficulty - target_difficulty), item.id))
                task = candidates[0]
                activity_type, activity_route = _task_activity(task)
                step_seq += 1
                steps.append({
                    "id": f"practice-{step_seq}",
                    "step_type": "training_retry",
                    "title": f"重练：{task.title}",
                    "reason": f"用于验证「{mastery['knowledge_point']}」补学效果；完成后系统将重新计算掌握度。",
                    "priority": priority,
                    "knowledge_point": mastery["knowledge_point"],
                    "target_ability": mastery["ability_key"],
                    "task_id": task.id,
                    "task_code": task.code,
                    "activity_type": activity_type,
                    "difficulty": task.difficulty,
                    "estimated_minutes": task.estimated_minutes,
                    "route": activity_route,
                    "safety_critical": mastery["safety_critical"],
                })

        if not answer_rows and not evidence_rows:
            for task in launchable[:3]:
                activity_type, activity_route = _task_activity(task)
                steps.append({
                    "id": f"diagnostic-{len(steps) + 1}",
                    "step_type": "diagnostic_training",
                    "title": f"诊断训练：{task.title}",
                    "reason": "尚无训练或仿真证据，先通过诊断任务建立个人能力与知识掌握基线。",
                    "priority": "建立基线",
                    "knowledge_point": (task.knowledge_points or ["综合知识"])[0],
                    "target_ability": (task.target_abilities or [""])[0],
                    "task_id": task.id,
                    "task_code": task.code,
                    "activity_type": activity_type,
                    "difficulty": task.difficulty,
                    "estimated_minutes": task.estimated_minutes,
                    "route": activity_route,
                    "safety_critical": False,
                })

        # §44 高难度前置提醒：安全未达标时，难度 ≥ gate 的步骤标记安全门禁
        safety_score = float(score_by_key.get("safety_awareness", 0.0))
        safety_alert: dict[str, Any] | None = None
        if evidence_rows and safety_score < settings.adaptive_safety_score_floor:
            safety_alert = {
                "safety_score": round(safety_score, 1),
                "floor": settings.adaptive_safety_score_floor,
                "message": (
                    f"安全意识当前 {safety_score:.0f} 分（低于 {settings.adaptive_safety_score_floor:.0f}）："
                    "请先完成安全类补学，再进入更高难度实训。"
                ),
            }
            for step in steps:
                if step["difficulty"] >= settings.adaptive_safety_gate_difficulty and not step["safety_critical"]:
                    step["safety_gate_warning"] = True

        weak_count = sum(item["mastery_score"] < 60 for item in mastery_items)
        learning_count = sum(60 <= item["mastery_score"] < 80 for item in mastery_items)
        mastered_count = sum(item["mastery_score"] >= 80 for item in mastery_items)
        overall = round(sum(item["mastery_score"] for item in mastery_items) / len(mastery_items), 1) if mastery_items else 0
        return {
            "student_id": student_id,
            "data_boundary": (
                "仅根据该学生的统一能力证据（知识答题/情境选择/操作仿真/教师评价）"
                "和个人能力画像生成，不影响专业培养方案。"
            ),
            "summary": {
                "overall_mastery": overall,
                "knowledge_count": len(mastery_items),
                "weak_count": weak_count,
                "learning_count": learning_count,
                "mastered_count": mastered_count,
                "completed_answer_count": len(answer_rows),
                "path_step_count": len(steps),
                "evidence_count": len(evidence_rows),
                "evidence_driven_steps": sum(1 for step in steps if step.get("evidence_driven")),
            },
            "ability_state": ability_state,
            "knowledge_mastery": mastery_items,
            "learning_path": steps,
            "next_step": steps[0] if steps else None,
            "safety_alert": safety_alert,
            "refresh_rule": (
                "每次实训/仿真实训完成后实时重算：统一证据链 + 知识点掌握度双通道，"
                "近期表现权重更高，安全类低分强制优先（阈值集中于配置，规则不经模型）。"
            ),
        }

    @staticmethod
    def _state(score: float) -> str:
        if score >= 80:
            return "mastered"
        if score >= 60:
            return "learning"
        return "weak"


def score_map_confidence(
    score_map: dict[int, AbilityScore], abilities: list[Ability], ability_key: str
) -> str:
    """按能力键查画像置信度（无记录 → low）。"""
    for ability in abilities:
        if ability.key == ability_key:
            obj = score_map.get(ability.id)
            return obj.confidence if obj else "low"
    return "low"


__all__ = [
    "AdaptiveLearningService",
    "OPERATIONAL_SOURCES",
    "plan_evidence_chain",
    "summarize_evidence",
]
