from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.schemas import HealthStatus, Question, RoleSummary
from app.services.question_bank import get_question, get_questions, get_roles


app = FastAPI(
    title="AI 面试训练与表达分析系统 API",
    description="为中文模拟面试提供题库与后续分析服务。",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthStatus)
def health_check() -> HealthStatus:
    return HealthStatus(status="ok", service="ai-interview-api", stage=2)


@app.get("/api/roles", response_model=list[RoleSummary])
def list_roles() -> list[RoleSummary]:
    return get_roles()


@app.get("/api/questions", response_model=list[Question])
def list_questions(
    role_id: str = Query(description="岗位编号，例如 software_developer"),
) -> list[Question]:
    questions = get_questions(role_id)
    if not questions:
        raise HTTPException(status_code=404, detail="未找到该岗位或对应题目")
    return questions


@app.get("/api/questions/{question_id}", response_model=Question)
def question_detail(question_id: str) -> Question:
    question = get_question(question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="未找到该题目")
    return question

