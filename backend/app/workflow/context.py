"""WorkflowContext — 工作流运行上下文（第十五节）。

基于 Pydantic，支持 context.model_dump() 并保存为 JSON，用于持久化与中断恢复。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import TrainingStage
from app.workflow.enums import WorkflowState


class RetrievedDoc(BaseModel):
    """检索到的知识片段。"""

    knowledge_id: str = ""
    title: str = ""
    content: str = ""
    source_name: str = ""
    source_no: str = ""
    chapter: str = ""
    page: int | None = None
    rerank_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: str  # user / assistant / system
    content: str


class WorkflowContext(BaseModel):
    """贯穿一次工作流执行的上下文。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, use_enum_values=True)

    # 标识
    workflow_id: str = ""
    session_id: str = ""
    user_id: int | None = None
    role: str = "student"

    # 路由
    intent: str | None = None  # qa / training / task_gen
    mode: str = "qa"
    current_node: str = ""
    current_stage: str = TrainingStage.init.value  # type: ignore[assignment]
    next_node: str | None = None
    state: WorkflowState = WorkflowState.PENDING

    # 输入
    user_input: str = ""
    task_id: int | None = None
    current_task: dict[str, Any] = Field(default_factory=dict)

    # RAG
    retrieved_documents: list[RetrievedDoc] = Field(default_factory=list)
    student_answer: str = ""

    # 评价
    evaluation_result: dict[str, Any] | None = None
    score: float | None = None
    ability_scores: dict[str, float] = Field(default_factory=dict)

    # 安全
    safety_level: str = "safe"  # safe / caution / blocked

    # 会话消息
    messages: list[Message] = Field(default_factory=list)
    attempt_count: int = 0
    follow_up_count: int = 0
    max_follow_ups: int = 3

    # 结构化输出（Intent/Task/Eval 等）
    structured: dict[str, Any] = Field(default_factory=dict)

    # 杂项与错误
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str = ""

    # ---- 便捷方法 ----
    def add_message(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))

    def reset_for_resume(self) -> None:
        """恢复运行前清理一次性错误状态。"""
        self.error = ""
        self.next_node = None

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> "WorkflowContext":
        return cls.model_validate_json(data)


__all__ = ["WorkflowContext", "RetrievedDoc", "Message"]
