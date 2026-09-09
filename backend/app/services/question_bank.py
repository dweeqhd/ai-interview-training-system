import json
from functools import lru_cache
from pathlib import Path

from app.schemas import Question, RoleSummary


PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUESTION_BANK_FILE = (
    PROJECT_ROOT / "data" / "question_bank" / "software_developer.draft.json"
)


class QuestionBankError(RuntimeError):
    """Raised when the local question bank cannot be loaded."""


@lru_cache(maxsize=1)
def load_question_bank() -> dict:
    try:
        with QUESTION_BANK_FILE.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionBankError(f"无法读取题库：{QUESTION_BANK_FILE}") from exc


def get_roles() -> list[RoleSummary]:
    bank = load_question_bank()
    role = bank["role"]
    questions = bank.get("questions", [])
    return [
        RoleSummary(
            id=role["id"],
            name=role["name"],
            question_count=len(questions),
            review_status=bank.get("status", "unknown"),
        )
    ]


def get_questions(role_id: str) -> list[Question]:
    bank = load_question_bank()
    role = bank["role"]
    if role_id != role["id"]:
        return []

    return [
        Question(
            id=item["id"],
            role_id=role["id"],
            category=item["category"],
            question=item["question"],
            expected_points=item["expected_points"],
            star_expected=item["star_expected"],
            duration_sec=tuple(item["duration_sec"]),
            review_status=item["review_status"],
        )
        for item in bank.get("questions", [])
    ]


def get_question(question_id: str) -> Question | None:
    bank = load_question_bank()
    role_id = bank["role"]["id"]
    for item in bank.get("questions", []):
        if item["id"] == question_id:
            return Question(
                id=item["id"],
                role_id=role_id,
                category=item["category"],
                question=item["question"],
                expected_points=item["expected_points"],
                star_expected=item["star_expected"],
                duration_sec=tuple(item["duration_sec"]),
                review_status=item["review_status"],
            )
    return None

