"""情境实训 Schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TrainingStartRequest(BaseModel):
    task_code: str = Field(..., min_length=1, max_length=64)


class TrainingChoiceSubmitRequest(BaseModel):
    question_id: int = Field(..., gt=0)
    option_id: int = Field(..., gt=0)


class TrainingTaskOut(BaseModel):
    id: int
    code: str
    title: str
    description: str = ""
    difficulty: int = 2
    target_abilities: list[str] = Field(default_factory=list)
    estimated_minutes: int = 15
    max_follow_ups: int = 3
    mode: str = "choice"
    question_count: int = 0

    model_config = {"from_attributes": True}


class TrainingSessionOut(BaseModel):
    id: int
    task_code: str = ""
    task_title: str = ""
    stage: str = "init"
    attempt_count: int = 0
    follow_up_count: int = 0
    max_follow_ups: int = 3
    finished: bool = False
    current_coach_question: str = ""
    mode: str = "choice"
    question_count: int = 0
    answered_count: int = 0
    current_question: dict[str, Any] | None = None
    answer_records: list[dict[str, Any]] = Field(default_factory=list)
    last_answer_feedback: dict[str, Any] | None = None
    scenario_text: str = ""
    messages: list[dict[str, str]] = Field(default_factory=list)
    evidence_citations: list[dict[str, Any]] = Field(default_factory=list)
    evaluation: dict[str, Any] | None = None
    created_at: str = ""

    model_config = {"from_attributes": True}


__all__ = [
    "TrainingStartRequest",
    "TrainingChoiceSubmitRequest",
    "TrainingTaskOut",
    "TrainingSessionOut",
]
