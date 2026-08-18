"""Workflow Engine — 自研有限状态机 + 条件路由（第十四节）。

核心能力：
- 顺序/条件路由执行节点
- WAITING_INPUT 暂停与 resume 恢复
- Retry / Error Handling / ServiceUnavailable 中断恢复
- 节点执行日志
- 最大迭代次数保护，禁止无限循环
"""

from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.workflow.context import WorkflowContext
from app.workflow.enums import PAUSED_STATES, TERMINAL_STATES, NodeStatus, WorkflowState
from app.workflow.exceptions import (
    RetryableNodeError,
    ServiceUnavailableError,
    WorkflowError,
)
from app.workflow.persistence import NodeTimer, WorkflowPersistence
from app.workflow.registry import NodeRegistry
from app.workflow.router import ConditionalRouter


class WorkflowEngine:
    """工作流引擎。"""

    def __init__(
        self,
        registry: NodeRegistry,
        router: ConditionalRouter | None = None,
        persistence: WorkflowPersistence | None = None,
        *,
        max_iterations: int = 200,
        max_retries: int = 3,
    ) -> None:
        self.registry = registry
        self.router = router or ConditionalRouter()
        self.persistence = persistence
        self.max_iterations = max_iterations
        self.max_retries = max_retries

    async def run(
        self,
        workflow_type: str,
        context: WorkflowContext,
        start_node: str | None = None,
    ) -> WorkflowContext:
        """从 start_node（或 context.current_node）开始运行至终态/暂停态。"""
        if start_node:
            context.current_node = start_node
        if not context.current_node:
            raise WorkflowError("缺少起始节点：context.current_node 为空")
        context.state = WorkflowState.RUNNING
        await self._persist(context, workflow_type)
        return await self._loop(workflow_type, context)

    async def resume(self, workflow_type: str, context: WorkflowContext) -> WorkflowContext:
        """恢复运行：从 context.current_node 继续（用于 WAITING_INPUT 后提交输入）。"""
        context.reset_for_resume()
        context.state = WorkflowState.RUNNING
        await self._persist(context, workflow_type)
        return await self._loop(workflow_type, context)

    async def _loop(self, workflow_type: str, context: WorkflowContext) -> WorkflowContext:
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            if context.state in TERMINAL_STATES:
                break
            if context.state in PAUSED_STATES:
                # 暂停态：持久化后退出，等待外部 resume
                await self._persist(context, workflow_type)
                return context

            node_name = context.current_node
            if not node_name or not self.registry.has(node_name):
                context.state = WorkflowState.COMPLETED
                break
            node = self.registry.get(node_name)
            context = await self._exec_node(node, context, workflow_type)

            # 暂停态由节点触发（WAITING_INPUT / SERVICE_UNAVAILABLE）
            if context.state in PAUSED_STATES:
                # 推进到恢复点（next_node），再暂停，使 resume 从消费输入的节点继续
                if context.next_node:
                    context.current_node = context.next_node
                    context.next_node = None
                await self._persist(context, workflow_type)
                return context
            if context.state in TERMINAL_STATES:
                await self._persist(context, workflow_type)
                return context

            # 决定下一节点：优先 context.next_node，否则条件路由
            next_node = context.next_node
            if not next_node:
                next_node = await self.router.route(context, node.name)
            if not next_node:
                context.state = WorkflowState.COMPLETED
                await self._persist(context, workflow_type)
                return context
            context.current_node = next_node
            context.next_node = None

        else:
            # 达到最大迭代次数仍未结束
            logger.error("工作流达到最大迭代次数 {} 仍未结束，强制终止", self.max_iterations)
            context.state = WorkflowState.FAILED
            context.error = f"达到最大迭代次数 {self.max_iterations}"
            await self._persist(context, workflow_type)
        return context

    async def _exec_node(
        self,
        node: Any,
        context: WorkflowContext,
        workflow_type: str,
    ) -> WorkflowContext:
        """执行单个节点：计时、重试、异常映射、日志。"""
        wid = int(context.workflow_id) if context.workflow_id else 0
        timer = NodeTimer()
        timer.__enter__()
        status = NodeStatus.SUCCESS.value
        error_type = ""
        input_summary = _summarize(context)
        try:
            attempts = 0
            while True:
                try:
                    context = await node.run(context)
                    break
                except RetryableNodeError as exc:
                    attempts += 1
                    if attempts > self.max_retries:
                        raise
                    logger.warning("节点 {} 重试 {}/{}：{}", node.name, attempts, self.max_retries, exc)
                    context.attempt_count += 1
                    context.state = WorkflowState.RETRY
                    continue
            # 成功：状态由节点决定；默认保持 RUNNING
            if context.state == WorkflowState.RETRY:
                context.state = WorkflowState.RUNNING
        except ServiceUnavailableError as exc:
            context.state = WorkflowState.SERVICE_UNAVAILABLE
            context.error = str(exc)
            status = NodeStatus.FAILED.value
            error_type = "service_unavailable"
            logger.warning("节点 {} 依赖服务不可用，将中断恢复：{}", node.name, exc)
        except WorkflowError as exc:
            context.state = WorkflowState.FAILED
            context.error = str(exc)
            status = NodeStatus.FAILED.value
            error_type = type(exc).__name__
            logger.error("节点 {} 失败：{}", node.name, exc)
        except Exception as exc:  # noqa: BLE001
            context.state = WorkflowState.FAILED
            context.error = f"{type(exc).__name__}: {exc}"
            status = NodeStatus.FAILED.value
            error_type = type(exc).__name__
            logger.exception("节点 {} 未捕获异常", node.name)
        finally:
            timer.__exit__(None, None, None)
            if self.persistence and wid:
                await self.persistence.log_node(
                    wid,
                    node.name,
                    input_summary=input_summary,
                    output_summary=_summarize(context),
                    status=status,
                    started_at=timer.started_at,
                    finished_at=getattr(timer, "finished_at", None),
                    duration_ms=getattr(timer, "duration_ms", None),
                    error_type=error_type,
                )
        return context

    async def _persist(self, context: WorkflowContext, workflow_type: str) -> None:
        if self.persistence:
            try:
                await self.persistence.upsert_instance(context, workflow_type)
            except Exception as exc:  # noqa: BLE001
                logger.debug("持久化失败（非致命）：{}", exc)


def _summarize(context: WorkflowContext) -> str:
    """脱敏摘要，用于日志（不含密钥/密码）。"""
    return (
        f"node={context.current_node} state={context.state} "
        f"intent={context.intent} attempt={context.attempt_count} "
        f"followups={context.follow_up_count}/{context.max_follow_ups} "
        f"docs={len(context.retrieved_documents)} score={context.score}"
    )


__all__ = ["WorkflowEngine"]
