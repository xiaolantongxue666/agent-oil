"""节点统一接口（第十六节）。

每个核心 Node 独立文件，继承 BaseWorkflowNode。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.workflow.context import WorkflowContext


class BaseWorkflowNode(ABC):
    """所有工作流节点的抽象基类。

    子类需：
      - 设置类属性 `name`（节点唯一标识）
      - 实现 `execute(context)`：处理上下文并返回更新后的上下文
      - 可选设置 `context.next_node` 指定下一节点；不设置则由 ConditionalRouter 决定
    """

    name: str = ""

    @abstractmethod
    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        """执行节点逻辑，返回更新后的上下文。"""
        raise NotImplementedError

    async def pre_run(self, context: WorkflowContext) -> WorkflowContext:
        """执行前钩子（日志/校验）。默认直接返回。"""
        return context

    async def post_run(self, context: WorkflowContext) -> WorkflowContext:
        """执行后钩子。默认直接返回。"""
        return context

    async def run(self, context: WorkflowContext) -> WorkflowContext:
        """引擎调用的统一入口：pre -> execute -> post。"""
        context = await self.pre_run(context)
        context = await self.execute(context)
        context = await self.post_run(context)
        return context

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


__all__ = ["BaseWorkflowNode"]
