from pathlib import Path

from app.database import SessionLocal
from app.models import AnalysisReport, AnalysisTask, InterviewAnswer
from app.services.audio_processing import normalize_audio
from app.services.content_analyzer import build_analysis_report
from app.services.question_bank import get_question
from app.services.speech_analyzer import analyze_audio
from app.settings import PROCESSED_AUDIO_DIR


def process_analysis_task(task_id: str) -> None:
    database = SessionLocal()
    try:
        task = database.get(AnalysisTask, task_id)
        if task is None:
            return
        answer = database.get(InterviewAnswer, task.answer_id)
        if answer is None:
            task.status = "failed"
            task.error_message = "回答记录不存在"
            database.commit()
            return

        task.status = "processing"
        task.error_message = None
        database.commit()

        normalized_path = PROCESSED_AUDIO_DIR / f"{answer.id}.wav"
        normalize_audio(Path(answer.audio_path), normalized_path)
        analysis = analyze_audio(normalized_path)
        question = get_question(answer.question_id)
        if question is None:
            raise RuntimeError("题目不存在，无法生成分析报告")
        report = build_analysis_report(
            question,
            analysis["transcript"],
            analysis["metrics"],
        )

        answer.normalized_audio_path = str(normalized_path)
        answer.transcript = analysis["transcript"]
        answer.metrics_json = analysis["metrics"]
        answer.analysis_report = AnalysisReport(
            answer_id=answer.id,
            engine_version=report["engine_version"],
            report_json=report,
        )
        task.status = "completed"
        database.commit()
    except Exception as exc:  # noqa: BLE001 - background task must persist failure
        database.rollback()
        task = database.get(AnalysisTask, task_id)
        if task is not None:
            task.status = "failed"
            task.error_message = str(exc)[:500]
            database.commit()
    finally:
        database.close()
