import csv
import json
from pathlib import Path

from app.services.annotation_evaluator import (
    _asr_metrics_from_pairs,
    _pause_detection_metrics,
    _read_csv,
    _resolve_audio_files,
    evaluate_annotation_package,
    evaluate_synthetic_controls,
)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_gb18030_annotation_csv_is_decoded(tmp_path: Path) -> None:
    path = tmp_path / "annotations.csv"
    path.write_text("audio_id,note\nA001,安静室内\n", encoding="gb18030")

    rows, encoding = _read_csv(path)

    assert encoding == "gb18030"
    assert rows == [{"audio_id": "A001", "note": "安静室内"}]


def test_asr_cer_ignores_spaces_and_punctuation() -> None:
    metrics = _asr_metrics_from_pairs([("你好 world。", "你好word")])

    assert metrics["sample_count"] == 1
    assert metrics["reference_character_count"] == 6
    assert metrics["corpus_cer"] == 0.1667


def test_audio_resolver_skips_macos_fork_and_accepts_double_extension(
    tmp_path: Path,
) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "._U001_test.m4a.m4a").write_bytes(b"x" * 176)
    real_audio = audio_dir / "U001_test.m4a.m4a"
    real_audio.write_bytes(b"x" * 2048)

    resolved, issues = _resolve_audio_files(
        [{"audio_id": "A001", "file_name": "U001_test.m4a"}], audio_dir
    )

    assert resolved == {"A001": real_audio}
    assert issues == []


def test_pause_detection_uses_one_to_one_interval_matching() -> None:
    pauses = [
        {
            "audio_id": "A001",
            "row_status": "新增",
            "is_valid": "是",
            "start_sec": "1.0",
            "end_sec": "2.0",
            "duration_sec": "1.0",
        },
        {
            "audio_id": "A001",
            "row_status": "新增",
            "is_valid": "是",
            "start_sec": "4.0",
            "end_sec": "5.0",
            "duration_sec": "1.0",
        },
    ]
    analyses = {
        "A001": {
            "metrics": {
                "pauses": [
                    {"start_ms": 1100, "end_ms": 1900},
                    {"start_ms": 7000, "end_ms": 7800},
                ]
            }
        }
    }

    metrics = _pause_detection_metrics(pauses, analyses)

    assert metrics["true_positive"] == 1
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
    assert metrics["f1"] == 0.5


def test_evaluator_keeps_content_sample_when_pause_rows_are_missing(
    tmp_path: Path,
) -> None:
    csv_dir = tmp_path / "csv_templates"
    _write_csv(
        csv_dir / "00_tasks.csv",
        ["audio_id"],
        [{"audio_id": "A001"}],
    )
    _write_csv(
        csv_dir / "01_metadata.csv",
        ["audio_id", "participant_id", "duration_sec", "split"],
        [
            {
                "audio_id": "A001",
                "participant_id": "U001",
                "duration_sec": 70,
                "split": "dev",
            }
        ],
    )
    _write_csv(
        csv_dir / "02_transcripts.csv",
        ["audio_id", "annotator_id", "question_id", "asr_text", "corrected_text"],
        [
            {
                "audio_id": "A001",
                "annotator_id": "L01",
                "question_id": "dev_project_01",
                "asr_text": "我负责接口开发",
                "corrected_text": "我负责接口开发",
            }
        ],
    )
    _write_csv(
        csv_dir / "03_pauses.csv",
        ["audio_id", "annotator_id", "row_status"],
        [],
    )
    _write_csv(
        csv_dir / "04_labels.csv",
        ["audio_id", "annotator_id", "label_name", "is_present"],
        [
            {
                "audio_id": "A001",
                "annotator_id": "L01",
                "label_name": "个人职责",
                "is_present": "是",
            }
        ],
    )
    score_row = {
        "audio_id": "A001",
        "annotator_id": "L01",
        "relevance_score_0_20": 15,
        "structure_score_0_20": 15,
        "evidence_score_0_20": 15,
        "speaking_rate_score_0_10": 8,
        "pause_score_0_15": 12,
        "filler_duration_score_0_15": 12,
    }
    _write_csv(
        csv_dir / "05_scores.csv",
        list(score_row),
        [score_row],
    )
    _write_csv(
        csv_dir / "06_consensus.csv",
        list(score_row),
        [],
    )

    report = evaluate_annotation_package(tmp_path)

    assert report["source_summary"]["completed_audio_count"] == 1
    assert report["source_summary"]["evaluated_audio_count"] == 1
    assert report["asr"]["corpus_cer"] == 0
    assert any(
        issue["code"] == "pause_annotations_missing"
        for issue in report["data_quality"]["issues"]
    )
    json.dumps(report, ensure_ascii=False)


def test_tracked_synthetic_controls_pass_current_rule_version() -> None:
    project_root = Path(__file__).resolve().parents[2]
    controls = project_root / "data" / "evaluation" / "synthetic_content_controls.v1.json"

    result = evaluate_synthetic_controls(controls)

    assert result["sample_count"] == 18
    assert result["check_count"] == 136
    assert result["passed_count"] == 136
    assert result["failures"] == []
