import app.main as main_module
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
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
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_health_check() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-interview-api",
        "stage": 3,
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
