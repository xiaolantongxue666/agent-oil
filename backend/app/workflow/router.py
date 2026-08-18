"""条件路由器（ConditionalRouter）。

有限状态机 + 条件路由：为每个节点注册一组 (condition -> target_node) 边，
按顺序评估条件，命中则跳转。用于"是否需要追问"等分支决策。

节点也可在 execute 中直接设置 context.next_node 优先于路由。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Union

from app.workflow.context import WorkflowContext

# 条件：同步或异步，返回 bool
Condition = Callable[[WorkflowContext], Union[bool, Awaitable[bool]]]


@dataclass
class Route:
    target: str  # 目标节点名
    condition: Condition
    description: str = ""


@dataclass
class ConditionalRouter:
    """节点条件路由表。"""

    _routes: dict[str, list[Route]] = field(default_factory=dict)
    _default: dict[str, str] = field(default_factory=dict)

    def add_route(
        self,
        from_node: str,
        target: str,
        condition: Condition,
        description: str = "",
    ) -> "ConditionalRouter":
        self._routes.setdefault(from_node, []).append(Route(target, condition, description))
        return self

    def set_default(self, from_node: str, target: str) -> "ConditionalRouter":
        self._default[from_node] = target
        return self

    async def route(self, context: WorkflowContext, from_node: str) -> str | None:
        """评估条件路由，返回目标节点名；无命中返回默认或 None。"""
        for route in self._routes.get(from_node, []):
            result = route.condition(context)
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[assignment]
            if result:
                return route.target
        return self._default.get(from_node)


__all__ = ["ConditionalRouter", "Route", "Condition"]
