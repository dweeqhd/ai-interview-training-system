from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db, init_database
from app.models import AnalysisReport, AnalysisTask, InterviewAnswer, TrainingSession
from app.schemas import (
    AnalysisTaskResponse,
    AnswerResponse,
    HealthStatus,
    HistoryItem,
    Question,
    RoleSummary,
    SessionCreate,
    SessionResponse,
    TranscriptUpdate,
)
from app.services.analysis_jobs import process_analysis_task
from app.services.audio_processing import AudioProcessingError, probe_audio_duration
from app.services.content_analyzer import build_analysis_report
from app.services.question_bank import get_question, get_questions, get_roles
from app.settings import MAX_AUDIO_BYTES, UPLOAD_DIR, ensure_runtime_directories


ALLOWED_AUDIO_EXTENSIONS = {".wav", ".webm", ".mp3", ".m4a", ".ogg", ".flac"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_runtime_directories()
    init_database()
    yield


app = FastAPI(
    title="AI 面试训练与表达分析系统 API",
    description="为中文模拟面试提供题库与后续分析服务。",
    version="0.3.2",
    lifespan=lifespan,
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
    return HealthStatus(
        status="ok",
        service="ai-interview-api",
        stage=5,
        speech_environment="cpu-ready",
    )


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


def _answer_response(answer: InterviewAnswer) -> AnswerResponse:
    original_transcript = answer.asr_transcript or answer.transcript
    transcript_source = (
        "pending"
        if answer.transcript is None
        else "user_corrected"
        if original_transcript != answer.transcript
        else "asr"
    )
    return AnswerResponse(
        id=answer.id,
        session_id=answer.session_id,
        question_id=answer.question_id,
        duration_sec=answer.duration_sec,
        asr_transcript=original_transcript,
        transcript=answer.transcript,
        transcript_source=transcript_source,
        metrics=answer.metrics_json,
        report=answer.analysis_report.report_json if answer.analysis_report else None,
        created_at=answer.created_at,
        task=AnalysisTaskResponse.model_validate(answer.analysis_task),
    )


@app.post("/api/sessions", response_model=SessionResponse, status_code=201)
def create_training_session(
    payload: SessionCreate,
    database: Session = Depends(get_db),
) -> TrainingSession:
    if not get_questions(payload.role_id):
        raise HTTPException(status_code=404, detail="未找到该岗位")
    training_session = TrainingSession(id=str(uuid4()), role_id=payload.role_id)
    database.add(training_session)
    database.commit()
    database.refresh(training_session)
    return training_session


@app.post(
    "/api/sessions/{session_id}/answers",
    response_model=AnswerResponse,
    status_code=202,
)
async def upload_answer(
    session_id: str,
    background_tasks: BackgroundTasks,
    question_id: str = Form(),
    audio: UploadFile = File(),
    database: Session = Depends(get_db),
) -> AnswerResponse:
    training_session = database.get(TrainingSession, session_id)
    if training_session is None:
        raise HTTPException(status_code=404, detail="训练会话不存在")
    question = get_question(question_id)
    if question is None or question.role_id != training_session.role_id:
        raise HTTPException(status_code=400, detail="题目与训练岗位不匹配")

    extension = Path(audio.filename or "").suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="仅支持 WAV、WebM、MP3、M4A、OGG、FLAC")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    answer_id = str(uuid4())
    upload_path = UPLOAD_DIR / f"{answer_id}{extension}"
    total_bytes = 0
    try:
        with upload_path.open("wb") as target:
            while chunk := await audio.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_AUDIO_BYTES:
                    raise HTTPException(status_code=413, detail="音频文件不能超过 25MB")
                target.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="音频文件为空")
        duration_sec = probe_audio_duration(upload_path)
    except AudioProcessingError as exc:
        if upload_path.exists():
            upload_path.unlink()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        if upload_path.exists():
            upload_path.unlink()
        raise
    finally:
        await audio.close()

    task = AnalysisTask(id=str(uuid4()), answer_id=answer_id, status="queued")
    answer = InterviewAnswer(
        id=answer_id,
        session_id=session_id,
        question_id=question_id,
        original_filename=Path(audio.filename or f"answer{extension}").name,
        content_type=audio.content_type or "application/octet-stream",
        audio_path=str(upload_path),
        duration_sec=duration_sec,
        analysis_task=task,
    )
    database.add(answer)
    database.commit()
    database.refresh(answer)
    background_tasks.add_task(process_analysis_task, task.id)
    return _answer_response(answer)


@app.get("/api/answers/{answer_id}", response_model=AnswerResponse)
def answer_detail(
    answer_id: str,
    database: Session = Depends(get_db),
) -> AnswerResponse:
    statement = (
        select(InterviewAnswer)
        .options(
            selectinload(InterviewAnswer.analysis_task),
            selectinload(InterviewAnswer.analysis_report),
        )
        .where(InterviewAnswer.id == answer_id)
    )
    answer = database.scalar(statement)
    if answer is None:
        raise HTTPException(status_code=404, detail="回答记录不存在")
    return _answer_response(answer)


@app.put("/api/answers/{answer_id}/transcript", response_model=AnswerResponse)
def update_answer_transcript(
    answer_id: str,
    payload: TranscriptUpdate,
    database: Session = Depends(get_db),
) -> AnswerResponse:
    answer = database.scalar(
        select(InterviewAnswer)
        .options(
            selectinload(InterviewAnswer.analysis_task),
            selectinload(InterviewAnswer.analysis_report),
        )
        .where(InterviewAnswer.id == answer_id)
    )
    if answer is None:
        raise HTTPException(status_code=404, detail="回答记录不存在")
    if answer.analysis_task.status != "completed" or answer.metrics_json is None:
        raise HTTPException(status_code=409, detail="语音分析尚未完成，不能修正转写")

    transcript = payload.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="修正后的转写不能为空")
    question = get_question(answer.question_id)
    if question is None:
        raise HTTPException(status_code=400, detail="题目不存在，无法重新生成报告")

    original_transcript = answer.asr_transcript or answer.transcript or ""
    if answer.asr_transcript is None:
        answer.asr_transcript = original_transcript
    answer.transcript = transcript
    report = build_analysis_report(question, transcript, answer.metrics_json)
    report["transcript_source"] = (
        "asr" if transcript == original_transcript else "user_corrected"
    )
    if answer.analysis_report is None:
        answer.analysis_report = AnalysisReport(
            answer_id=answer.id,
            engine_version=report["engine_version"],
            report_json=report,
        )
    else:
        answer.analysis_report.engine_version = report["engine_version"]
        answer.analysis_report.report_json = report
    database.commit()
    return _answer_response(answer)


@app.get("/api/reports/{answer_id}", response_model=AnswerResponse)
def report_detail(
    answer_id: str,
    database: Session = Depends(get_db),
) -> AnswerResponse:
    answer = database.scalar(
        select(InterviewAnswer)
        .options(
            selectinload(InterviewAnswer.analysis_task),
            selectinload(InterviewAnswer.analysis_report),
        )
        .where(InterviewAnswer.id == answer_id)
    )
    if answer is None:
        raise HTTPException(status_code=404, detail="回答记录不存在")
    if answer.analysis_report is None:
        raise HTTPException(status_code=409, detail="分析报告尚未生成")
    return _answer_response(answer)


@app.get("/api/history", response_model=list[HistoryItem])
def training_history(
    role_id: str | None = Query(default=None),
    question_id: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    database: Session = Depends(get_db),
) -> list[HistoryItem]:
    statement = (
        select(InterviewAnswer)
        .join(InterviewAnswer.training_session)
        .options(
            selectinload(InterviewAnswer.analysis_report),
            selectinload(InterviewAnswer.training_session),
        )
        .where(InterviewAnswer.analysis_report.has())
        .order_by(InterviewAnswer.created_at.desc())
        .limit(limit)
    )
    if role_id:
        statement = statement.where(TrainingSession.role_id == role_id)
    if question_id:
        statement = statement.where(InterviewAnswer.question_id == question_id)

    items = []
    for answer in database.scalars(statement).all():
        question = get_question(answer.question_id)
        report = answer.analysis_report.report_json
        if question is None:
            continue
        items.append(
            HistoryItem(
                answer_id=answer.id,
                session_id=answer.session_id,
                question_id=answer.question_id,
                question=question.question,
                category=question.category,
                duration_sec=answer.duration_sec,
                created_at=answer.created_at,
                scores=report["scores"],
                summary=report["summary"],
            )
        )
    return items
