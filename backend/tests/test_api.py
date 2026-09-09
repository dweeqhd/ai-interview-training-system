import app.main as main_module
import app.services.analysis_jobs as jobs_module
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AnalysisReport, InterviewAnswer
from app.services.content_analyzer import build_analysis_report
from app.services.question_bank import get_question
from app.services.speech_analyzer import calculate_metrics


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        database = testing_session()
        try:
            yield database
        finally:
            database.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(main_module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(main_module, "probe_audio_duration", lambda _: 10.0)
    monkeypatch.setattr(main_module, "process_analysis_task", lambda _: None)
    yield testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_health_check() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-interview-api",
        "stage": 4,
        "speech_environment": "cpu-ready",
    }


def test_list_roles_returns_software_developer() -> None:
    response = client.get("/api/roles")
    assert response.status_code == 200
    roles = response.json()
    assert len(roles) == 1
    assert roles[0]["id"] == "software_developer"
    assert roles[0]["question_count"] == 15


def test_list_questions_returns_all_draft_questions() -> None:
    response = client.get(
        "/api/questions", params={"role_id": "software_developer"}
    )
    assert response.status_code == 200
    questions = response.json()
    assert len(questions) == 15
    assert questions[0]["review_status"] == "pending"


def test_unknown_role_returns_404() -> None:
    response = client.get("/api/questions", params={"role_id": "unknown"})
    assert response.status_code == 404


def test_question_detail_returns_expected_points() -> None:
    response = client.get("/api/questions/dev_project_01")
    assert response.status_code == 200
    payload = response.json()
    assert payload["category"] == "项目经历"
    assert "个人职责" in payload["expected_points"]


def test_unknown_question_returns_404() -> None:
    response = client.get("/api/questions/not-found")
    assert response.status_code == 404


def test_create_session_and_upload_answer() -> None:
    session_response = client.post(
        "/api/sessions", json={"role_id": "software_developer"}
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["id"]

    upload_response = client.post(
        f"/api/sessions/{session_id}/answers",
        data={"question_id": "dev_project_01"},
        files={"audio": ("answer.wav", b"test-audio", "audio/wav")},
    )
    assert upload_response.status_code == 202
    payload = upload_response.json()
    assert payload["duration_sec"] == 10.0
    assert payload["task"]["status"] == "queued"

    detail_response = client.get(f"/api/answers/{payload['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["question_id"] == "dev_project_01"


def test_upload_rejects_unsupported_extension() -> None:
    session_id = client.post(
        "/api/sessions", json={"role_id": "software_developer"}
    ).json()["id"]
    response = client.post(
        f"/api/sessions/{session_id}/answers",
        data={"question_id": "dev_project_01"},
        files={"audio": ("answer.txt", b"not-audio", "text/plain")},
    )
    assert response.status_code == 415


def test_pause_and_speaking_rate_metrics_are_explainable() -> None:
    segments = [
        {"start_ms": 0, "end_ms": 1000, "text": "第一句"},
        {"start_ms": 1800, "end_ms": 2800, "text": "第二句"},
        {"start_ms": 4500, "end_ms": 5500, "text": "第三句"},
    ]
    metrics = calculate_metrics("嗯我负责API，然后优化", segments, 6.0)
    assert metrics["pause_count"] == 2
    assert metrics["long_pause_count"] == 1
    assert metrics["longest_pause_sec"] == 1.7
    assert metrics["filler_details"] == {"嗯": 1, "然后": 1}
    assert metrics["speaking_rate_per_min"] > 0


def test_rule_report_keeps_scores_and_evidence_explainable() -> None:
    question = get_question("dev_project_01")
    assert question is not None
    metrics = calculate_metrics(
        "",
        [{"start_ms": 0, "end_ms": 50000, "text": ""}],
        65.0,
    )
    transcript = (
        "当时我们要开发一个面试训练系统，我负责后端接口和数据库设计。"
        "目标是在两周内跑通录音分析流程。"
        "我采用FastAPI实现接口，并编写自动化测试。"
        "最终接口响应时间降低30%，项目通过验收。"
    )
    metrics["speech_units"] = 120
    metrics["speaking_rate_per_min"] = 144
    report = build_analysis_report(question, transcript, metrics)

    assert report["engine_version"] == "rules-v1"
    assert report["scores"]["content"] >= 45
    assert report["structure_analysis"]["present_count"] == 4
    assert report["evidence_analysis"]["present_count"] == 4
    assert report["keyword_coverage"]["items"][0]["evidence"]
    assert "不构成录用判断" in report["disclaimer"]


def test_report_and_history_endpoints_return_completed_report(
    isolated_database,
) -> None:
    session_id = client.post(
        "/api/sessions", json={"role_id": "software_developer"}
    ).json()["id"]
    answer_payload = client.post(
        f"/api/sessions/{session_id}/answers",
        data={"question_id": "dev_project_01"},
        files={"audio": ("answer.wav", b"test-audio", "audio/wav")},
    ).json()
    question = get_question("dev_project_01")
    assert question is not None
    transcript = "我负责接口设计，我采用FastAPI实现，最终完成项目并通过测试。"
    metrics = {
        "total_duration_sec": 70.0,
        "speech_duration_sec": 60.0,
        "speech_units": 150,
        "speaking_rate_per_min": 150.0,
        "pause_count": 1,
        "long_pause_count": 0,
        "longest_pause_sec": 0.8,
        "pause_ratio": 0.05,
        "filler_count": 0,
        "filler_details": {},
        "segments": [],
        "pauses": [],
        "metric_note": "测试指标",
    }
    report = build_analysis_report(question, transcript, metrics)
    with isolated_database() as database:
        answer = database.get(InterviewAnswer, answer_payload["id"])
        answer.transcript = transcript
        answer.metrics_json = metrics
        answer.analysis_task.status = "completed"
        answer.analysis_report = AnalysisReport(
            answer_id=answer.id,
            engine_version=report["engine_version"],
            report_json=report,
        )
        database.commit()

    report_response = client.get(f"/api/reports/{answer_payload['id']}")
    assert report_response.status_code == 200
    assert report_response.json()["report"]["scores"]["total"] == report["scores"]["total"]

    history_response = client.get(
        "/api/history",
        params={"role_id": "software_developer", "question_id": "dev_project_01"},
    )
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    assert history[0]["answer_id"] == answer_payload["id"]


def test_background_job_persists_stage_four_report(
    isolated_database,
    monkeypatch,
    tmp_path,
) -> None:
    with isolated_database() as database:
        session = main_module.create_training_session(
            main_module.SessionCreate(role_id="software_developer"),
            database,
        )
        answer = InterviewAnswer(
            id="background-report-answer",
            session_id=session.id,
            question_id="dev_project_01",
            original_filename="answer.wav",
            content_type="audio/wav",
            audio_path=str(tmp_path / "answer.wav"),
            duration_sec=70.0,
            analysis_task=jobs_module.AnalysisTask(
                id="background-report-task",
                status="queued",
            ),
        )
        database.add(answer)
        database.commit()

    metrics = {
        "total_duration_sec": 70.0,
        "speech_duration_sec": 60.0,
        "speech_units": 150,
        "speaking_rate_per_min": 150.0,
        "pause_count": 0,
        "long_pause_count": 0,
        "longest_pause_sec": 0,
        "pause_ratio": 0,
        "filler_count": 0,
        "filler_details": {},
        "segments": [],
        "pauses": [],
        "metric_note": "测试指标",
    }
    monkeypatch.setattr(jobs_module, "SessionLocal", isolated_database)
    monkeypatch.setattr(jobs_module, "PROCESSED_AUDIO_DIR", tmp_path)
    monkeypatch.setattr(jobs_module, "normalize_audio", lambda *_: None)
    monkeypatch.setattr(
        jobs_module,
        "analyze_audio",
        lambda _: {
            "transcript": "我负责接口设计，我采用FastAPI实现，最终完成并通过测试。",
            "metrics": metrics,
        },
    )

    jobs_module.process_analysis_task("background-report-task")

    with isolated_database() as database:
        answer = database.get(InterviewAnswer, "background-report-answer")
        assert answer.analysis_task.status == "completed"
        assert answer.analysis_report.engine_version == "rules-v1"
        assert answer.analysis_report.report_json["scores"]["total"] > 0
