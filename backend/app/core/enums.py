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
    """实训会话阶段。"""

    init = "init"
    answering = "answering"
    evaluating = "evaluating"
    follow_up = "follow_up"
    scoring = "scoring"
    finished = "finished"
