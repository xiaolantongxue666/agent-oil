"""领域枚举：用户角色、六维能力键、任务状态等。

六维能力的具体名称与权重存于数据库 Ability 表，此处仅定义稳定键值，
避免散落硬编码。
"""

from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"


class AbilityKey(str, Enum):
    """六维岗位能力键。"""

    process_understanding = "process_understanding"  # 工艺流程认知
    equipment_recognition = "equipment_recognition"  # 设备认知
    instrument_parameter = "instrument_parameter"  # 参数与仪表认知
    abnormal_detection = "abnormal_detection"  # 异常识别
    safety_awareness = "safety_awareness"  # 安全风险辨识
    standard_recording = "standard_recording"  # 规范表达与记录


ABILITY_CN: dict[AbilityKey, str] = {
    AbilityKey.process_understanding: "工艺流程认知",
    AbilityKey.equipment_recognition: "设备认知",
    AbilityKey.instrument_parameter: "参数与仪表认知",
    AbilityKey.abnormal_detection: "异常识别",
    AbilityKey.safety_awareness: "安全风险辨识",
    AbilityKey.standard_recording: "规范表达与记录",
}


class TaskStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class TrainingStage(str, Enum):
    """实训会话阶段。

    init/answering/evaluating/follow_up/scoring/finished 为选择题实训阶段；
    briefing→observe→diagnose→risk_assess→decision→record 为 P0-2
    操作型仿真实训阶段（观察→诊断→风险判断→教学处置→规范记录），
    状态推进由后端状态机控制，前端不得任意修改。
    """

    init = "init"
    answering = "answering"
    evaluating = "evaluating"
    follow_up = "follow_up"
    scoring = "scoring"
    # ---- 操作型仿真实训（P0-2） ----
    briefing = "briefing"
    observe = "observe"
    diagnose = "diagnose"
    risk_assess = "risk_assess"
    decision = "decision"
    record = "record"
    finished = "finished"


SIMULATION_STAGE_FLOW: tuple[TrainingStage, ...] = (
    TrainingStage.briefing,
    TrainingStage.observe,
    TrainingStage.diagnose,
    TrainingStage.risk_assess,
    TrainingStage.decision,
    TrainingStage.record,
    TrainingStage.finished,
)
"""仿真实训阶段推进顺序（状态机唯一定义处）。"""


class EvidenceSourceType(str, Enum):
    """能力证据来源类型（P0-1 统一能力证据模型）。

    权重数值不写死在此处，统一由 Settings.ability_evidence_weight() 提供。
    """

    knowledge_quiz = "knowledge_quiz"  # 知识测验（题库答题）
    scenario_choice = "scenario_choice"  # 岗位情境选择题实训
    scenario_diagnosis = "scenario_diagnosis"  # 仿真实训：异常诊断提交（P0-2 接入）
    operation_event = "operation_event"  # 仿真实训：操作行为事件（P0-2 接入）
    teacher_assessment = "teacher_assessment"  # 教师评价


class ConfidenceLevel(str, Enum):
    """能力评价置信度（由证据数量与来源类型数决定，非模型判断）。"""

    low = "low"
    medium = "medium"
    high = "high"
