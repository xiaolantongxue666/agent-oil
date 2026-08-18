"""Workflow 异常体系。

区分可重试错误、服务不可用（可恢复）与不可恢复错误。
"""

from __future__ import annotations


class WorkflowError(Exception):
    """工作流基础异常。"""


class RetryableNodeError(WorkflowError):
    """节点执行失败但可重试。"""


class ServiceUnavailableError(WorkflowError):
    """依赖服务（如百炼）暂时不可用——可中断恢复。"""


class WorkflowResumeError(WorkflowError):
    """恢复工作流失败。"""


class MaxFollowUpExceeded(WorkflowError):
    """追问次数超上限。"""


__all__ = [
    "WorkflowError",
    "RetryableNodeError",
    "ServiceUnavailableError",
    "WorkflowResumeError",
    "MaxFollowUpExceeded",
]
