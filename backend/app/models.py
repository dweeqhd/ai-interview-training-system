from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TrainingSession(Base):
    __tablename__ = "training_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    answers: Mapped[list["InterviewAnswer"]] = relationship(
        back_populates="training_session", cascade="all, delete-orphan"
    )


class InterviewAnswer(Base):
    __tablename__ = "interview_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("training_sessions.id"), index=True
    )
    question_id: Mapped[str] = mapped_column(String(80), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    audio_path: Mapped[str] = mapped_column(Text)
    normalized_audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_sec: Mapped[float] = mapped_column(Float)
    asr_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    training_session: Mapped[TrainingSession] = relationship(
        back_populates="answers"
    )
    analysis_task: Mapped["AnalysisTask"] = relationship(
        back_populates="answer", cascade="all, delete-orphan", uselist=False
    )
    analysis_report: Mapped["AnalysisReport | None"] = relationship(
        back_populates="answer", cascade="all, delete-orphan", uselist=False
    )


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    answer_id: Mapped[str] = mapped_column(
        ForeignKey("interview_answers.id"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    answer: Mapped[InterviewAnswer] = relationship(back_populates="analysis_task")


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    answer_id: Mapped[str] = mapped_column(
        ForeignKey("interview_answers.id"), primary_key=True
    )
    engine_version: Mapped[str] = mapped_column(String(40))
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    answer: Mapped[InterviewAnswer] = relationship(back_populates="analysis_report")
