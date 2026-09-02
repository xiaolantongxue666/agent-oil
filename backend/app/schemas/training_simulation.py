"""仿真实训（P0-2）Schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SimulationEventRequest(BaseModel):
    """学生行为事件提交。评分字段（分值/答案）一律由服务端按场景配置计算。"""

    event_type: str = Field(..., min_length=1, max_length=48)
    event_code: str = Field("", max_length=64)
    target_type: str = Field("", max_length=32)
    target_id: str = Field("", max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
