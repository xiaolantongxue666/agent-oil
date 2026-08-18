"""Workflow 状态机枚举（第十八节）。

状态必须持久化，支持中断恢复。
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    WAITING_INPUT = "WAITING_INPUT"
    RETRY = "RETRY"
    FAILED = "FAILED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    COMPLETED = "COMPLETED"


class NodeStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    RETRY = "RETRY"


# 终态：进入后不再运行
TERMINAL_STATES = frozenset(
    {WorkflowState.SUCCESS, WorkflowState.FAILED, WorkflowState.COMPLETED, WorkflowState.SERVICE_UNAVAILABLE}
)
# 暂停态：可恢复
PAUSED_STATES = frozenset({WorkflowState.WAITING_INPUT, WorkflowState.SERVICE_UNAVAILABLE, WorkflowState.RETRY})


__all__ = ["WorkflowState", "NodeStatus", "TERMINAL_STATES", "PAUSED_STATES"]
