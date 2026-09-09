from pydantic import BaseModel, Field


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

