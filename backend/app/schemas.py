from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RoleSummary(BaseModel):
    id: str
    name: str
    question_count: int = Field(ge=0)
    review_status: str


class Question(BaseModel):
    id: str
    role_id: str
    category: str
    question: str
    expected_points: list[str]
    star_expected: list[str]
    duration_sec: tuple[int, int]
    review_status: str


class HealthStatus(BaseModel):
    status: str
    service: str
    stage: int
    speech_environment: str


class SessionCreate(BaseModel):
    role_id: str = Field(min_length=1, max_length=80)


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    role_id: str
    created_at: datetime


class AnalysisTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class AnswerResponse(BaseModel):
    id: str
    session_id: str
    question_id: str
    duration_sec: float
    transcript: str | None
    metrics: dict[str, Any] | None
    report: dict[str, Any] | None
    created_at: datetime
    task: AnalysisTaskResponse


class HistoryItem(BaseModel):
    answer_id: str
    session_id: str
    question_id: str
    question: str
    category: str
    duration_sec: float
    created_at: datetime
    scores: dict[str, Any]
    summary: str
