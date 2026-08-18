"""依据公开招聘证据生成并发布岗位能力图谱草稿。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ABILITY_CN, AbilityKey, TaskStatus
from app.llm import get_gateway
from app.llm.base import LLMMessage
from app.models.position import (
    Ability,
    JobTask,
    KnowledgePoint,
    Position,
    PositionAbilityRelation,
    SkillPoint,
    TaskAbilityRelation,
)
from app.models.position_market import JobPostingSnapshot, PositionAnalysisRun
from app.models.training import TrainingTask
from app.services.prompt_templates import get_prompt_messages

ABILITY_KEYS = [key.value for key in AbilityKey]


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _normalize_weights(raw: Any) -> dict[str, float]:
    source = raw if isinstance(raw, dict) else {}
    values: dict[str, float] = {}
    for key in ABILITY_KEYS:
        try:
            values[key] = max(0.0, float(source.get(key, 0.0)))
        except (TypeError, ValueError):
            values[key] = 0.0
    total = sum(values.values())
    if total <= 0:
        equal = 1.0 / len(ABILITY_KEYS)
        return {key: equal for key in ABILITY_KEYS}
    normalized = {key: value / total for key, value in values.items()}
    # 将浮点余差落到最大权重，保证规则校验严格等于 1。
    largest = max(normalized, key=normalized.get)  # type: ignore[arg-type]
    normalized[largest] += 1.0 - sum(normalized.values())
    return {key: round(value, 6) for key, value in normalized.items()}


def normalize_graph_draft(
    raw: dict[str, Any],
    *,
    position_code: str,
    position_name: str,
) -> dict[str, Any]:
    tasks_raw = (
        raw.get("tasks")
        or raw.get("job_tasks")
        or raw.get("items")
        or []
    ) if isinstance(raw, dict) else []
    tasks: list[dict[str, Any]] = []
    for index, item in enumerate(tasks_raw[:12], 1):
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 128)
        if not name:
            continue
        weights = _normalize_weights(item.get("ability_weights"))
        points: list[dict[str, Any]] = []
        for point_index, point in enumerate(item.get("knowledge_points", [])[:8], 1):
            if isinstance(point, str):
                point = {"name": point}
            if not isinstance(point, dict):
                continue
            point_name = _text(point.get("name"), 128)
            if not point_name:
                continue
            ability_key = str(point.get("ability_key") or "")
            if ability_key not in ABILITY_KEYS:
                ability_key = max(weights, key=weights.get)  # type: ignore[arg-type]
            skills = [
                _text(skill, 128)
                for skill in point.get("skills", [])[:8]
                if _text(skill, 128)
            ]
            points.append(
                {
                    "code": f"{position_code}-T{index:02d}-K{point_index:02d}",
                    "name": point_name,
                    "description": _text(point.get("description"), 512),
                    "ability_key": ability_key,
                    "skills": list(dict.fromkeys(skills)),
                }
            )
        if not points:
            top_key = max(weights, key=weights.get)  # type: ignore[arg-type]
            points.append(
                {
                    "code": f"{position_code}-T{index:02d}-K01",
                    "name": f"{name}知识要点",
                    "description": "依据招聘岗位职责形成的待教师审核知识要点。",
                    "ability_key": top_key,
                    "skills": [f"{name}任务分析"],
                }
            )
        tasks.append(
            {
                "code": f"{position_code}-T{index:02d}",
                "name": name,
                "description": _text(item.get("description"), 512),
                "ability_weights": weights,
                "knowledge_points": points,
                "source_refs": [
                    int(value)
                    for value in item.get("source_refs", [])[:20]
                    if str(value).isdigit()
                ],
            }
        )

    if len(tasks) < 3:
        fallback_names = ["岗位职责认知", "运行信息识别", "安全规范与记录"]
        while len(tasks) < 3:
            index = len(tasks) + 1
            name = fallback_names[index - 1]
            weights = _normalize_weights({ABILITY_KEYS[index - 1]: 1})
            tasks.append(
                {
                    "code": f"{position_code}-T{index:02d}",
                    "name": name,
                    "description": f"围绕{position_name}形成的待教师审核典型任务。",
                    "ability_weights": weights,
                    "knowledge_points": [
                        {
                            "code": f"{position_code}-T{index:02d}-K01",
                            "name": f"{name}知识要点",
                            "description": "依据岗位资料形成的候选知识点。",
                            "ability_key": ABILITY_KEYS[index - 1],
                            "skills": [f"{name}分析"],
                        }
                    ],
                    "source_refs": [],
                }
            )

    overall_raw = raw.get("ability_weights") if isinstance(raw, dict) else None
    if not isinstance(overall_raw, dict):
        overall_raw = {
            key: sum(task["ability_weights"][key] for task in tasks) / len(tasks)
            for key in ABILITY_KEYS
        }
    return {
        "position_summary": _text(
            raw.get("position_summary") if isinstance(raw, dict) else "",
            1000,
        ) or f"{position_name}岗位能力图谱候选草稿。",
        "ability_weights": _normalize_weights(overall_raw),
        "tasks": tasks,
        "demand_skills": list(
            dict.fromkeys(
                _text(item, 128)
                for item in (raw.get("demand_skills", []) if isinstance(raw, dict) else [])[:20]
                if _text(item, 128)
            )
        ),
        "review_note": "AI仅生成候选结构，必须由教师审核后发布。",
    }


class PositionGraphAnalysisService:
    async def generate(
        self,
        *,
        position: Position,
        snapshots: list[JobPostingSnapshot],
    ) -> tuple[dict[str, Any], str, float]:
        evidence = []
        for snapshot in snapshots[:20]:
            evidence.append(
                {
                    "id": snapshot.id,
                    "title": snapshot.title,
                    "source": snapshot.source_name,
                    "url": snapshot.source_url,
                    "published_at": snapshot.published_at.isoformat() if snapshot.published_at else "",
                    "skills": snapshot.skills or [],
                    "text": _text(snapshot.content or snapshot.snippet, 1800),
                }
            )
        if not evidence:
            raise ValueError("尚未发现可用招聘证据，请先执行AI寻找岗位数据")

        ability_schema = {key.value: ABILITY_CN[key] for key in AbilityKey}
        output_contract = {
            "position_summary": "岗位摘要",
            "ability_weights": {key: 0.0 for key in ABILITY_KEYS},
            "tasks": [
                {
                    "name": "典型工作任务名称",
                    "description": "任务说明",
                    "ability_weights": {key: 0.0 for key in ABILITY_KEYS},
                    "knowledge_points": [
                        {
                            "name": "知识点",
                            "description": "知识说明",
                            "ability_key": "equipment_recognition",
                            "skills": ["技能点"],
                        }
                    ],
                    "source_refs": [evidence[0]["id"]],
                }
            ],
            "demand_skills": ["招聘样本中的技能"],
        }
        system_prompt, prompt = await get_prompt_messages(
            "position_graph_analysis",
            {
                "major": position.major,
                "position_name": position.name,
                "aliases": position.aliases or [],
                "description": position.description,
                "ability_schema": ability_schema,
                "evidence": evidence,
                "output_contract": output_contract,
            },
        )
        result = await get_gateway().chat_structured(
            [
                LLMMessage.system(system_prompt),
                LLMMessage.user(prompt),
            ],
            schema_description=(
                '{"position_summary":"摘要","ability_weights":{"process_understanding":0.2,'
                '"equipment_recognition":0.2,"instrument_parameter":0.15,'
                '"abnormal_detection":0.15,"safety_awareness":0.2,'
                '"standard_recording":0.1},"tasks":[{"name":"任务",'
                '"description":"说明","ability_weights":{"六维key":0.2},'
                '"knowledge_points":[{"name":"知识点","description":"说明",'
                '"ability_key":"六维key","skills":["技能"]}],"source_refs":[1]}],'
                '"demand_skills":["技能"]}'
            ),
            temperature=0.15,
            max_tokens=7000,
            timeout=90,
        )
        if not result.success or not result.data:
            raise ValueError(f"岗位图谱结构化分析失败：{result.error or '模型未返回有效JSON'}")
        raw_tasks = (
            result.data.get("tasks")
            or result.data.get("job_tasks")
            or result.data.get("items")
            or []
        )
        if not isinstance(raw_tasks, list) or len(raw_tasks) < 3:
            raise ValueError("模型未返回至少3个可审核的典型工作任务，请重新分析")
        draft = normalize_graph_draft(
            result.data,
            position_code=position.code,
            position_name=position.name,
        )
        source_count = len({snapshot.source_name for snapshot in snapshots})
        confidence = min(0.95, 0.4 + min(len(snapshots), 20) * 0.02 + min(source_count, 5) * 0.03)
        return draft, result.provider, round(confidence, 3)

    async def publish(
        self,
        *,
        session: AsyncSession,
        position: Position,
        analysis: PositionAnalysisRun,
        reviewer_id: int,
    ) -> dict[str, int]:
        draft = normalize_graph_draft(
            analysis.result_json or {},
            position_code=position.code,
            position_name=position.name,
        )
        abilities = (await session.scalars(select(Ability).order_by(Ability.id))).all()
        ability_by_key = {ability.key: ability for ability in abilities}
        missing = [key for key in ABILITY_KEYS if key not in ability_by_key]
        if missing:
            raise ValueError(f"系统六维能力数据不完整：{missing}")

        task_ids = list(
            await session.scalars(select(JobTask.id).where(JobTask.position_id == position.id))
        )
        if task_ids:
            point_ids = list(
                await session.scalars(
                    select(KnowledgePoint.id).where(KnowledgePoint.job_task_id.in_(task_ids))
                )
            )
            await session.execute(
                delete(TaskAbilityRelation).where(TaskAbilityRelation.job_task_id.in_(task_ids))
            )
            if point_ids:
                await session.execute(delete(SkillPoint).where(SkillPoint.knowledge_point_id.in_(point_ids)))
                await session.execute(delete(KnowledgePoint).where(KnowledgePoint.id.in_(point_ids)))
            await session.execute(delete(JobTask).where(JobTask.id.in_(task_ids)))
        await session.execute(
            delete(PositionAbilityRelation).where(PositionAbilityRelation.position_id == position.id)
        )

        for key, weight in draft["ability_weights"].items():
            session.add(
                PositionAbilityRelation(
                    position_id=position.id,
                    ability_id=ability_by_key[key].id,
                    weight=weight,
                )
            )

        created_tasks = 0
        created_points = 0
        created_skills = 0
        for order, task_data in enumerate(draft["tasks"], 1):
            task = JobTask(
                position_id=position.id,
                code=task_data["code"],
                name=task_data["name"],
                description=task_data["description"],
                sort_order=order,
            )
            session.add(task)
            await session.flush()
            created_tasks += 1
            for key, weight in task_data["ability_weights"].items():
                session.add(
                    TaskAbilityRelation(
                        job_task_id=task.id,
                        ability_id=ability_by_key[key].id,
                        weight=weight,
                    )
                )
            point_names: list[str] = []
            for point_data in task_data["knowledge_points"]:
                point = KnowledgePoint(
                    ability_id=ability_by_key[point_data["ability_key"]].id,
                    job_task_id=task.id,
                    code=point_data["code"],
                    name=point_data["name"],
                    description=point_data["description"],
                )
                session.add(point)
                await session.flush()
                created_points += 1
                point_names.append(point.name)
                for skill_index, skill_name in enumerate(point_data["skills"], 1):
                    session.add(
                        SkillPoint(
                            knowledge_point_id=point.id,
                            code=f"{point.code}-S{skill_index:02d}",
                            name=skill_name,
                            description=f"由{point.name}形成的岗位技能候选项。",
                        )
                    )
                    created_skills += 1

            training_code = f"AI-{position.code}-{task.code}"[:64]
            training = (
                await session.scalars(select(TrainingTask).where(TrainingTask.code == training_code))
            ).one_or_none()
            target_abilities = [
                key for key, weight in task_data["ability_weights"].items() if weight > 0
            ]
            if training is None:
                training = TrainingTask(
                    position_id=position.id,
                    job_task_id=task.id,
                    code=training_code,
                    title=f"{position.name} · {task.name}",
                    description=task.description,
                    difficulty=2,
                    target_abilities=target_abilities,
                    knowledge_points=point_names,
                    required_points=point_names,
                    reference_points=[],
                    scenario={
                        "scenario_text": f"【教学模拟】围绕“{task.name}”完成岗位情境判断。",
                        "position_name": position.name,
                        "job_task_name": task.name,
                    },
                    max_follow_ups=3,
                    estimated_minutes=15,
                    status=TaskStatus.draft,
                )
                session.add(training)
            else:
                training.position_id = position.id
                training.job_task_id = task.id
                training.title = f"{position.name} · {task.name}"
                training.description = task.description
                training.target_abilities = target_abilities
                training.knowledge_points = point_names
                training.required_points = point_names

        now = datetime.now(UTC)
        position.status = "published"
        position.graph_version = analysis.version
        position.source_summary = draft["position_summary"]
        position.published_at = now
        analysis.status = "published"
        analysis.reviewed_by = reviewer_id
        analysis.reviewed_at = now
        analysis.published_at = now
        analysis.result_json = draft
        await session.commit()
        return {
            "tasks": created_tasks,
            "knowledge_points": created_points,
            "skill_points": created_skills,
        }


__all__ = [
    "ABILITY_KEYS",
    "PositionGraphAnalysisService",
    "normalize_graph_draft",
]
