from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-interview-api",
        "stage": 2,
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

