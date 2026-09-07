"""数据种子：用户、岗位能力图谱、训练任务和可追溯公开证据。

业务场景与学生数据为教学模拟/脱敏数据；标注为公开证据的数据来自可核验公开页面。
幂等：已存在则跳过。

用法：
    python -m app.seed            # 仅种子数据
    python -m app.seed --reset    # 清空后重新种子（仅开发环境）
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import ABILITY_CN, AbilityKey, TaskStatus
from app.core.logging import logger, setup_logging
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, Base, engine
from app.evidence.catalog import load_verified_public_evidence
from app.knowledge.catalog import load_authoritative_knowledge
from app.models import (
    Ability,
    AbilityEvidence,
    AbilityHistory,
    AbilityScore,
    AdminAuditLog,
    ChatMessage,
    ChatSession,
    CurriculumCourse,
    CurriculumProgram,
    ErrorRecord,
    EvaluationResult,
    FeatureConfig,
    IndustryEvidence,
    JobPostingSnapshot,
    JobTask,
    KnowledgeChunk,
    KnowledgeEvidenceRelation,
    KnowledgeItem,
    KnowledgePoint,
    LearningRecommendation,
    Major,
    Position,
    PositionAbilityRelation,
    PositionAnalysisRun,
    PositionDiscoveryRun,
    ProfessionalGroup,
    ProgramAdjustmentProposal,
    SkillPoint,
    StudentAnswer,
    TaskAbilityRelation,
    TeachingPlan,
    TrainingActionEvent,
    TrainingChoiceAnswer,
    TrainingOption,
    TrainingQuestion,
    TrainingScenario,
    TrainingSession,
    TrainingTask,
    User,
    WorkflowExecutionLog,
    WorkflowInstance,
)

settings = get_settings()

VERIFIED_EVIDENCE_RUN_MARKER = "seed:verified-public-evidence:2026-08-13-v1"


def _upgrade_legacy_schema(sync_connection: Connection) -> None:
    """为早期开发库补齐已上线模型列，不删除或重建任何业务表。"""
    inspector = inspect(sync_connection)
    if "knowledge_items" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("knowledge_items")}
    additions = {
        "file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "file_type": "VARCHAR(16) NOT NULL DEFAULT ''",
        "file_size": "BIGINT NOT NULL DEFAULT 0",
        "file_hash": "VARCHAR(64)",
        "file_path": "VARCHAR(500) NOT NULL DEFAULT ''",
    }
    for column, definition in additions.items():
        if column not in existing:
            sync_connection.execute(text(f"ALTER TABLE knowledge_items ADD COLUMN {column} {definition}"))
            logger.info("兼容升级：knowledge_items.{} 已补齐", column)
    if "knowledge_chunks" in inspector.get_table_names():
        chunk_existing = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
        chunk_additions = {
            "heading_path": "VARCHAR(512) NOT NULL DEFAULT ''",
            "chunk_type": "VARCHAR(16) NOT NULL DEFAULT 'text'",
        }
        for column, definition in chunk_additions.items():
            if column not in chunk_existing:
                sync_connection.execute(
                    text(f"ALTER TABLE knowledge_chunks ADD COLUMN {column} {definition}")
                )
                logger.info("兼容升级：knowledge_chunks.{} 已补齐", column)
    if "ability_scores" in inspector.get_table_names():
        ability_existing = {column["name"] for column in inspector.get_columns("ability_scores")}
        ability_additions = {
            "growth_xp": "INTEGER NOT NULL DEFAULT 0",
            "confidence": "VARCHAR(8) NOT NULL DEFAULT 'low'",
            "evidence_count": "INTEGER NOT NULL DEFAULT 0",
            "evidence_type_count": "INTEGER NOT NULL DEFAULT 0",
            "last_evaluated_at": "DATETIME",
        }
        for column, definition in ability_additions.items():
            if column not in ability_existing:
                sync_connection.execute(
                    text(f"ALTER TABLE ability_scores ADD COLUMN {column} {definition}")
                )
                logger.info("兼容升级：ability_scores.{} 已补齐", column)


    if "positions" in inspector.get_table_names():
        pos_existing = {column["name"] for column in inspector.get_columns("positions")}
        pos_additions = {
            "aliases": "JSON NOT NULL DEFAULT '[]'",
            "status": "VARCHAR(24) NOT NULL DEFAULT 'published'",
            "source_summary": "TEXT NOT NULL DEFAULT ''",
            "graph_version": "INTEGER NOT NULL DEFAULT 1",
            "created_by": "INTEGER",
            "published_at": "DATETIME",
        }
        for column, definition in pos_additions.items():
            if column not in pos_existing:
                sync_connection.execute(
                    text(f"ALTER TABLE positions ADD COLUMN {column} {definition}")
                )
                logger.info("兼容升级：positions.{} 已补齐", column)
    if "training_tasks" in inspector.get_table_names():
        tasks_existing = {column["name"] for column in inspector.get_columns("training_tasks")}
        tasks_additions = {
            "position_id": "INTEGER",
            "job_task_id": "INTEGER",
        }
        for column, definition in tasks_additions.items():
            if column not in tasks_existing:
                sync_connection.execute(
                    text(f"ALTER TABLE training_tasks ADD COLUMN {column} {definition}")
                )
                logger.info("兼容升级：training_tasks.{} 已补齐", column)
    if "training_sessions" in inspector.get_table_names():
        sess_existing = {column["name"] for column in inspector.get_columns("training_sessions")}
        if "scenario_code" not in sess_existing:
            sync_connection.execute(
                text("ALTER TABLE training_sessions ADD COLUMN scenario_code VARCHAR(64) NOT NULL DEFAULT ''")
            )
            logger.info("兼容升级：training_sessions.scenario_code 已补齐")
    # P0-3 专业群兼容列（新表 professional_groups/majors 由 create_all 兜底建出）
    for table in ("curriculum_programs", "positions"):
        if table in inspector.get_table_names():
            cols = {column["name"] for column in inspector.get_columns(table)}
            if "major_id" not in cols:
                sync_connection.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN major_id INTEGER")
                )
                logger.info("兼容升级：{}.major_id 已补齐", table)


# ===== 六维能力默认权重（与 config 一致，但权重必须存库，禁止散落硬编码） =====
ABILITY_WEIGHTS: dict[AbilityKey, float] = {
    AbilityKey.process_understanding: settings.ability_weight_process,
    AbilityKey.equipment_recognition: settings.ability_weight_equipment,
    AbilityKey.instrument_parameter: settings.ability_weight_instrument,
    AbilityKey.abnormal_detection: settings.ability_weight_abnormal,
    AbilityKey.safety_awareness: settings.ability_weight_safety,
    AbilityKey.standard_recording: settings.ability_weight_recording,
}


# ===== 13 个典型工作任务（第十一节） =====
JOB_TASKS = [
    ("T01", "站场工艺流程识读", "识读输气站工艺流程，理解各功能区作用与介质流向。"),
    ("T02", "日常巡检", "按巡检路线对站场设备、管阀、仪表进行日常检查。"),
    ("T03", "阀门及管件状态检查", "识别阀门类型与状态，检查管件连接与密封。"),
    ("T04", "泵等设备状态认知", "认知泵类设备结构、运行参数与常见状态。"),
    ("T05", "压缩机等设备状态认知", "认知压缩机组结构、运行参数与状态判读。"),
    ("T06", "仪表参数读取", "正确读取压力、温度、流量、液位等仪表参数。"),
    ("T07", "工艺异常信息识别", "识别工艺参数偏离、设备异常与趋势变化。"),
    ("T08", "泄漏风险辨识", "辨识阀门、法兰、管段泄漏风险与处置要点。"),
    ("T09", "消防设施检查", "检查消防器材、灭火系统状态与可用性。"),
    ("T10", "HSE 风险辨识", "辨识作业现场 HSE 风险与防护措施。"),
    ("T11", "巡检记录填写", "按规范填写巡检记录，内容完整、术语准确。"),
    ("T12", "异常信息报告", "按流程上报异常信息，内容准确、要素齐全。"),
    ("T13", "标准规范查询", "查询并引用国家/行业标准与操作规程。"),
]


# ===== 知识点（按能力归类，脱敏教学示例） =====
KNOWLEDGE_POINTS = [
    # process_understanding
    ("K-PROC-01", AbilityKey.process_understanding, "T01", "输气站工艺流程组成", "进站—分离—计量—调压—出站等功能区与介质流向。"),
    ("K-PROC-02", AbilityKey.process_understanding, "T01", "站场功能区作用", "各功能区设备组成与在流程中的作用。"),
    # equipment_recognition
    ("K-EQP-01", AbilityKey.equipment_recognition, "T03", "阀门类型识别", "闸阀、球阀、截止阀、安全阀、止回阀等类型与用途。"),
    ("K-EQP-02", AbilityKey.equipment_recognition, "T03", "阀门状态判读", "阀门开/关/内漏/外漏状态的判读方法。"),
    ("K-EQP-03", AbilityKey.equipment_recognition, "T04", "泵类设备结构", "离心泵、往复泵基本结构与运行参数。"),
    ("K-EQP-04", AbilityKey.equipment_recognition, "T05", "压缩机组认知", "往复式/离心式压缩机组结构与运行参数。"),
    # instrument_parameter
    ("K-INS-01", AbilityKey.instrument_parameter, "T06", "压力仪表读取", "压力表量程、读数与单位换算。"),
    ("K-INS-02", AbilityKey.instrument_parameter, "T06", "温度仪表读取", "温度仪表类型与读数方法。"),
    ("K-INS-03", AbilityKey.instrument_parameter, "T06", "流量仪表读取", "流量计类型与读数、单位换算。"),
    # abnormal_detection
    ("K-ABN-01", AbilityKey.abnormal_detection, "T07", "参数偏离识别", "压力/流量偏离设定值的识别与趋势判断。"),
    ("K-ABN-02", AbilityKey.abnormal_detection, "T07", "设备异常识别", "振动、温升、异响等设备异常辨识。"),
    ("K-ABN-03", AbilityKey.abnormal_detection, "T07", "趋势变化判断", "参数渐变与突变趋势的分析方法。"),
    # safety_awareness
    ("K-SAF-01", AbilityKey.safety_awareness, "T08", "泄漏风险辨识", "阀门/法兰/管段泄漏的辨识与风险分级。"),
    ("K-SAF-02", AbilityKey.safety_awareness, "T10", "HSE 风险辨识", "作业现场 HSE 风险源与防护措施。"),
    ("K-SAF-03", AbilityKey.safety_awareness, "T09", "消防设施检查", "灭火器、消防水系统状态检查要点。"),
    # standard_recording
    ("K-REC-01", AbilityKey.standard_recording, "T11", "巡检记录规范", "巡检记录的要素、术语与填写规范。"),
    ("K-REC-02", AbilityKey.standard_recording, "T12", "异常信息报告", "异常上报的要素、流程与规范表达。"),
]


TASK_ABILITY_WEIGHTS: dict[str, dict[AbilityKey, float]] = {
    "T01": {AbilityKey.process_understanding: 0.7, AbilityKey.equipment_recognition: 0.3},
    "T02": {AbilityKey.equipment_recognition: 0.3, AbilityKey.instrument_parameter: 0.2, AbilityKey.abnormal_detection: 0.3, AbilityKey.safety_awareness: 0.2},
    "T03": {AbilityKey.equipment_recognition: 0.55, AbilityKey.abnormal_detection: 0.3, AbilityKey.safety_awareness: 0.15},
    "T04": {AbilityKey.equipment_recognition: 0.55, AbilityKey.instrument_parameter: 0.3, AbilityKey.abnormal_detection: 0.15},
    "T05": {AbilityKey.equipment_recognition: 0.5, AbilityKey.instrument_parameter: 0.25, AbilityKey.abnormal_detection: 0.25},
    "T06": {AbilityKey.instrument_parameter: 0.75, AbilityKey.standard_recording: 0.25},
    "T07": {AbilityKey.abnormal_detection: 0.6, AbilityKey.instrument_parameter: 0.25, AbilityKey.process_understanding: 0.15},
    "T08": {AbilityKey.safety_awareness: 0.55, AbilityKey.abnormal_detection: 0.3, AbilityKey.standard_recording: 0.15},
    "T09": {AbilityKey.safety_awareness: 0.7, AbilityKey.equipment_recognition: 0.3},
    "T10": {AbilityKey.safety_awareness: 0.75, AbilityKey.abnormal_detection: 0.25},
    "T11": {AbilityKey.standard_recording: 0.8, AbilityKey.instrument_parameter: 0.2},
    "T12": {AbilityKey.standard_recording: 0.65, AbilityKey.abnormal_detection: 0.35},
    "T13": {AbilityKey.standard_recording: 0.65, AbilityKey.process_understanding: 0.35},
}


# 岗位群依据项目已导入的职业技能标准进行教学映射。每个岗位必须同时具备：
# 岗位能力权重（合计 1.0）和典型任务能力权重（每项任务合计 1.0）。
POSITION_BLUEPRINTS = [
    {
        "code": "P-PIPE-STATION",
        "name": "长输油气管道站场运行岗位",
        "description": (
            "依据《油气输送工国家职业技能标准（征求意见稿）》职业编码 6-16-02-11 "
            "第 3.9 节“长输油气管道站场运行工”进行教学映射。"
        ),
        "weights": ABILITY_WEIGHTS,
        "tasks": [
            (code, name, description, TASK_ABILITY_WEIGHTS[code])
            for code, name, description in JOB_TASKS
        ],
    },
    {
        "code": "P-GATHERING",
        "name": "油气集输运行岗位",
        "description": (
            "依据《油气输送工国家职业技能标准（征求意见稿）》职业编码 6-16-02-11 "
            "第 3.1 节“集输工”进行教学映射。"
        ),
        "weights": {
            AbilityKey.process_understanding: 0.25,
            AbilityKey.equipment_recognition: 0.20,
            AbilityKey.instrument_parameter: 0.15,
            AbilityKey.abnormal_detection: 0.15,
            AbilityKey.safety_awareness: 0.15,
            AbilityKey.standard_recording: 0.10,
        },
        "tasks": [
            ("GS01", "机泵及储运设备操作", "操作机泵和储运设备，识别启停条件与运行状态。", {
                AbilityKey.equipment_recognition: 0.45, AbilityKey.process_understanding: 0.25,
                AbilityKey.instrument_parameter: 0.15, AbilityKey.safety_awareness: 0.15,
            }),
            ("GS02", "油气集输流程操作", "识读并执行油气集输工艺流程和介质流向切换。", {
                AbilityKey.process_understanding: 0.50, AbilityKey.equipment_recognition: 0.20,
                AbilityKey.instrument_parameter: 0.15, AbilityKey.safety_awareness: 0.15,
            }),
            ("GS03", "油气处理与储存", "完成油气处理、储存相关设备状态确认和参数监视。", {
                AbilityKey.process_understanding: 0.35, AbilityKey.equipment_recognition: 0.25,
                AbilityKey.instrument_parameter: 0.15, AbilityKey.abnormal_detection: 0.15,
                AbilityKey.safety_awareness: 0.10,
            }),
            ("GS04", "运行参数录取与分析", "录取压力、温度、流量等参数并完成基础趋势分析。", {
                AbilityKey.instrument_parameter: 0.55, AbilityKey.abnormal_detection: 0.20,
                AbilityKey.standard_recording: 0.25,
            }),
            ("GS05", "储运设备巡检维护", "巡检储运设备，识别设备异常并记录维护信息。", {
                AbilityKey.equipment_recognition: 0.40, AbilityKey.abnormal_detection: 0.25,
                AbilityKey.safety_awareness: 0.25, AbilityKey.standard_recording: 0.10,
            }),
            ("GS06", "异常工况识别与报告", "识别集输异常工况、判断风险并按规范报告。", {
                AbilityKey.abnormal_detection: 0.40, AbilityKey.safety_awareness: 0.25,
                AbilityKey.standard_recording: 0.25, AbilityKey.process_understanding: 0.10,
            }),
        ],
    },
    {
        "code": "P-OIL-TRANSPORT",
        "name": "原油输送运行岗位",
        "description": (
            "依据《油气输送工国家职业技能标准（征求意见稿）》职业编码 6-16-02-11 "
            "第 3.3 节“输油工”进行教学映射。"
        ),
        "weights": {
            AbilityKey.process_understanding: 0.22,
            AbilityKey.equipment_recognition: 0.20,
            AbilityKey.instrument_parameter: 0.17,
            AbilityKey.abnormal_detection: 0.16,
            AbilityKey.safety_awareness: 0.15,
            AbilityKey.standard_recording: 0.10,
        },
        "tasks": [
            ("OT01", "输油泵机组操作", "识别并完成输油泵机组教学模拟启停与切换。", {
                AbilityKey.equipment_recognition: 0.45, AbilityKey.process_understanding: 0.20,
                AbilityKey.instrument_parameter: 0.20, AbilityKey.safety_awareness: 0.15,
            }),
            ("OT02", "输油工艺流程切换", "识读输油流程并完成教学情境中的流程切换判断。", {
                AbilityKey.process_understanding: 0.50, AbilityKey.equipment_recognition: 0.20,
                AbilityKey.instrument_parameter: 0.15, AbilityKey.safety_awareness: 0.15,
            }),
            ("OT03", "储油及辅助设备操作", "认知储油、加热及辅助设备的功能和运行状态。", {
                AbilityKey.equipment_recognition: 0.35, AbilityKey.process_understanding: 0.30,
                AbilityKey.instrument_parameter: 0.15, AbilityKey.safety_awareness: 0.20,
            }),
            ("OT04", "输油参数监控与计量", "监视输油压力、温度、流量并规范记录计量数据。", {
                AbilityKey.instrument_parameter: 0.50, AbilityKey.abnormal_detection: 0.20,
                AbilityKey.process_understanding: 0.15, AbilityKey.standard_recording: 0.15,
            }),
            ("OT05", "输油设备巡检维护", "巡检泵机组和输油设备，识别异常与安全风险。", {
                AbilityKey.equipment_recognition: 0.40, AbilityKey.abnormal_detection: 0.25,
                AbilityKey.safety_awareness: 0.25, AbilityKey.standard_recording: 0.10,
            }),
            ("OT06", "输油异常识别与报告", "识别输油异常工况并形成规范的异常信息报告。", {
                AbilityKey.abnormal_detection: 0.40, AbilityKey.safety_awareness: 0.25,
                AbilityKey.standard_recording: 0.25, AbilityKey.process_understanding: 0.10,
            }),
        ],
    },
    {
        "code": "P-GAS-TRANSPORT",
        "name": "天然气输送运行岗位",
        "description": (
            "依据《油气输送工国家职业技能标准（征求意见稿）》职业编码 6-16-02-11 "
            "第 3.4 节“输气工”进行教学映射。"
        ),
        "weights": {
            AbilityKey.process_understanding: 0.22,
            AbilityKey.equipment_recognition: 0.18,
            AbilityKey.instrument_parameter: 0.20,
            AbilityKey.abnormal_detection: 0.17,
            AbilityKey.safety_awareness: 0.13,
            AbilityKey.standard_recording: 0.10,
        },
        "tasks": [
            ("GT01", "天然气参数录取与计算", "录取天然气生产参数并完成基础输气量计算。", {
                AbilityKey.instrument_parameter: 0.55, AbilityKey.process_understanding: 0.25,
                AbilityKey.standard_recording: 0.20,
            }),
            ("GT02", "输气设备操作与流程切换", "识读输气流程并完成设备和流程状态判断。", {
                AbilityKey.process_understanding: 0.45, AbilityKey.equipment_recognition: 0.25,
                AbilityKey.instrument_parameter: 0.15, AbilityKey.safety_awareness: 0.15,
            }),
            ("GT03", "分离调压计量设备运行", "认知分离、调压和计量设备并监视运行参数。", {
                AbilityKey.equipment_recognition: 0.35, AbilityKey.instrument_parameter: 0.30,
                AbilityKey.process_understanding: 0.20, AbilityKey.safety_awareness: 0.15,
            }),
            ("GT04", "输气管道运行监控", "监控输气管道参数，识别趋势变化并记录信息。", {
                AbilityKey.instrument_parameter: 0.35, AbilityKey.abnormal_detection: 0.30,
                AbilityKey.process_understanding: 0.20, AbilityKey.standard_recording: 0.15,
            }),
            ("GT05", "输气设备巡检维护", "巡检输气设备，辨识设备异常和作业风险。", {
                AbilityKey.equipment_recognition: 0.40, AbilityKey.abnormal_detection: 0.25,
                AbilityKey.safety_awareness: 0.25, AbilityKey.standard_recording: 0.10,
            }),
            ("GT06", "输气异常与泄漏报告", "识别输气异常和泄漏风险并按流程报告。", {
                AbilityKey.abnormal_detection: 0.40, AbilityKey.safety_awareness: 0.30,
                AbilityKey.standard_recording: 0.20, AbilityKey.process_understanding: 0.10,
            }),
        ],
    },
    {
        "code": "P-METERING",
        "name": "油气计量检验岗位",
        "description": (
            "依据《油气输送工国家职业技能标准（征求意见稿）》职业编码 6-16-02-11 "
            "第 3.5 节“综合计量工”和第 3.8 节“油品计量工”进行教学映射。"
        ),
        "weights": {
            AbilityKey.process_understanding: 0.10,
            AbilityKey.equipment_recognition: 0.15,
            AbilityKey.instrument_parameter: 0.35,
            AbilityKey.abnormal_detection: 0.10,
            AbilityKey.safety_awareness: 0.10,
            AbilityKey.standard_recording: 0.20,
        },
        "tasks": [
            ("MT01", "油气样品采集", "按教学规范识别取样位置、器具和样品记录要求。", {
                AbilityKey.safety_awareness: 0.25, AbilityKey.instrument_parameter: 0.25,
                AbilityKey.standard_recording: 0.25, AbilityKey.process_understanding: 0.15,
                AbilityKey.equipment_recognition: 0.10,
            }),
            ("MT02", "油品化验分析", "识别常用化验仪器、分析数据并记录结果。", {
                AbilityKey.instrument_parameter: 0.45, AbilityKey.abnormal_detection: 0.20,
                AbilityKey.standard_recording: 0.20, AbilityKey.safety_awareness: 0.15,
            }),
            ("MT03", "计量参数计算", "完成标准密度、体积和质量等教学计量计算。", {
                AbilityKey.instrument_parameter: 0.55, AbilityKey.process_understanding: 0.20,
                AbilityKey.standard_recording: 0.25,
            }),
            ("MT04", "油气交接计量", "核对交接计量参数、偏差和记录要素。", {
                AbilityKey.instrument_parameter: 0.45, AbilityKey.standard_recording: 0.30,
                AbilityKey.safety_awareness: 0.15, AbilityKey.abnormal_detection: 0.10,
            }),
            ("MT05", "计量设备操作检定", "认知计量设备并完成教学模拟操作和状态检查。", {
                AbilityKey.equipment_recognition: 0.35, AbilityKey.instrument_parameter: 0.35,
                AbilityKey.abnormal_detection: 0.15, AbilityKey.safety_awareness: 0.15,
            }),
            ("MT06", "计量数据审核与报告", "审核计量数据异常并形成规范记录和报告。", {
                AbilityKey.instrument_parameter: 0.30, AbilityKey.abnormal_detection: 0.25,
                AbilityKey.standard_recording: 0.45,
            }),
        ],
    },
    {
        "code": "P-GAS-DISTRIBUTION",
        "name": "燃气输配场站运行岗位",
        "description": (
            "依据《燃气储运工国家职业技能标准（2021年版）》职业编码 6-28-02-01 "
            "第 3 章“工作要求”中燃气输配场站运行工方向进行教学映射。"
        ),
        "weights": {
            AbilityKey.process_understanding: 0.22,
            AbilityKey.equipment_recognition: 0.20,
            AbilityKey.instrument_parameter: 0.15,
            AbilityKey.abnormal_detection: 0.15,
            AbilityKey.safety_awareness: 0.18,
            AbilityKey.standard_recording: 0.10,
        },
        "tasks": [
            ("FG01", "燃气输配设施压力测试", "识别压力测试连接、仪表读数和异常压力变化。", {
                AbilityKey.instrument_parameter: 0.35, AbilityKey.equipment_recognition: 0.20,
                AbilityKey.abnormal_detection: 0.20, AbilityKey.safety_awareness: 0.25,
            }),
            ("FG02", "置换与通气投产", "识读置换与通气投产流程并辨识关键安全条件。", {
                AbilityKey.process_understanding: 0.40, AbilityKey.equipment_recognition: 0.20,
                AbilityKey.instrument_parameter: 0.15, AbilityKey.safety_awareness: 0.25,
            }),
            ("FG03", "燃气场站设备运行", "认知场站设备功能并监控教学运行状态。", {
                AbilityKey.equipment_recognition: 0.35, AbilityKey.process_understanding: 0.30,
                AbilityKey.instrument_parameter: 0.20, AbilityKey.safety_awareness: 0.15,
            }),
            ("FG04", "调压计量与供气监控", "读取调压计量参数并识别供气趋势变化。", {
                AbilityKey.instrument_parameter: 0.40, AbilityKey.process_understanding: 0.25,
                AbilityKey.abnormal_detection: 0.20, AbilityKey.standard_recording: 0.15,
            }),
            ("FG05", "管网巡检与泄漏辨识", "巡检燃气管网设施，辨识泄漏和设备状态异常。", {
                AbilityKey.abnormal_detection: 0.35, AbilityKey.safety_awareness: 0.35,
                AbilityKey.equipment_recognition: 0.20, AbilityKey.standard_recording: 0.10,
            }),
            ("FG06", "安全防护与运行记录", "辨识燃气作业风险并完成规范运行记录。", {
                AbilityKey.safety_awareness: 0.40, AbilityKey.standard_recording: 0.35,
                AbilityKey.abnormal_detection: 0.15, AbilityKey.instrument_parameter: 0.10,
            }),
        ],
    },
]


SKILL_POINT_NAMES = {
    "K-PROC-01": "识读站场介质流向",
    "K-PROC-02": "说明功能区设备作用",
    "K-EQP-01": "辨识常见阀门类型",
    "K-EQP-02": "判读阀门开关与泄漏状态",
    "K-EQP-03": "辨识泵类设备结构与状态",
    "K-EQP-04": "辨识压缩机组结构与状态",
    "K-INS-01": "读取压力参数并核对单位",
    "K-INS-02": "读取温度参数并判断偏离",
    "K-INS-03": "读取流量参数并完成换算",
    "K-ABN-01": "识别运行参数偏离",
    "K-ABN-02": "辨识振动温升异响异常",
    "K-ABN-03": "分析参数渐变与突变趋势",
    "K-SAF-01": "辨识密封点泄漏风险",
    "K-SAF-02": "完成作业情境风险辨识",
    "K-SAF-03": "检查消防设施状态",
    "K-REC-01": "填写完整规范的巡检记录",
    "K-REC-02": "组织异常信息并按流程报告",
}


EVIDENCE_POINT_OVERRIDES = {
    "职业岗位认知": "K-PROC-01",
    "技能等级要求": "K-REC-01",
    "管道与标志识别": "K-EQP-01",
}

EVIDENCE_ABILITY_FALLBACK = {
    AbilityKey.process_understanding.value: "K-PROC-01",
    AbilityKey.equipment_recognition.value: "K-EQP-02",
    AbilityKey.instrument_parameter.value: "K-INS-01",
    AbilityKey.abnormal_detection.value: "K-ABN-01",
    AbilityKey.safety_awareness.value: "K-SAF-02",
    AbilityKey.standard_recording.value: "K-REC-01",
}


async def _seed_abilities(session: AsyncSession) -> dict[str, int]:
    existing = {a.key: a for a in (await session.scalars(select(Ability))).all()}
    ids: dict[str, int] = {}
    for key in AbilityKey:
        ab = existing.get(key.value)
        if ab is None:
            ab = Ability(
                key=key.value,
                name=ABILITY_CN[key],
                weight=ABILITY_WEIGHTS[key],
                description=f"{ABILITY_CN[key]} 维度能力",
            )
            session.add(ab)
            await session.flush()
        else:
            ab.weight = ABILITY_WEIGHTS[key]
            ab.name = ABILITY_CN[key]
        ids[key.value] = ab.id
    return ids


async def _seed_positions(
    session: AsyncSession,
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """幂等写入完整岗位蓝图；空岗位不会被写入图谱。"""
    existing_positions = {
        position.code: position
        for position in (await session.scalars(select(Position))).all()
    }
    position_ids: dict[str, int] = {}
    task_ids_by_position: dict[str, dict[str, int]] = {}

    for blueprint in POSITION_BLUEPRINTS:
        position = existing_positions.get(blueprint["code"])
        if position is None:
            position = Position(
                code=blueprint["code"],
                name=blueprint["name"],
                major="油气储运工程",
                description=blueprint["description"],
            )
            session.add(position)
            await session.flush()
        else:
            position.name = blueprint["name"]
            position.major = "油气储运工程"
            position.description = blueprint["description"]

        existing_tasks = {
            task.code: task
            for task in (
                await session.scalars(
                    select(JobTask).where(JobTask.position_id == position.id)
                )
            ).all()
        }
        # 正式图谱保护：岗位已存在任意典型任务（含教师/AI工作流建立的任务）时，
        # 不再注入该岗位的蓝图默认任务，避免初始化扩展或覆盖既有图谱；
        # 全新岗位（无任何任务）仍写入完整蓝图，保证新库初始化完整。
        # 判断依据是"岗位已有任务"这一图谱事实，而非任务编码前缀。
        has_formal_graph = bool(existing_tasks)
        task_ids: dict[str, int] = {}
        for sort_order, (code, name, description, _weights) in enumerate(
            blueprint["tasks"], start=1
        ):
            task = existing_tasks.get(code)
            if task is None:
                if has_formal_graph:
                    continue
                task = JobTask(
                    position_id=position.id,
                    code=code,
                    name=name,
                    description=description,
                    sort_order=sort_order,
                )
                session.add(task)
                await session.flush()
            else:
                task.name = name
                task.description = description
                task.sort_order = sort_order
            task_ids[code] = task.id

        position_ids[blueprint["code"]] = position.id
        task_ids_by_position[blueprint["code"]] = task_ids

    return position_ids, task_ids_by_position


# ===== 专业群示范配置（P0-3；教学示例数据，名称与专业特色权重均可配置） =====
PROFESSIONAL_GROUP_SEED: dict = {
    "code": "PG-OIL-001",
    "name": "智慧油气储运与安全专业群",
    "industry_domain": "油气储运与城市燃气安全",
    "description": "面向油气储运生产运维一线，辐射城市燃气、仪表自动化与安全生产服务的示范专业群。",
    "majors": [
        {
            "code": "MAJOR-OIL-STORAGE",
            "name": "油气储运工程",  # 与既有 CurriculumProgram.major/Position.major 字符串一致，seed 回填 major_id
            "is_core": True,
            "ability_weights": {
                "process_understanding": 25,
                "equipment_recognition": 20,
                "instrument_parameter": 15,
                "abnormal_detection": 15,
                "safety_awareness": 15,
                "standard_recording": 10,
            },
            "description": "群内核心专业：站场运行、管输工艺与设备完整性方向。",
        },
        {
            "code": "MAJOR-URBAN-GAS",
            "name": "城市燃气工程技术",
            "is_core": False,
            "ability_weights": {
                "process_understanding": 20,
                "equipment_recognition": 15,
                "instrument_parameter": 15,
                "abnormal_detection": 15,
                "safety_awareness": 25,
                "standard_recording": 10,
            },
            "description": "城市门站—管网—用户终端运行与燃气安全服务方向。",
        },
        {
            "code": "MAJOR-IND-AUTO",
            "name": "工业过程自动化技术",
            "is_core": False,
            "ability_weights": {
                "process_understanding": 15,
                "equipment_recognition": 20,
                "instrument_parameter": 30,
                "abnormal_detection": 15,
                "safety_awareness": 10,
                "standard_recording": 10,
            },
            "description": "SCADA/PLC 仪表与控制系统运维方向（仪控特色）。",
        },
        {
            "code": "MAJOR-SAFETY-TECH",
            "name": "安全技术与管理",
            "is_core": False,
            "ability_weights": {
                "process_understanding": 10,
                "equipment_recognition": 10,
                "instrument_parameter": 10,
                "abnormal_detection": 25,
                "safety_awareness": 35,
                "standard_recording": 10,
            },
            "description": "HSE 风险辨识、作业许可与应急处置方向。",
        },
    ],
}


async def _seed_professional_group(session: AsyncSession) -> tuple[int, int]:
    """幂等写入专业群与示范专业，并按名称精确匹配回填旧数据的 major_id。

    返回 (专业数, 回填链接数)。旧字符串列 major 保留不删，匹配不上的一律不动。
    """
    payload = PROFESSIONAL_GROUP_SEED
    group = (
        await session.scalars(
            select(ProfessionalGroup).where(ProfessionalGroup.code == payload["code"])
        )
    ).first()
    if group is None:
        group = ProfessionalGroup(code=payload["code"])
        session.add(group)
    group.name = payload["name"]
    group.industry_domain = payload["industry_domain"]
    group.description = payload["description"]
    await session.flush()

    known_keys = {k.value for k in AbilityKey}
    major_ids_by_name: dict[str, int] = {}
    for spec in payload["majors"]:
        weights = spec["ability_weights"]
        if set(weights) - known_keys or abs(sum(weights.values()) - 100) > 1e-9:
            raise ValueError(
                f"专业 {spec['code']} 的 ability_weights 非法：必须使用六维能力键且权重合计 100"
            )  # fail-loud：配置错误禁止带病上线
        major = (
            await session.scalars(select(Major).where(Major.code == spec["code"]))
        ).first()
        if major is None:
            major = Major(code=spec["code"])
            session.add(major)
        major.professional_group_id = group.id
        major.name = spec["name"]
        major.is_core_major = spec["is_core"]
        major.ability_weights = weights
        major.description = spec["description"]
        await session.flush()
        major_ids_by_name[major.name] = major.id

    backfilled = 0
    for name, major_id in major_ids_by_name.items():
        for model in (Position, CurriculumProgram):
            result = await session.execute(
                update(model)
                .where(model.major == name, model.major_id.is_(None))
                .values(major_id=major_id)
            )
            backfilled += int(result.rowcount or 0)
    return len(major_ids_by_name), backfilled


async def _seed_knowledge_points(
    session: AsyncSession, ability_ids: dict[str, int], task_ids: dict[str, int]
) -> None:
    existing = {k.code for k in (await session.scalars(select(KnowledgePoint))).all()}
    for code, ability_key, task_code, name, desc in KNOWLEDGE_POINTS:
        if code in existing:
            continue
        kp = KnowledgePoint(
            ability_id=ability_ids[ability_key.value],
            job_task_id=task_ids.get(task_code),
            code=code,
            name=name,
            description=desc,
        )
        session.add(kp)
    await session.flush()


async def _seed_graph_relations(
    session: AsyncSession,
    position_ids: dict[str, int],
    ability_ids: dict[str, int],
    task_ids_by_position: dict[str, dict[str, int]],
) -> None:
    """建立多岗位→任务→能力→知识→技能的真实数据库关系。"""
    position_relations = {
        (r.position_id, r.ability_id): r
        for r in (await session.scalars(select(PositionAbilityRelation))).all()
    }
    task_relations = {
        (r.job_task_id, r.ability_id): r
        for r in (await session.scalars(select(TaskAbilityRelation))).all()
    }

    for blueprint in POSITION_BLUEPRINTS:
        position_id = position_ids[blueprint["code"]]
        for ability_key, weight in blueprint["weights"].items():
            ability_id = ability_ids[ability_key.value]
            relation = position_relations.get((position_id, ability_id))
            if relation is None:
                session.add(PositionAbilityRelation(
                    position_id=position_id,
                    ability_id=ability_id,
                    weight=weight,
                ))
            # 已有权重不覆盖：岗位能力权重属教师/业务数据，初始化只补缺，不改正。

        task_ids = task_ids_by_position[blueprint["code"]]
        for task_code, _name, _description, weights in blueprint["tasks"]:
            if task_code not in task_ids:
                # 正式图谱保护下该岗位未注入蓝图任务（见 _seed_positions），
                # 其任务级权重关系同样不创建。
                continue
            for ability_key, weight in weights.items():
                relation_key = (task_ids[task_code], ability_ids[ability_key.value])
                relation = task_relations.get(relation_key)
                if relation is None:
                    session.add(TaskAbilityRelation(
                        job_task_id=relation_key[0],
                        ability_id=relation_key[1],
                        weight=weight,
                    ))
                # 已有任务能力权重同理只补缺，不覆盖。

    # 技能点自动生成仅面向种子编码体系（K-前缀，K-→S- 派生）；
    # 其他来源的知识点（如 AI 工作流创建的岗位图谱）编码不含"K-"中缀，
    # 派生码会与知识点同码，误建冗余技能点，故显式跳过。
    knowledge_points = (await session.scalars(select(KnowledgePoint))).all()
    skills = {s.code: s for s in (await session.scalars(select(SkillPoint))).all()}
    for point in knowledge_points:
        if "K-" not in point.code:
            continue
        code = point.code.replace("K-", "S-", 1)
        skill = skills.get(code)
        name = SKILL_POINT_NAMES.get(point.code, f"应用{point.name}")
        if skill is None:
            session.add(SkillPoint(
                knowledge_point_id=point.id,
                code=code,
                name=name,
                description=f"在教学模拟任务中{name}。",
            ))
        else:
            skill.knowledge_point_id = point.id
            skill.name = name
    await session.flush()


async def _seed_users(session: AsyncSession) -> None:
    demos = [
        ("student", "学生·演示", "student123", "student", "S2026001", "储运 2026-1 班"),
        ("teacher", "教师·演示", "teacher123", "teacher", None, None),
        ("admin", "管理员·演示", "admin123", "admin", None, None),
    ]
    existing = {u.username for u in (await session.scalars(select(User))).all()}
    for username, real_name, pwd, role, sno, cls in demos:
        if username in existing:
            continue
        u = User(
            username=username,
            real_name=real_name,
            hashed_password=hash_password(pwd),
            role=role,  # type: ignore[arg-type]
            student_no=sno,
            class_name=cls,
        )
        session.add(u)
    await session.flush()


# ===== 8 个训练任务（第四十七节，均为教学模拟） =====
def _inspection_scenario() -> dict:
    """输气站日常巡检教学模拟情境（核心演示任务）。"""
    return {
        "scenario_text": "【教学模拟】某输气站处于平稳输送工况。你需要按进站区—分离区—计量区—调压区—出站区完成一轮日常巡检。现场给出脱敏仪表参数，并设置阀杆疑似微漏和法兰轻微渗漏两个异常线索。",
        "initial_question": "请先说明你的巡检路线、每个区域要检查的设备与参数，以及发现疑似泄漏后如何安全报告和处置。",
        "station": "某输气站（教学模拟）",
        "route": ["进站区", "分离区", "计量区", "调压区", "出站区"],
        "conditions": {
            "note": "以下工况与参数均为教学模拟/脱敏数据，非真实生产数据。",
            "inlet_pressure_mpa": 4.5,
            "outlet_pressure_mpa": 3.2,
            "temperature_c": 18,
            "flow_nm3_h": 120000,
            "valves_total": 36,
        },
        "abnormalities": [
            {"loc": "进站区 3#球阀阀杆", "phenomenon": "阀杆处疑似微漏（教学模拟）", "severity": "中"},
            {"loc": "计量区法兰 F-12", "phenomenon": "法兰面轻微渗漏（教学模拟）", "severity": "中"},
        ],
        "safety_tip": "本情境为教学模拟，不作为真实现场操作依据。",
    }


TRAINING_SCENARIOS = {
    "TT-02": ("【教学模拟】系统展示一张输气站简化流程图，包含进站、分离、计量、调压和出站功能区，所有参数均为脱敏数据。", "请按介质流向依次说明各功能区的主要设备和作用。"),
    "TT-03": ("【教学模拟】巡检画面中出现球阀、闸阀和截止阀，并给出阀位标识、阀杆外观和密封点检测提示。", "请识别阀门类型与开关状态，并指出哪些现象需要作为泄漏异常上报。"),
    "TT-04": ("【教学模拟】站场仪表面板给出压力、温度和流量读数，其中一项存在单位换算要求，一项较历史区间发生偏离。", "请逐项读取参数、写明单位，并判断哪一项需要进一步核查。"),
    "TT-05": ("【教学模拟】系统提供一组连续运行趋势和设备巡检信息，其中包含压力波动、温升与轻微异响等线索。", "请找出异常信息，按风险优先级说明判断依据和后续报告要点。"),
    "TT-06": ("【教学模拟】某检维修区域同时出现临时用电、受限空间入口和可燃气体检测提示，现场不进行任何真实作业。", "请辨识主要 HSE 风险，并列出作业前必须核对的隔离、检测、监护和防护条件。"),
    "TT-07": ("【教学模拟】你已完成一轮站场巡检，系统提供时间、位置、参数和两处异常线索，需要形成规范记录。", "请按巡检记录格式整理正常数据与异常信息，并说明异常上报应包含哪些要素。"),
    "TT-08": ("【教学模拟】综合任务同时提供简化流程、设备状态、仪表趋势、泄漏线索和巡检记录模板，所有数据均为脱敏教学数据。", "请综合流程、设备、参数、异常、安全和记录六个方面给出完整分析。"),
}


TRAINING_TASKS = [
    {
        "code": "TT-01", "title": "输气站日常巡检基础训练", "difficulty": 2,
        "target": [AbilityKey.abnormal_detection, AbilityKey.safety_awareness, AbilityKey.equipment_recognition],
        "kp": ["K-ABN-01", "K-SAF-01", "K-EQP-02"], "minutes": 15, "follow_ups": 3,
        "required": ["巡检路线确认", "阀门状态检查", "压力/温度/流量读取", "渗漏检查", "消防器材状态", "巡检记录规范"],
        "reference": [
            "应按既定巡检路线覆盖进站—分离—计量—调压—出站各区。",
            "阀门状态检查应区分开/关/内漏/外漏，阀杆处疑似微漏属异常。",
            "压力/温度/流量参数应读取并与设计值/历史趋势比对判读。",
            "法兰面渗漏属于泄漏风险，应辨识并评估风险等级。",
            "消防器材应检查位置、铅封、压力与有效期。",
            "巡检记录应要素齐全、术语规范、异常及时上报。",
        ],
    },
    {
        "code": "TT-02", "title": "站场工艺流程识读", "difficulty": 1,
        "target": [AbilityKey.process_understanding],
        "kp": ["K-PROC-01", "K-PROC-02"], "minutes": 10, "follow_ups": 2,
        "required": ["功能区识别", "介质流向", "设备组成", "功能区作用"],
        "reference": ["应识读进站—分离—计量—调压—出站流程。", "应说明各功能区设备与作用。"],
    },
    {
        "code": "TT-03", "title": "阀门状态识别训练", "difficulty": 2,
        "target": [AbilityKey.equipment_recognition, AbilityKey.abnormal_detection],
        "kp": ["K-EQP-01", "K-EQP-02"], "minutes": 12, "follow_ups": 3,
        "required": ["阀门类型", "开/关状态", "内漏/外漏判读", "风险辨识"],
        "reference": ["应区分闸阀/球阀/截止阀等类型。", "应判读阀杆微漏等异常。"],
    },
    {
        "code": "TT-04", "title": "仪表参数认知训练", "difficulty": 2,
        "target": [AbilityKey.instrument_parameter],
        "kp": ["K-INS-01", "K-INS-02", "K-INS-03"], "minutes": 12, "follow_ups": 2,
        "required": ["压力读数", "温度读数", "流量读数", "单位换算"],
        "reference": ["应正确读取量程与读数并换算单位。", "应判断参数是否偏离。"],
    },
    {
        "code": "TT-05", "title": "多信息异常识别训练", "difficulty": 3,
        "target": [AbilityKey.abnormal_detection, AbilityKey.instrument_parameter],
        "kp": ["K-ABN-01", "K-ABN-02", "K-ABN-03"], "minutes": 18, "follow_ups": 3,
        "required": ["参数偏离", "设备异常", "趋势判断", "原因分析"],
        "reference": ["应识别参数偏离与趋势变化。", "应分析振动/温升/异响等设备异常。"],
    },
    {
        "code": "TT-06", "title": "HSE 风险辨识训练", "difficulty": 3,
        "target": [AbilityKey.safety_awareness],
        "kp": ["K-SAF-02", "K-SAF-03"], "minutes": 15, "follow_ups": 3,
        "required": ["风险源识别", "防护措施", "消防设施", "应急处置"],
        "reference": ["应辨识作业现场 HSE 风险源。", "应明确防护与应急处置措施。"],
    },
    {
        "code": "TT-07", "title": "巡检记录规范训练", "difficulty": 2,
        "target": [AbilityKey.standard_recording],
        "kp": ["K-REC-01", "K-REC-02"], "minutes": 10, "follow_ups": 2,
        "required": ["记录要素", "术语规范", "异常上报", "完整性"],
        "reference": ["巡检记录应要素齐全、术语规范。", "异常应按流程及时上报。"],
    },
    {
        "code": "TT-08", "title": "综合岗位能力训练", "difficulty": 4,
        "target": list(AbilityKey), "kp": [], "minutes": 25, "follow_ups": 3,
        "required": ["流程识读", "设备认知", "参数判读", "异常识别", "风险辨识", "规范记录"],
        "reference": ["应综合运用六维能力完成岗位任务。", "应形成系统性岗位思维。"],
    },
]


def _question_spec(
    stem: str,
    ability: AbilityKey,
    knowledge_point: str,
    explanation: str,
    choices: list[str],
    correct_key: str,
    partial_key: str | None = None,
) -> dict:
    return {
        "stem": stem,
        "ability": ability.value,
        "knowledge_point": knowledge_point,
        "explanation": explanation,
        "choices": choices,
        "correct_key": correct_key,
        "partial_key": partial_key,
    }


# 岗位情境选择题题库。题干、选项、分值和反馈全部持久化，实训时不调用大模型。
TRAINING_QUESTION_BANK = {
    "TT-01": [
        _question_spec(
            "巡检开始前，哪项准备最符合规范要求？",
            AbilityKey.safety_awareness,
            "巡检准备",
            "巡检应先确认任务、路线、风险提示和必要防护，再进入教学模拟环节。",
            ["直接从最近设备开始", "确认任务路线、风险提示和防护要求", "只携带记录表", "等待出现报警再检查"],
            "B",
            "C",
        ),
        _question_spec(
            "模拟巡检发现阀杆处疑似微漏，首要选择是什么？",
            AbilityKey.abnormal_detection,
            "阀门泄漏异常",
            "疑似泄漏应保持安全距离、标记异常并按教学流程报告，不应擅自处置。",
            ["擦拭后继续巡检", "保持安全距离并按流程报告", "自行紧固阀杆", "忽略轻微现象"],
            "B",
        ),
        _question_spec(
            "下列哪组信息最适合作为一次完整巡检记录？",
            AbilityKey.standard_recording,
            "巡检记录要素",
            "规范记录应包含时间、位置、参数、设备状态、异常描述与报告情况。",
            ["时间和签名", "设备名称和正常二字", "时间、位置、参数、状态、异常及上报情况", "只记录异常设备"],
            "C",
            "B",
        ),
    ],
    "TT-02": [
        _question_spec(
            "输气站简化流程中，介质流向的合理顺序是？",
            AbilityKey.process_understanding,
            "站场流程顺序",
            "教学简化流程按进站、分离、计量、调压、出站识读。",
            ["进站—计量—分离—出站—调压", "进站—分离—计量—调压—出站", "调压—进站—分离—计量—出站", "进站—出站—分离—计量—调压"],
            "B",
        ),
        _question_spec(
            "分离功能区在简化工艺中的主要作用是？",
            AbilityKey.process_understanding,
            "分离区作用",
            "分离区用于去除输送介质中需要分离的液滴或杂质，为后续环节提供条件。",
            ["改变计量单位", "分离液滴或杂质", "填写巡检记录", "替代全部安全设施"],
            "B",
        ),
        _question_spec(
            "识读流程图时，最可靠的判断依据组合是？",
            AbilityKey.process_understanding,
            "流程图识读",
            "应综合管线连接、流向标识、设备符号和功能区名称判断。",
            ["只看设备颜色", "只凭设备大小", "管线连接、流向箭头、设备符号与区域名称", "按个人经验猜测"],
            "C",
        ),
    ],
    "TT-03": [
        _question_spec(
            "判断阀门类型时，应优先综合哪些信息？",
            AbilityKey.equipment_recognition,
            "阀门类型识别",
            "阀门识别应综合结构特征、铭牌标识和流程图符号。",
            ["结构特征、铭牌和流程图符号", "阀体颜色", "安装时间", "周围设备数量"],
            "A",
        ),
        _question_spec(
            "阀位标识与现场外观不一致时，正确做法是？",
            AbilityKey.abnormal_detection,
            "阀位异常",
            "状态信息不一致属于需核查异常，应记录并报告，不能仅凭单一外观下结论。",
            ["以外观为准直接修改标识", "以标识为准忽略外观", "记录不一致并按流程核查报告", "自行操作阀门验证"],
            "C",
        ),
        _question_spec(
            "哪一现象最应作为外漏线索记录上报？",
            AbilityKey.abnormal_detection,
            "阀门外漏识别",
            "密封点出现可疑介质痕迹或检测提示时，应作为外漏线索记录上报。",
            ["铭牌字迹清晰", "阀体涂层完整", "密封点出现可疑痕迹并有检测提示", "手轮方向正常"],
            "C",
        ),
    ],
    "TT-04": [
        _question_spec(
            "读取仪表参数时，哪种记录方式最完整？",
            AbilityKey.instrument_parameter,
            "仪表读数",
            "仪表记录应包含位号、数值、单位、时间及必要的状态说明。",
            ["仅记录数值", "位号、数值、单位、时间和状态", "只记录是否正常", "拍照但不登记"],
            "B",
            "A",
        ),
        _question_spec(
            "同一参数与历史趋势明显偏离但未达到报警值，应如何判断？",
            AbilityKey.instrument_parameter,
            "参数趋势判断",
            "未报警不等于正常，明显偏离历史趋势仍应复核数据并记录报告。",
            ["未报警即可忽略", "立即认定设备故障", "复核单位和读数，并结合趋势记录报告", "修改数据使其接近历史值"],
            "C",
        ),
        _question_spec(
            "进行单位换算后，记录中还应保留什么信息？",
            AbilityKey.standard_recording,
            "单位换算记录",
            "换算记录应明确原始值、原单位、换算值和目标单位，便于追溯。",
            ["只保留换算结果", "原始值与单位、换算结果与单位", "只写换算公式", "删除原始读数"],
            "B",
            "C",
        ),
    ],
    "TT-05": [
        _question_spec(
            "连续趋势中出现压力波动扩大并伴随设备异响，应如何处理信息？",
            AbilityKey.abnormal_detection,
            "多源异常关联",
            "多项异常同时出现时应关联分析、提高风险关注并按流程报告。",
            ["分别忽略轻微变化", "只记录压力", "关联趋势与异响，标记风险并报告", "自行拆检设备"],
            "C",
        ),
        _question_spec(
            "对多条异常线索排序时，应优先考虑什么？",
            AbilityKey.safety_awareness,
            "异常风险排序",
            "风险排序应优先考虑人员安全、泄漏火灾等后果及变化趋势。",
            ["记录最容易的线索", "人员安全与潜在严重后果", "设备编号大小", "发现顺序"],
            "B",
        ),
        _question_spec(
            "尚不能确定异常原因时，报告中应怎样表述？",
            AbilityKey.standard_recording,
            "异常客观描述",
            "应区分事实、趋势和推测，客观记录已知信息并说明待核查项。",
            ["把推测写成确定结论", "删除不确定信息", "记录事实和趋势，并标明原因待核查", "只写设备异常"],
            "C",
        ),
    ],
    "TT-06": [
        _question_spec(
            "受限空间教学情境中，作业前最关键的条件组合是？",
            AbilityKey.safety_awareness,
            "受限空间风险控制",
            "应核对许可、隔离、检测、通风、监护和防护等条件；本系统不指导真实作业。",
            ["工具和照明", "许可、隔离、检测、通风、监护与防护", "人员到齐即可", "先进入再补手续"],
            "B",
            "A",
        ),
        _question_spec(
            "临时用电与可燃气体风险同时出现时，哪项判断正确？",
            AbilityKey.safety_awareness,
            "复合 HSE 风险",
            "风险可能相互放大，应停止进入并按教学流程核对隔离、检测和许可条件。",
            ["两个风险相互独立无需关联", "风险可能叠加，应停止进入并报告核查", "只检查电缆外观", "检测一次后永久有效"],
            "B",
        ),
        _question_spec(
            "发现安全条件与作业许可信息不一致时，应选择？",
            AbilityKey.safety_awareness,
            "作业许可核对",
            "条件不一致时不能继续，应暂停并由授权人员核查确认。",
            ["按许可内容继续", "按现场条件继续", "暂停并报告，由授权人员核查", "自行修改许可"],
            "C",
        ),
    ],
    "TT-07": [
        _question_spec(
            "异常上报记录中，哪组要素最便于教师复盘？",
            AbilityKey.standard_recording,
            "异常上报要素",
            "异常记录应包括时间、地点、对象、现象、参数、风险判断、报告对象和处置状态。",
            ["异常二字和签名", "时间、地点、对象、现象、参数、风险及上报状态", "设备照片", "最终结论"],
            "B",
        ),
        _question_spec(
            "巡检记录中的参数书写应遵循什么原则？",
            AbilityKey.standard_recording,
            "参数记录规范",
            "参数应记录原始读数和单位，保持真实、准确、可追溯。",
            ["统一取整数", "按经验修正", "原始读数、单位明确且可追溯", "只记录异常值"],
            "C",
        ),
        _question_spec(
            "后续核查发现原记录有误，规范做法是？",
            AbilityKey.standard_recording,
            "记录更正",
            "更正应保留原记录痕迹并注明更正内容、原因、时间和责任人。",
            ["直接覆盖原记录", "删除整条记录", "按规定更正并保留痕迹和说明", "不做处理"],
            "C",
        ),
    ],
    "TT-08": [
        _question_spec(
            "综合情境中首先应建立哪种分析顺序？",
            AbilityKey.process_understanding,
            "综合分析顺序",
            "应先确认流程与工况，再核对设备参数、识别异常和风险，最后规范记录报告。",
            ["先写结论再找证据", "流程工况—设备参数—异常风险—记录报告", "只看报警信息", "只检查记录模板"],
            "B",
        ),
        _question_spec(
            "出现参数偏离、泄漏线索和记录缺项时，优先级最高的是？",
            AbilityKey.safety_awareness,
            "综合风险优先级",
            "应优先关注可能危及人员和环境安全的泄漏线索，同时记录并报告其他问题。",
            ["先补全记录格式", "先处理字体问题", "优先隔离关注泄漏风险并按流程报告", "先计算平均参数"],
            "C",
            "A",
        ),
        _question_spec(
            "完整的综合任务结论应具备什么特点？",
            AbilityKey.standard_recording,
            "综合结论",
            "结论应有事实依据、风险分级、待核查项、报告状态及权威知识引用。",
            ["结论越短越好", "只列设备名称", "事实依据、风险判断、待核查项、上报状态和知识依据齐全", "全部表述为正常"],
            "C",
        ),
    ],
}


async def _seed_training_questions(session: AsyncSession) -> None:
    """幂等补齐已发布任务的选择题与分级评分选项。"""
    tasks = {task.code: task for task in (await session.scalars(select(TrainingTask))).all()}
    for task_code, specs in TRAINING_QUESTION_BANK.items():
        task = tasks.get(task_code)
        if task is None:
            continue
        existing_questions = {
            question.code: question
            for question in (
                await session.scalars(select(TrainingQuestion).where(TrainingQuestion.task_id == task.id))
            ).all()
        }
        for index, spec in enumerate(specs, 1):
            question_code = f"{task_code}-Q{index:02d}"
            question = existing_questions.get(question_code)
            if question is None:
                question = TrainingQuestion(
                    task_id=task.id,
                    code=question_code,
                    stem=spec["stem"],
                    ability_key=spec["ability"],
                    knowledge_point=spec["knowledge_point"],
                    explanation=spec["explanation"],
                    sort_order=index,
                    max_score=100,
                    active=True,
                    status="published",
                    batch_code="seed",
                    generated_by_ai=False,
                    generation_meta={"source": "curated_seed", "review_status": "pre_reviewed"},
                )
                session.add(question)
                await session.flush()
            option_count = await session.scalar(
                select(func.count()).select_from(TrainingOption).where(TrainingOption.question_id == question.id)
            )
            if option_count:
                continue
            for option_index, content in enumerate(spec["choices"]):
                option_key = chr(ord("A") + option_index)
                is_correct = option_key == spec["correct_key"]
                is_partial = option_key == spec.get("partial_key")
                score = 100 if is_correct else 60 if is_partial else 0
                if is_correct:
                    feedback = f"判断正确。{spec['explanation']}"
                elif is_partial:
                    feedback = f"方向部分正确，但信息不完整。{spec['explanation']}"
                else:
                    feedback = f"该选项不符合本题岗位规范。{spec['explanation']}"
                session.add(
                    TrainingOption(
                        question_id=question.id,
                        option_key=option_key,
                        content=content,
                        score=score,
                        feedback=feedback,
                        is_correct=is_correct,
                    )
                )
    await session.flush()


async def _seed_training_tasks(session: AsyncSession) -> None:
    existing = {t.code: t for t in (await session.scalars(select(TrainingTask))).all()}
    for t in TRAINING_TASKS:
        scenario = _inspection_scenario() if t["code"] == "TT-01" else {
            "scenario_text": TRAINING_SCENARIOS[t["code"]][0],
            "initial_question": TRAINING_SCENARIOS[t["code"]][1],
            "note": "教学模拟情境",
            "safety_tip": "教学模拟，非真实生产数据。",
        }
        task = existing.get(t["code"])
        if task is None:
            task = TrainingTask(
                code=t["code"],
                title=t["title"],
                description=f"{t['title']}（教学模拟任务）",
                difficulty=t["difficulty"],
                target_abilities=[a.value for a in t["target"]],
                knowledge_points=t["kp"],
                required_points=t["required"],
                reference_points=t["reference"],
                scenario=scenario,
                max_follow_ups=t["follow_ups"],
                estimated_minutes=t["minutes"],
                status=TaskStatus.published,
            )
            session.add(task)
        else:
            # 仅补齐历史种子缺失的情境字段，保留教师后续编辑。
            current_scenario = dict(task.scenario or {})
            for key in ("scenario_text", "initial_question", "note", "safety_tip"):
                if not current_scenario.get(key) and scenario.get(key):
                    current_scenario[key] = scenario[key]
            task.scenario = current_scenario
        await session.flush()  # 取得 task.id
        if t["code"] == "TT-01":
            training_scenario = await session.scalar(
                select(TrainingScenario).where(TrainingScenario.task_id == task.id)
            )
            if training_scenario is None:
                training_scenario = TrainingScenario(
                    task_id=task.id,
                    scenario_text=scenario["scenario_text"],
                    conditions=scenario["conditions"],
                    ai_generated=False,
                    approved=True,
                )
                session.add(training_scenario)
            elif not training_scenario.scenario_text:
                training_scenario.scenario_text = scenario["scenario_text"]
                training_scenario.conditions = scenario["conditions"]
    await session.flush()


async def _seed_simulation_tasks(session: AsyncSession) -> int:
    """幂等发布仿真实训任务（P0-2）：每个场景 JSON 对应一条 TrainingTask。

    任务不配题库（questions 为空），选择题 /tasks 列表按 question_count==0
    自动过滤，不会混入选择题实训。
    """
    from app.scenarios import load_scenarios

    existing = {t.code: t for t in (await session.scalars(select(TrainingTask))).all()}
    count = 0
    for code, scenario in load_scenarios().items():
        task_code = scenario["task_code"]
        if task_code in existing:
            continue
        session.add(
            TrainingTask(
                code=task_code,
                title=scenario["title"],
                description=scenario["description"],
                difficulty=scenario.get("difficulty", 3),
                target_abilities=list(scenario.get("target_abilities") or []),
                knowledge_points=[
                    doc["id"] for doc in (scenario.get("monitor") or {}).get("knowledge_docs") or []
                ],
                required_points=[],
                reference_points=[],
                scenario={
                    "simulation": True,
                    "scenario_code": code,
                    "note": "教学仿真实训，数据均为模拟编造。",
                    "safety_tip": scenario.get("disclaimer", ""),
                },
                max_follow_ups=0,
                estimated_minutes=scenario.get("estimated_minutes", 20),
                status=TaskStatus.published,
            )
        )
        count += 1
    await session.flush()
    if count:
        logger.info("仿真实训任务发布：新增 {} 个", count)
    return count


async def _seed_authoritative_knowledge(session: AsyncSession) -> int:
    """幂等写入 50+ 条可追溯权威知识摘要。"""
    existing = {
        k.knowledge_id: k for k in (await session.scalars(select(KnowledgeItem))).all()
    }
    items = load_authoritative_knowledge()
    model_fields = {
        "title", "major", "position", "job_task", "ability", "knowledge_point",
        "skill_point", "difficulty", "content", "source_type", "source_name",
        "source_no", "page", "chapter", "safety_level", "tags",
    }
    for data in items:
        item = existing.get(data["knowledge_id"])
        if item is None:
            item = KnowledgeItem(knowledge_id=data["knowledge_id"])
            session.add(item)
        previous_content = item.content
        for field in model_fields:
            setattr(item, field, data[field])
        if previous_content != item.content:
            item.vector_embedded = False
            item.qdrant_point_id = None
    await session.flush()
    return len(items)


async def _seed_evidence_relations(session: AsyncSession) -> int:
    """将每条权威知识关联到岗位图谱知识点。"""
    points = (await session.scalars(select(KnowledgePoint))).all()
    point_by_code = {point.code: point for point in points}
    code_by_name = {point.name: point.code for point in points}
    items = (
        await session.scalars(
            select(KnowledgeItem).where(
                KnowledgeItem.safety_level == "权威来源教学摘要"
            )
        )
    ).all()
    authority_item_ids = {item.id for item in items}
    for relation in (await session.scalars(select(KnowledgeEvidenceRelation))).all():
        if relation.knowledge_item_id not in authority_item_ids:
            await session.delete(relation)
    existing = {
        (relation.knowledge_point_id, relation.knowledge_item_id): relation
        for relation in (await session.scalars(select(KnowledgeEvidenceRelation))).all()
    }
    linked = 0
    for item in items:
        point_code = (
            code_by_name.get(item.knowledge_point)
            or EVIDENCE_POINT_OVERRIDES.get(item.knowledge_point)
            or EVIDENCE_ABILITY_FALLBACK.get(item.ability)
        )
        point = point_by_code.get(point_code or "")
        if point is None:
            logger.warning("权威知识 {} 无法关联图谱知识点", item.knowledge_id)
            continue
        key = (point.id, item.id)
        relation = existing.get(key)
        if relation is None:
            relation = KnowledgeEvidenceRelation(
                knowledge_point_id=point.id,
                knowledge_item_id=item.id,
            )
            session.add(relation)
        relation.relation_type = "supports"
        relation.relevance = 1.0 if item.knowledge_point == point.name else 0.85
        linked += 1
    await session.flush()
    return linked


async def _remove_demo_positions(session: AsyncSession) -> int:
    """只清理明确命名的开发测试岗位，不触碰正式岗位和教师业务数据。"""
    demo_positions = (
        await session.scalars(select(Position).where(Position.code.in_(["TEST", "TEST-2"])))
    ).all()
    if not demo_positions:
        return 0
    position_ids = [item.id for item in demo_positions]
    # 与测试岗位直接绑定的实训任务也属于演示数据；正式岗位任务不受影响。
    await session.execute(delete(TrainingTask).where(TrainingTask.position_id.in_(position_ids)))
    for item in demo_positions:
        await session.delete(item)
    await session.flush()
    logger.warning("已清理 {} 个明确标记的开发测试岗位：TEST/TEST-2", len(demo_positions))
    return len(demo_positions)


async def _seed_verified_public_evidence(session: AsyncSession) -> tuple[int, int]:
    """幂等写入经过人工核验的公开岗位时间样本和产业证据。"""
    catalog = load_verified_public_evidence()
    teacher_id = await session.scalar(select(User.id).where(User.username == "teacher"))

    industry_count = 0
    for payload in catalog["industry_evidence"]:
        item = await session.scalar(
            select(IndustryEvidence).where(IndustryEvidence.source_url == payload["source_url"])
        )
        if item is None:
            item = IndustryEvidence(source_url=payload["source_url"])
            session.add(item)
        for field in (
            "title",
            "source_name",
            "source_type",
            "source_no",
            "summary",
            "themes",
            "skills",
            "confidence",
        ):
            setattr(item, field, payload[field])
        item.major = "油气储运工程"
        item.published_at = datetime.fromisoformat(payload["published_at"])
        item.enabled = True
        item.created_by = teacher_id
        industry_count += 1
    await session.flush()

    positions = {
        item.code: item
        for item in (
            await session.scalars(
                select(Position).where(Position.code.in_({
                    payload["position_code"] for payload in catalog["job_postings"]
                }))
            )
        ).all()
    }
    grouped: defaultdict[str, list[dict]] = defaultdict(list)
    for payload in catalog["job_postings"]:
        grouped[payload["position_code"]].append(payload)

    posting_count = 0
    now = datetime.now(UTC)
    for position_code, payloads in grouped.items():
        position = positions.get(position_code)
        if position is None:
            logger.warning("公开岗位证据未找到目标岗位代码：{}", position_code)
            continue
        run = await session.scalar(
            select(PositionDiscoveryRun).where(
                PositionDiscoveryRun.position_id == position.id,
                PositionDiscoveryRun.error_summary == VERIFIED_EVIDENCE_RUN_MARKER,
            )
        )
        if run is None:
            run = PositionDiscoveryRun(
                position_id=position.id,
                status="completed",
                query_terms=["人工核验公开岗位证据"],
                source_domains=sorted({payload["source_url"].split("/")[2] for payload in payloads}),
                error_summary=VERIFIED_EVIDENCE_RUN_MARKER,
                completed_at=now,
            )
            session.add(run)
            await session.flush()
        run.status = "completed"
        run.found_count = len(payloads)
        run.saved_count = len(payloads)
        run.completed_at = now

        for payload in payloads:
            url_hash = hashlib.sha256(payload["source_url"].encode("utf-8")).hexdigest()
            snapshot = await session.scalar(
                select(JobPostingSnapshot).where(
                    JobPostingSnapshot.discovery_run_id == run.id,
                    JobPostingSnapshot.source_url_hash == url_hash,
                )
            )
            if snapshot is None:
                snapshot = JobPostingSnapshot(
                    position_id=position.id,
                    discovery_run_id=run.id,
                    source_url=payload["source_url"],
                    source_url_hash=url_hash,
                )
                session.add(snapshot)
            for field in ("title", "company", "region", "source_name", "snippet", "skills", "match_score"):
                setattr(snapshot, field, payload[field])
            snapshot.content = payload["snippet"]
            snapshot.content_hash = hashlib.sha256(payload["snippet"].encode("utf-8")).hexdigest()
            snapshot.published_at = datetime.fromisoformat(payload["published_at"])
            snapshot.published_at_raw = payload["published_at_raw"]
            snapshot.published_at_source = "page_explicit"
            snapshot.date_confidence = (
                "high" if payload["source_tier"].startswith("enterprise_official") else "medium"
            )
            snapshot.date_parse_reason = payload["verification_note"]
            snapshot.metadata_json = {
                "curated_public_evidence": True,
                "catalog_version": catalog["catalog_version"],
                "source_tier": payload["source_tier"],
                "verification_note": payload["verification_note"],
                "privacy_boundary": "公开招聘信息，不含求职者个人信息",
            }
            posting_count += 1
    await session.flush()
    return posting_count, industry_count


async def seed(reset: bool = False) -> None:
    setup_logging()
    async with engine.begin() as conn:
        # 开发环境便捷建表兜底；生产以 alembic upgrade head 为准
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_upgrade_legacy_schema)
    async with AsyncSessionLocal() as session:
        if reset:
            for model in [
                ProgramAdjustmentProposal, CurriculumCourse, CurriculumProgram, IndustryEvidence,
                AdminAuditLog, FeatureConfig,
                PositionAnalysisRun, JobPostingSnapshot, PositionDiscoveryRun,
                WorkflowExecutionLog, WorkflowInstance, TeachingPlan, EvaluationResult,
                TrainingActionEvent,
                TrainingChoiceAnswer, StudentAnswer, TrainingSession, TrainingOption,
                TrainingQuestion, TrainingScenario, TrainingTask, LearningRecommendation,
                ErrorRecord, AbilityEvidence, AbilityHistory, AbilityScore, KnowledgeEvidenceRelation,
                KnowledgeChunk, SkillPoint, KnowledgePoint, KnowledgeItem, TaskAbilityRelation,
                PositionAbilityRelation, JobTask,
                Ability, Position, Major, ProfessionalGroup, ChatMessage, ChatSession, User,
            ]:
                await session.execute(delete(model))
            logger.warning("已清空全部业务表（--reset，仅开发环境）")
        removed_demo_count = await _remove_demo_positions(session)
        ability_ids = await _seed_abilities(session)
        position_ids, task_ids_by_position = await _seed_positions(session)
        primary_task_ids = task_ids_by_position["P-PIPE-STATION"]
        await _seed_knowledge_points(session, ability_ids, primary_task_ids)
        await _seed_graph_relations(
            session,
            position_ids,
            ability_ids,
            task_ids_by_position,
        )
        major_count, major_link_count = await _seed_professional_group(session)
        await _seed_users(session)
        from app.services.admin_governance import ensure_default_features
        await ensure_default_features(session)
        await _seed_training_tasks(session)
        await _seed_training_questions(session)
        simulation_task_count = await _seed_simulation_tasks(session)
        knowledge_count = await _seed_authoritative_knowledge(session)
        evidence_count = await _seed_evidence_relations(session)
        posting_count, industry_count = await _seed_verified_public_evidence(session)
        from app.services.knowledge_chunks import backfill_file_chunks

        file_chunk_count = await backfill_file_chunks(session)
        await session.commit()
    logger.info(
        "种子数据完成：清理{}个测试岗位/{}条可核验岗位样本/{}条产业证据/{}条权威知识/{}条权威关系/{}个历史文件分块/{}个仿真任务/{}个专业({}条major_id回填)已就绪",
        removed_demo_count,
        posting_count,
        industry_count,
        knowledge_count,
        evidence_count,
        file_chunk_count,
        simulation_task_count,
        major_count,
        major_link_count,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="清空后重新种子（仅开发）")
    args = parser.parse_args()
    asyncio.run(seed(reset=args.reset))


if __name__ == "__main__":
    main()
