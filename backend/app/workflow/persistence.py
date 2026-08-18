"""Workflow 持久化：上下文快照与执行日志（第六十一、六十二节）。

支持中断恢复：服务不可用时保存 context/state，恢复后从当前节点继续。
不得记录 API Key / 密码 / Authorization Header。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkflowExecutionLog, WorkflowInstance
from app.workflow.context import WorkflowContext
from app.workflow.enums import WorkflowState


class WorkflowPersistence:
    """工作流持久化服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_instance(self, context: WorkflowContext, workflow_type: str) -> WorkflowInstance:
        """保存/更新工作流实例。"""
        inst: WorkflowInstance | None = None
        if context.workflow_id:
            inst = await self.session.get(WorkflowInstance, int(context.workflow_id))
        if inst is None:
            inst = WorkflowInstance(workflow_type=workflow_type)
            self.session.add(inst)
            await self.session.flush()
            context.workflow_id = str(inst.id)
        inst.workflow_type = workflow_type
        inst.state = context.state.value if isinstance(context.state, WorkflowState) else str(context.state)
        inst.current_node = context.current_node
        inst.context_json = context.model_dump(mode="json")
        inst.attempt_count = context.attempt_count
        inst.error = context.error
        inst.finished = context.state in (WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.SUCCESS)
        if inst.finished:
            inst.finished_at = datetime.now(timezone.utc)
        if context.session_id:
            inst.session_id = context.session_id
        if context.user_id:
            inst.user_id = context.user_id
        await self.session.flush()
        return inst

    async def load_instance(self, workflow_id: int) -> WorkflowContext | None:
        """从实例恢复上下文。"""
        inst = await self.session.get(WorkflowInstance, workflow_id)
        if inst is None:
            return None
        ctx = WorkflowContext.from_json(inst.context_json or "{}")
        ctx.workflow_id = str(inst.id)
        ctx.current_node = inst.current_node or ctx.current_node
        ctx.state = WorkflowState(inst.state) if inst.state else ctx.state  # type: ignore[arg-type]
        return ctx

    async def log_node(
        self,
        workflow_id: int,
        node_name: str,
        *,
        input_summary: str = "",
        output_summary: str = "",
        status: str = "SUCCESS",
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
        error_type: str = "",
        payload: dict[str, Any] | None = None,
    ) -> WorkflowExecutionLog:
        """记录一次节点执行（脱敏，不含敏感信息）。"""
        log = WorkflowExecutionLog(
            workflow_id=workflow_id,
            node_name=node_name,
            input_summary=_truncate(input_summary),
            output_summary=_truncate(output_summary),
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            error_type=error_type,
            payload=payload or {},
        )
        self.session.add(log)
        await self.session.flush()
        return log


def _truncate(s: str, limit: int = 500) -> str:
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


class NodeTimer:
    """节点计时上下文管理器。"""

    def __init__(self) -> None:
        self.started: float = 0.0
        self.started_at: datetime | None = None

    def __enter__(self) -> "NodeTimer":
        self.started = time.perf_counter()
        self.started_at = datetime.now(timezone.utc)
        return self

    def __exit__(self, *exc: object) -> None:
        self.finished_at = datetime.now(timezone.utc)
        self.duration_ms = int((time.perf_counter() - self.started) * 1000)


__all__ = ["WorkflowPersistence", "NodeTimer"]
