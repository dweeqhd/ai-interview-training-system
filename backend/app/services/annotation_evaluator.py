import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any

from app.services.content_analyzer import build_analysis_report
from app.services.audio_processing import normalize_audio
from app.services.question_bank import get_question
from app.services.speech_analyzer import (
    FILLER_WORDS,
    SPEECH_METRIC_VERSION,
    analyze_audio,
)


EVALUATION_VERSION = "annotation-evaluation-v1"
SCORE_FIELDS = {
    "relevance": ("relevance_score_0_20", 20),
    "structure": ("structure_score_0_20", 20),
    "evidence": ("evidence_score_0_20", 20),
    "pace": ("speaking_rate_score_0_10", 10),
    "pause": ("pause_score_0_15", 15),
    "filler_duration": ("filler_duration_score_0_15", 15),
}
CSV_PREFIXES = {
    "tasks": "00_",
    "metadata": "01_",
    "transcripts": "02_",
    "pauses": "03_",
    "labels": "04_",
    "scores": "05_",
    "consensus": "06_",
}


class AnnotationEvaluationError(RuntimeError):
    """Raised when an annotation package cannot be evaluated."""


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = path.read_text(encoding=encoding)
            reader = csv.DictReader(text.splitlines())
            if not reader.fieldnames:
                raise AnnotationEvaluationError(f"CSV 缺少表头：{path.name}")
            rows = []
            for raw_row in reader:
                row = {
                    (key or "").strip(): (value or "").strip()
                    for key, value in raw_row.items()
                }
                if any(row.values()):
                    rows.append(row)
            return rows, encoding
        except UnicodeDecodeError:
            continue
    raise AnnotationEvaluationError(f"无法识别 CSV 编码：{path.name}")


def _find_csv_files(annotation_dir: Path) -> dict[str, Path]:
    csv_dir = annotation_dir / "csv_templates"
    if not csv_dir.is_dir():
        csv_dir = annotation_dir
    if not csv_dir.is_dir():
        raise AnnotationEvaluationError(f"标注目录不存在：{annotation_dir}")

    files: dict[str, Path] = {}
    for key, prefix in CSV_PREFIXES.items():
        matches = sorted(csv_dir.glob(f"{prefix}*.csv"))
        if len(matches) != 1:
            raise AnnotationEvaluationError(
                f"需要且只能有一个 {prefix}*.csv，实际找到 {len(matches)} 个"
            )
        files[key] = matches[0]
    return files


def _issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    audio_ids: list[str] | None = None,
) -> None:
    item: dict[str, Any] = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if audio_ids:
        item["count"] = len(audio_ids)
        item["sample_audio_ids"] = sorted(audio_ids)[:10]
    issues.append(item)


def _float_value(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    denominator = left_scale * right_scale
    return round(numerator / denominator, 4) if denominator else None


def _score_alignment(
    pairs: list[tuple[float, float]],
) -> dict[str, float | int | None]:
    if not pairs:
        return {
            "sample_count": 0,
            "human_mean": None,
            "system_mean": None,
            "mae": None,
            "mean_signed_error": None,
            "pearson": None,
        }
    human = [pair[0] for pair in pairs]
    system = [pair[1] for pair in pairs]
    return {
        "sample_count": len(pairs),
        "human_mean": round(fmean(human), 2),
        "system_mean": round(fmean(system), 2),
        "mae": round(fmean(abs(s - h) for h, s in pairs), 2),
        "mean_signed_error": round(fmean(s - h for h, s in pairs), 2),
        "pearson": _pearson(human, system),
    }


def _normalized_characters(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)).lower()


def _edit_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


def _asr_metrics(transcript_rows: list[dict[str, str]]) -> dict[str, Any]:
    pairs = [
        (row.get("asr_text", ""), row.get("corrected_text", ""))
        for row in transcript_rows
    ]
    return _asr_metrics_from_pairs(pairs)


def _asr_metrics_from_pairs(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    sample_rates = []
    total_edits = 0
    total_reference_chars = 0
    for hypothesis_text, reference_text in pairs:
        hypothesis = _normalized_characters(hypothesis_text)
        reference = _normalized_characters(reference_text)
        if not reference:
            continue
        edits = _edit_distance(hypothesis, reference)
        total_edits += edits
        total_reference_chars += len(reference)
        sample_rates.append(edits / len(reference))
    return {
        "sample_count": len(sample_rates),
        "corpus_cer": round(total_edits / total_reference_chars, 4)
        if total_reference_chars
        else None,
        "mean_sample_cer": round(fmean(sample_rates), 4) if sample_rates else None,
        "reference_character_count": total_reference_chars,
        "normalization": "仅比较中文字符、英文字母和数字，忽略空白与标点",
    }


def _speech_proxy_metrics(
    transcript: str,
    duration_sec: float,
    pause_rows: list[dict[str, str]],
) -> dict[str, Any]:
    valid_pauses = []
    for row in pause_rows:
        if row.get("row_status") not in {"新增", "有效停顿"}:
            continue
        if row.get("is_valid") not in {"是", ""}:
            continue
        duration = _float_value(row.get("duration_sec", ""))
        if duration is not None and duration >= 0:
            valid_pauses.append(duration)

    chinese_characters = len(re.findall(r"[\u4e00-\u9fff]", transcript))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", transcript))
    speech_units = chinese_characters + latin_words
    total_pause_sec = sum(valid_pauses)
    speech_duration_sec = max(0.1, duration_sec - total_pause_sec)
    filler_count = sum(transcript.count(word) for word in FILLER_WORDS)
    return {
        "total_duration_sec": duration_sec,
        "speech_duration_sec": round(speech_duration_sec, 2),
        "speech_units": speech_units,
        "speaking_rate_per_min": round(speech_units / speech_duration_sec * 60, 1),
        "pause_count": len(valid_pauses),
        "long_pause_count": sum(duration >= 1.5 for duration in valid_pauses),
        "longest_pause_sec": round(max(valid_pauses, default=0), 2),
        "pause_ratio": round(total_pause_sec / duration_sec, 4)
        if duration_sec
        else 0,
        "filler_count": filler_count,
        "filler_details": {},
        "segments": [],
        "pauses": [],
        "metric_note": "由人工时长和停顿标注构造的开发集代理值，不代表系统 VAD 结果",
    }


def _label_detected(label_name: str, report: dict[str, Any]) -> bool | None:
    keyword_hits = {
        item["point"]: item["hit"] for item in report["keyword_coverage"]["items"]
    }
    structure_hits = {
        item["key"]: item["present"]
        for item in report["structure_analysis"]["dimensions"]
    }
    evidence_hits = {
        item["key"]: item["present"]
        for item in report["evidence_analysis"]["dimensions"]
    }
    checks = {
        "技术栈/基础": keyword_hits.get("教育或专业背景", False)
        or keyword_hits.get("技术能力", False),
        "核心优势": keyword_hits.get("岗位匹配", False),
        "项目背景": keyword_hits.get("项目背景", False)
        or structure_hits.get("S", False),
        "个人职责": evidence_hits.get("responsibility", False)
        or structure_hits.get("T", False),
        "项目成果": evidence_hits.get("result", False)
        or structure_hits.get("R", False),
        "问题现象": keyword_hits.get("问题背景", False)
        or structure_hits.get("S", False),
        "解决过程": keyword_hits.get("排查过程", False)
        or keyword_hits.get("解决方案", False)
        or evidence_hits.get("action", False)
        or structure_hits.get("A", False),
        "最终效果": keyword_hits.get("验证结果", False)
        or evidence_hits.get("result", False)
        or structure_hits.get("R", False),
    }
    return checks.get(label_name)


def _content_label_recall(
    label_rows: list[dict[str, str]],
    reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    comparable = 0
    positive = 0
    positive_detected = 0
    negative = 0
    negative_not_detected = 0
    skipped = 0
    by_label: dict[str, dict[str, int]] = defaultdict(
        lambda: {"comparable": 0, "positive": 0, "positive_detected": 0}
    )
    for row in label_rows:
        report = reports.get(row.get("audio_id", ""))
        if report is None:
            skipped += 1
            continue
        detected = _label_detected(row.get("label_name", ""), report)
        if detected is None or row.get("is_present") not in {"是", "否"}:
            skipped += 1
            continue
        comparable += 1
        bucket = by_label[row["label_name"]]
        bucket["comparable"] += 1
        if row["is_present"] == "是":
            positive += 1
            bucket["positive"] += 1
            if detected:
                positive_detected += 1
                bucket["positive_detected"] += 1
        else:
            negative += 1
            if not detected:
                negative_not_detected += 1

    labels = {}
    for label_name, values in sorted(by_label.items()):
        labels[label_name] = {
            **values,
            "positive_recall": round(
                values["positive_detected"] / values["positive"], 4
            )
            if values["positive"]
            else None,
        }
    return {
        "comparable_label_count": comparable,
        "positive_label_count": positive,
        "positive_detected_count": positive_detected,
        "positive_recall": round(positive_detected / positive, 4)
        if positive
        else None,
        "negative_label_count": negative,
        "negative_specificity": round(negative_not_detected / negative, 4)
        if negative
        else None,
        "skipped_label_count": skipped,
        "by_label": labels,
        "note": "只对能映射到现有规则维度的标签计算；无负例时不能计算精确率或特异度",
    }


def _resolve_audio_files(
    metadata_rows: list[dict[str, str]], audio_dir: Path
) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    candidates = [
        path
        for path in audio_dir.rglob("*")
        if path.is_file() and not path.name.startswith("._") and path.stat().st_size > 1024
    ]
    by_name: dict[str, list[Path]] = defaultdict(list)
    for path in candidates:
        by_name[path.name.lower()].append(path)

    resolved: dict[str, Path] = {}
    issues: list[dict[str, Any]] = []
    for row in metadata_rows:
        audio_id = row.get("audio_id", "")
        requested_name = row.get("file_name", "")
        if not audio_id or not requested_name:
            continue
        matches = by_name.get(requested_name.lower(), [])
        if not matches:
            requested_lower = requested_name.lower()
            matches = [
                path
                for path in candidates
                if path.name.lower().startswith(requested_lower + ".")
            ]
        if len(matches) == 1:
            resolved[audio_id] = matches[0]
        elif not matches:
            _issue(
                issues,
                "error",
                "audio_file_missing",
                "标注元数据中的录音文件未找到",
                [audio_id],
            )
        else:
            _issue(
                issues,
                "error",
                "audio_file_ambiguous",
                "同一个匿名编号匹配到多个录音文件",
                [audio_id],
            )
    return resolved, issues


def analyze_annotation_audio(
    annotation_dir: Path,
    audio_dir: Path,
    cache_dir: Path,
    progress: Any | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    files = _find_csv_files(annotation_dir.resolve())
    metadata_rows, _ = _read_csv(files["metadata"])
    audio_files, issues = _resolve_audio_files(metadata_rows, audio_dir.resolve())
    cache_dir = cache_dir.resolve()
    normalized_dir = cache_dir / "normalized"
    cache_file = cache_dir / "speech-analysis-cache.json"
    cache: dict[str, Any] = {
        "version": 2,
        "speech_metric_version": SPEECH_METRIC_VERSION,
        "items": {},
    }
    if cache_file.is_file():
        try:
            cached_data = json.loads(cache_file.read_text(encoding="utf-8"))
            if (
                cached_data.get("version") == 2
                and cached_data.get("speech_metric_version")
                == SPEECH_METRIC_VERSION
            ):
                cache = cached_data
        except (OSError, json.JSONDecodeError):
            pass

    analyses: dict[str, dict[str, Any]] = {}
    ordered_audio = sorted(audio_files.items())
    for index, (audio_id, source_path) in enumerate(ordered_audio, start=1):
        stat = source_path.stat()
        signature = {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        cached_item = cache["items"].get(audio_id)
        if cached_item and cached_item.get("signature") == signature:
            analyses[audio_id] = cached_item["analysis"]
            if progress:
                progress(audio_id, index, len(ordered_audio), True)
            continue

        if progress:
            progress(audio_id, index, len(ordered_audio), False)
        try:
            normalized_path = normalized_dir / f"{audio_id}.wav"
            normalize_audio(source_path, normalized_path)
            analysis = analyze_audio(normalized_path)
            analyses[audio_id] = analysis
            cache["items"][audio_id] = {
                "signature": signature,
                "analysis": analysis,
            }
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - keep the rest of a batch usable
            _issue(
                issues,
                "error",
                "audio_analysis_failed",
                f"录音分析失败：{type(exc).__name__}",
                [audio_id],
            )
    return analyses, issues


def _pause_detection_metrics(
    pauses: list[dict[str, str]],
    system_analyses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows_by_audio: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pauses:
        if row.get("audio_id"):
            rows_by_audio[row["audio_id"]].append(row)

    true_positive = 0
    false_positive = 0
    false_negative = 0
    evaluated_audio = 0
    reference_count = 0
    detected_count = 0
    for audio_id, rows in rows_by_audio.items():
        analysis = system_analyses.get(audio_id)
        if analysis is None:
            continue
        reference_intervals = []
        for row in rows:
            if row.get("row_status") not in {"新增", "有效停顿"}:
                continue
            if row.get("is_valid") not in {"是", ""}:
                continue
            start = _float_value(row.get("start_sec", ""))
            end = _float_value(row.get("end_sec", ""))
            if start is not None and end is not None and end - start >= 0.5:
                reference_intervals.append((start, end))
        detected_intervals = [
            (pause["start_ms"] / 1000, pause["end_ms"] / 1000)
            for pause in analysis.get("metrics", {}).get("pauses", [])
        ]
        evaluated_audio += 1
        reference_count += len(reference_intervals)
        detected_count += len(detected_intervals)
        used_detected: set[int] = set()
        matched = 0
        for reference_start, reference_end in reference_intervals:
            best_index = None
            best_overlap = 0.0
            for detected_index, (detected_start, detected_end) in enumerate(
                detected_intervals
            ):
                if detected_index in used_detected:
                    continue
                overlap = max(
                    0.0,
                    min(reference_end, detected_end)
                    - max(reference_start, detected_start),
                )
                reference_duration = reference_end - reference_start
                boundary_close = (
                    abs(reference_start - detected_start) <= 0.35
                    and abs(reference_end - detected_end) <= 0.35
                )
                if overlap / reference_duration >= 0.3 or boundary_close:
                    if overlap >= best_overlap:
                        best_overlap = overlap
                        best_index = detected_index
            if best_index is not None:
                used_detected.add(best_index)
                matched += 1
        true_positive += matched
        false_negative += len(reference_intervals) - matched
        false_positive += len(detected_intervals) - matched

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else None
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else None
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {
        "evaluated_audio_count": evaluated_audio,
        "reference_pause_count_0_5_sec": reference_count,
        "detected_pause_count": detected_count,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "matching_rule": "人工停顿≥0.5秒；重叠覆盖人工区间≥30%，或起止边界均相差≤0.35秒",
    }


def _pause_threshold_sweep(
    pauses: list[dict[str, str]],
    system_analyses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    candidates = []
    for threshold_ms in (500, 600, 700, 800, 900, 1000, 1200, 1500):
        adjusted = {}
        for audio_id, analysis in system_analyses.items():
            metrics = dict(analysis.get("metrics", {}))
            segments = metrics.get("segments", [])
            candidate_pauses = []
            for previous, current in zip(segments, segments[1:], strict=False):
                gap_ms = current["start_ms"] - previous["end_ms"]
                if gap_ms >= threshold_ms:
                    candidate_pauses.append(
                        {
                            "start_ms": previous["end_ms"],
                            "end_ms": current["start_ms"],
                            "duration_ms": gap_ms,
                        }
                    )
            metrics["pauses"] = candidate_pauses
            adjusted[audio_id] = {
                "transcript": analysis.get("transcript", ""),
                "metrics": metrics,
            }
        result = _pause_detection_metrics(pauses, adjusted)
        candidates.append(
            {
                "threshold_ms": threshold_ms,
                "detected_pause_count": result["detected_pause_count"],
                "precision": result["precision"],
                "recall": result["recall"],
                "f1": result["f1"],
            }
        )
    best = max(candidates, key=lambda item: item["f1"] or -1)
    return {
        "candidates": candidates,
        "best_dev_threshold_ms": best["threshold_ms"],
        "best_dev_f1": best["f1"],
        "note": "仅用于开发集诊断；锁定阈值前需补齐标注并在独立测试集验证",
    }


def _report_signals(report: dict[str, Any]) -> dict[str, bool]:
    signals = {}
    for item in report["keyword_coverage"]["items"]:
        signals[f"keyword:{item['point']}"] = bool(item["hit"])
    for item in report["structure_analysis"]["dimensions"]:
        signals[f"structure:{item['key']}"] = bool(item["present"])
    for item in report["evidence_analysis"]["dimensions"]:
        signals[f"evidence:{item['key']}"] = bool(item["present"])
    return signals


def evaluate_synthetic_controls(control_file: Path) -> dict[str, Any]:
    try:
        payload = json.loads(control_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnnotationEvaluationError(
            f"无法读取合成控制集：{control_file}"
        ) from exc

    samples = payload.get("samples", [])
    failures = []
    check_count = 0
    passed_count = 0
    case_type_counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        sample_id = sample.get("id", "unknown")
        question = get_question(sample.get("question_id", ""))
        if question is None:
            failures.append(
                {
                    "sample_id": sample_id,
                    "signal": "question_id",
                    "expected": "known_question",
                    "actual": "unknown_question",
                }
            )
            continue
        if sample.get("source_type") != "synthetic_ai":
            failures.append(
                {
                    "sample_id": sample_id,
                    "signal": "source_type",
                    "expected": "synthetic_ai",
                    "actual": sample.get("source_type"),
                }
            )
            continue
        case_type_counts[sample.get("case_type", "未分类")] += 1
        metrics = {
            "total_duration_sec": sum(question.duration_sec) / 2,
            "speech_duration_sec": 60,
            "speech_units": 180,
            "speaking_rate_per_min": 180,
            "pause_count": 0,
            "long_pause_count": 0,
            "longest_pause_sec": 0,
            "pause_ratio": 0,
            "filler_count": 0,
            "pauses": [],
        }
        report = build_analysis_report(question, sample.get("transcript", ""), metrics)
        signals = _report_signals(report)
        for signal in sample.get("expected_present", []):
            check_count += 1
            actual = signals.get(signal)
            if actual is True:
                passed_count += 1
            else:
                failures.append(
                    {
                        "sample_id": sample_id,
                        "signal": signal,
                        "expected": True,
                        "actual": actual,
                    }
                )
        for signal in sample.get("expected_absent", []):
            check_count += 1
            actual = signals.get(signal)
            if actual is False:
                passed_count += 1
            else:
                failures.append(
                    {
                        "sample_id": sample_id,
                        "signal": signal,
                        "expected": False,
                        "actual": actual,
                    }
                )
    return {
        "dataset_version": payload.get("version"),
        "source_type": "synthetic_ai",
        "sample_count": len(samples),
        "case_type_counts": dict(sorted(case_type_counts.items())),
        "check_count": check_count,
        "passed_count": passed_count,
        "pass_rate": round(passed_count / check_count, 4) if check_count else None,
        "failures": failures,
        "note": "AI 合成控制集只用于规则回归和负例覆盖，不能替代真人语音、人工评分或独立测试集",
    }


def evaluate_annotation_package(
    annotation_dir: Path,
    system_analyses: dict[str, dict[str, Any]] | None = None,
    audio_issues: list[dict[str, Any]] | None = None,
    synthetic_controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    annotation_dir = annotation_dir.resolve()
    files = _find_csv_files(annotation_dir)
    tables: dict[str, list[dict[str, str]]] = {}
    encodings: dict[str, str] = {}
    for key, path in files.items():
        tables[key], encodings[key] = _read_csv(path)

    issues: list[dict[str, Any]] = list(audio_issues or [])
    tasks = tables["tasks"]
    metadata = tables["metadata"]
    transcripts = tables["transcripts"]
    pauses = tables["pauses"]
    labels = tables["labels"]
    scores = tables["scores"]
    consensus = tables["consensus"]

    task_ids = {row.get("audio_id", "") for row in tasks if row.get("audio_id")}
    table_ids = {
        key: {row.get("audio_id", "") for row in tables[key] if row.get("audio_id")}
        for key in ("metadata", "transcripts", "pauses", "labels", "scores")
    }
    core_keys = ("metadata", "transcripts", "labels", "scores")
    completed_ids = set.intersection(*(table_ids[key] for key in core_keys))
    missing_completed = sorted(task_ids - completed_ids)
    if missing_completed:
        _issue(
            issues,
            "warning",
            "incomplete_task_coverage",
            "任务清单中的部分录音没有完整的元数据、转写、停顿、内容证据和评分",
            missing_completed,
        )
    missing_pause_ids = sorted(completed_ids - table_ids["pauses"])
    if missing_pause_ids:
        _issue(
            issues,
            "warning",
            "pause_annotations_missing",
            "部分已完成内容标注的录音没有停顿标注表行",
            missing_pause_ids,
        )

    annotators = sorted(
        {
            row.get("annotator_id", "")
            for key in ("transcripts", "pauses", "labels", "scores")
            for row in tables[key]
            if row.get("annotator_id")
        }
    )
    if len(annotators) < 2:
        _issue(
            issues,
            "warning",
            "single_annotator_only",
            "当前只有一名标注员，无法计算标注者间一致性",
        )
    if not consensus:
        _issue(
            issues,
            "warning",
            "consensus_scores_missing",
            "最终共识评分为空，评测将使用现有标注员分数的平均值",
        )

    invalid_scores = []
    for row in scores + consensus:
        for _, (field, maximum) in SCORE_FIELDS.items():
            value = _float_value(row.get(field, ""))
            if value is None or not 0 <= value <= maximum:
                invalid_scores.append(row.get("audio_id", "unknown"))
                break
    if invalid_scores:
        _issue(
            issues,
            "error",
            "invalid_score",
            "存在缺失、非数字或超出量程的人工评分",
            invalid_scores,
        )

    invalid_pauses = []
    for row in pauses:
        if row.get("row_status") not in {"新增", "有效停顿"}:
            continue
        start = _float_value(row.get("start_sec", ""))
        end = _float_value(row.get("end_sec", ""))
        duration = _float_value(row.get("duration_sec", ""))
        if (
            start is None
            or end is None
            or duration is None
            or start < 0
            or end <= start
            or abs((end - start) - duration) > 0.08
        ):
            invalid_pauses.append(row.get("audio_id", "unknown"))
    if invalid_pauses:
        _issue(
            issues,
            "error",
            "invalid_pause_boundary",
            "存在无效停顿边界，或持续时间与起止时间不一致",
            invalid_pauses,
        )

    positive_values = [row.get("is_present") for row in labels]
    if positive_values and all(value == "是" for value in positive_values):
        _issue(
            issues,
            "warning",
            "content_labels_have_no_negative_examples",
            "内容证据标签全部为“是”，只能评估召回，不能评估误报",
        )

    transcript_by_audio = {}
    for row in transcripts:
        audio_id = row.get("audio_id", "")
        if audio_id and row.get("corrected_text") and audio_id not in transcript_by_audio:
            transcript_by_audio[audio_id] = row
    metadata_by_audio = {
        row.get("audio_id", ""): row for row in metadata if row.get("audio_id")
    }
    pauses_by_audio: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in pauses:
        pauses_by_audio[row.get("audio_id", "")].append(row)

    corrected_reports: dict[str, dict[str, Any]] = {}
    system_reports: dict[str, dict[str, Any]] = {}
    for audio_id in sorted(completed_ids):
        transcript_row = transcript_by_audio.get(audio_id)
        metadata_row = metadata_by_audio.get(audio_id)
        if transcript_row is None or metadata_row is None:
            continue
        question = get_question(transcript_row.get("question_id", ""))
        duration = _float_value(metadata_row.get("duration_sec", ""))
        if question is None or duration is None or duration <= 0:
            continue
        transcript = transcript_row["corrected_text"]
        analysis = (system_analyses or {}).get(audio_id)
        metrics = (
            analysis["metrics"]
            if analysis
            else _speech_proxy_metrics(transcript, duration, pauses_by_audio[audio_id])
        )
        corrected_reports[audio_id] = build_analysis_report(
            question, transcript, metrics
        )
        if analysis:
            system_reports[audio_id] = build_analysis_report(
                question, analysis.get("transcript", ""), metrics
            )

    score_rows_by_audio: dict[str, list[dict[str, str]]] = defaultdict(list)
    score_source = consensus if consensus else scores
    for row in score_source:
        score_rows_by_audio[row.get("audio_id", "")].append(row)

    def build_alignment_pairs(
        reports: dict[str, dict[str, Any]], include_fluency: bool
    ) -> dict[str, list[tuple[float, float]]]:
        pair_keys = ["relevance", "structure", "evidence", "content_total"]
        if include_fluency:
            pair_keys.extend(
                ["pace", "pause", "filler_duration", "fluency_total", "total"]
            )
        component_pairs = {key: [] for key in pair_keys}
        for audio_id, report in reports.items():
            human_rows = score_rows_by_audio.get(audio_id, [])
            component_means = {}
            for component in (
                "relevance",
                "structure",
                "evidence",
                "pace",
                "pause",
                "filler_duration",
            ):
                if component not in SCORE_FIELDS:
                    continue
                field = SCORE_FIELDS[component][0]
                values = [
                    value
                    for row in human_rows
                    if (value := _float_value(row.get(field, ""))) is not None
                ]
                if values:
                    component_means[component] = fmean(values)
                    if component in component_pairs:
                        component_pairs[component].append(
                            (
                                component_means[component],
                                report["scores"]["components"][component]["score"]
                                if component in {"pace", "pause", "filler_duration"}
                                else report["scores"][component],
                            )
                        )
            content_components = ("relevance", "structure", "evidence")
            if all(component in component_means for component in content_components):
                component_pairs["content_total"].append(
                    (
                        sum(component_means[item] for item in content_components),
                        report["scores"]["content"],
                    )
                )
            fluency_components = ("pace", "pause", "filler_duration")
            if include_fluency and all(
                component in component_means for component in fluency_components
            ):
                human_fluency = sum(
                    component_means[item] for item in fluency_components
                )
                component_pairs["fluency_total"].append(
                    (human_fluency, report["scores"]["fluency"])
                )
                if all(
                    component in component_means for component in content_components
                ):
                    component_pairs["total"].append(
                        (
                            human_fluency
                            + sum(
                                component_means[item]
                                for item in content_components
                            ),
                            report["scores"]["total"],
                        )
                    )
        return component_pairs

    corrected_pairs = build_alignment_pairs(corrected_reports, False)
    system_pairs = build_alignment_pairs(system_reports, True)

    valid_pause_rows = [
        row
        for row in pauses
        if row.get("row_status") in {"新增", "有效停顿"}
        and row.get("is_valid") in {"是", ""}
        and _float_value(row.get("duration_sec", "")) is not None
    ]
    pause_durations = [
        float(row["duration_sec"])
        for row in valid_pause_rows
        if float(row["duration_sec"]) >= 0
    ]
    pause_types: dict[str, int] = defaultdict(int)
    for row in valid_pause_rows:
        pause_types[row.get("pause_type") or "未分类"] += 1

    joined_text = "\n".join(
        row.get("corrected_text", "") for row in transcripts
    )
    privacy_scan = {
        "phone_pattern_matches": len(
            re.findall(r"(?<!\d)1[3-9]\d{9}(?!\d)", joined_text)
        ),
        "email_pattern_matches": len(
            re.findall(
                r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                joined_text,
            )
        ),
        "note": "仅做电话号码和邮箱格式扫描，不等同于完整隐私审查",
    }

    if system_analyses:
        transcript_by_id = {
            row.get("audio_id", ""): row for row in transcripts if row.get("audio_id")
        }
        system_asr_pairs = [
            (
                analysis.get("transcript", ""),
                transcript_by_id[audio_id].get("corrected_text", ""),
            )
            for audio_id, analysis in system_analyses.items()
            if audio_id in transcript_by_id
        ]
        asr_metrics = _asr_metrics_from_pairs(system_asr_pairs)
        asr_metrics["source"] = "audio_batch_analysis"
    else:
        asr_metrics = _asr_metrics(transcripts)
        asr_metrics["source"] = "annotation_csv_asr_text"

    content_alignment: dict[str, Any] = {
        "corrected_transcript": {
            component: _score_alignment(pairs)
            for component, pairs in corrected_pairs.items()
        },
        "system_transcript": None,
    }
    if system_reports:
        content_alignment["system_transcript"] = {
            component: _score_alignment(system_pairs[component])
            for component in ("relevance", "structure", "evidence", "content_total")
        }

    fluency_alignment = None
    if system_reports:
        fluency_alignment = {
            component: _score_alignment(system_pairs[component])
            for component in (
                "pace",
                "pause",
                "filler_duration",
                "fluency_total",
                "total",
            )
        }

    return {
        "evaluation_version": EVALUATION_VERSION,
        "rules_version": next(
            (report["engine_version"] for report in corrected_reports.values()), None
        ),
        "source_summary": {
            "csv_encodings": encodings,
            "task_count": len(task_ids),
            "completed_audio_count": len(completed_ids),
            "evaluated_audio_count": len(corrected_reports),
            "system_audio_count": len(system_reports),
            "participant_count": len(
                {
                    row.get("participant_id")
                    for row in metadata
                    if row.get("participant_id")
                }
            ),
            "annotators": annotators,
            "score_source": "consensus" if consensus else "annotator_mean",
            "split_counts": {
                split: sum(row.get("split") == split for row in metadata)
                for split in sorted({row.get("split", "") for row in metadata})
                if split
            },
        },
        "data_quality": {
            "status": "has_errors"
            if any(issue["severity"] == "error" for issue in issues)
            else "usable_with_warnings"
            if issues
            else "ready",
            "issues": issues,
            "privacy_pattern_scan": privacy_scan,
        },
        "asr": asr_metrics,
        "content_score_alignment": content_alignment,
        "fluency_score_alignment": fluency_alignment,
        "content_evidence_detection": _content_label_recall(
            labels, corrected_reports
        ),
        "pause_detection": _pause_detection_metrics(pauses, system_analyses or {})
        if system_analyses
        else None,
        "pause_threshold_sweep": _pause_threshold_sweep(
            pauses, system_analyses or {}
        )
        if system_analyses
        else None,
        "synthetic_controls": synthetic_controls,
        "human_pause_reference": {
            "valid_pause_count": len(pause_durations),
            "audio_with_valid_pauses": len(
                {row.get("audio_id") for row in valid_pause_rows}
            ),
            "mean_duration_sec": round(fmean(pause_durations), 3)
            if pause_durations
            else None,
            "long_pause_count_1_5_sec": sum(
                duration >= 1.5 for duration in pause_durations
            ),
            "type_counts": dict(sorted(pause_types.items())),
            "note": "人工参考分布；提供原始录音时，系统对照结果见 pause_detection",
        },
        "limitations": [
            "本批数据全部属于开发集，不能作为最终测试集报告泛化效果。",
            "只有提供原始录音并运行批量语音分析时，表达分和停顿检测指标才代表当前系统输出。",
            "缺少第二名独立标注员和共识评分时，不能计算标注者间一致性。",
            "内容标签缺少负例时，只能报告现有规则对正例的召回情况。",
        ],
    }


def render_evaluation_markdown(report: dict[str, Any]) -> str:
    source = report["source_summary"]
    quality = report["data_quality"]
    asr = report["asr"]
    corrected_alignment = report["content_score_alignment"]["corrected_transcript"]
    system_alignment = report["content_score_alignment"]["system_transcript"]
    fluency_alignment = report["fluency_score_alignment"]
    detection = report["content_evidence_detection"]
    pauses = report["human_pause_reference"]
    pause_detection = report["pause_detection"]
    pause_sweep = report["pause_threshold_sweep"]
    synthetic = report["synthetic_controls"]

    def display_metric(value: Any) -> str:
        return "不可计算" if value is None else str(value)

    lines = [
        "# 人工标注开发集评测摘要",
        "",
        f"> 评测程序：`{report['evaluation_version']}`；规则：`{report['rules_version']}`",
        "",
        "## 数据覆盖",
        "",
        f"- 任务清单：{source['task_count']} 条；完整可用：{source['completed_audio_count']} 条；实际评测：{source['evaluated_audio_count']} 条。",
        f"- 匿名参与者：{source['participant_count']} 人；标注员：{len(source['annotators'])} 人。",
        f"- 评分来源：{'最终共识' if source['score_source'] == 'consensus' else '现有标注员平均值'}。",
        f"- 数据质检状态：`{quality['status']}`。",
        "",
        "## 可复现指标",
        "",
        f"- ASR 字符错误率（CER）：语料级 {asr['corpus_cer']:.2%}，样本平均 {asr['mean_sample_cer']:.2%}（{asr['sample_count']} 条，来源 `{asr['source']}`）。",
        f"- 人工修正文本下的内容总分：人工均值 {corrected_alignment['content_total']['human_mean']}，规则均值 {corrected_alignment['content_total']['system_mean']}，MAE {corrected_alignment['content_total']['mae']}，Pearson {corrected_alignment['content_total']['pearson']}。",
        f"- 可比内容证据正例召回：{detection['positive_detected_count']}/{detection['positive_label_count']}（{detection['positive_recall']:.2%}）。",
        f"- 人工有效停顿：{pauses['valid_pause_count']} 个，覆盖 {pauses['audio_with_valid_pauses']} 条录音；其中 ≥1.5 秒 {pauses['long_pause_count_1_5_sec']} 个。",
    ]

    def append_alignment_table(title: str, alignment: dict[str, Any]) -> None:
        lines.extend(
            [
                "",
                f"### {title}",
                "",
                "| 分项 | 样本数 | 人工均值 | 系统均值 | MAE | 有符号偏差 | Pearson |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for component, label in (
            ("relevance", "题目相关性"),
            ("structure", "结构完整性"),
            ("evidence", "事实与成果"),
            ("content_total", "内容总分"),
        ):
            item = alignment[component]
            lines.append(
                f"| {label} | {item['sample_count']} | {item['human_mean']} | {item['system_mean']} | {item['mae']} | {item['mean_signed_error']} | {display_metric(item['pearson'])} |"
            )

    append_alignment_table("人工修正文本下的内容分", corrected_alignment)
    if system_alignment:
        append_alignment_table("系统原始转写下的内容分", system_alignment)
    if fluency_alignment:
        lines.extend(
            [
                "",
                "### 系统表达分",
                "",
                "| 分项 | 样本数 | 人工均值 | 系统均值 | MAE | 有符号偏差 | Pearson |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for component, label in (
            ("pace", "语速表现"),
            ("pause", "停顿表现"),
            ("filler_duration", "语气词与时长"),
            ("fluency_total", "表达总分"),
            ("total", "综合总分"),
        ):
            item = fluency_alignment[component]
            lines.append(
                f"| {label} | {item['sample_count']} | {item['human_mean']} | {item['system_mean']} | {item['mae']} | {item['mean_signed_error']} | {display_metric(item['pearson'])} |"
            )
    if pause_detection:
        lines.extend(
            [
                "",
                "### 停顿检测",
                "",
                f"- 评测录音：{pause_detection['evaluated_audio_count']} 条；人工参考停顿（≥0.5 秒）：{pause_detection['reference_pause_count_0_5_sec']} 个；系统检出：{pause_detection['detected_pause_count']} 个。",
                f"- Precision {pause_detection['precision']}，Recall {pause_detection['recall']}，F1 {pause_detection['f1']}。",
                f"- 匹配规则：{pause_detection['matching_rule']}。",
                f"- 开发集阈值扫描最佳点：{pause_sweep['best_dev_threshold_ms']}ms，F1 {pause_sweep['best_dev_f1']}；仅作诊断，尚未据此锁定产品阈值。",
            ]
        )
    if synthetic:
        lines.extend(
            [
                "",
                "### AI 合成控制集",
                "",
                f"- {synthetic['sample_count']} 条合成控制样本，{synthetic['check_count']} 个布尔断言，通过 {synthetic['passed_count']} 个（{synthetic['pass_rate']:.2%}）。",
                f"- 失败断言 {len(synthetic['failures'])} 个；只记录样本编号和规则信号，不写入私人标注原文。",
                f"- {synthetic['note']}。",
            ]
        )

    lines.extend(["", "## 数据质检问题", ""])
    for issue in quality["issues"]:
        suffix = f"（{issue['count']} 条）" if issue.get("count") else ""
        lines.append(f"- [{issue['severity']}] {issue['message']}{suffix}")
    if not quality["issues"]:
        lines.append("- 未发现结构或范围问题。")

    lines.extend(["", "## 当前结论边界", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def save_evaluation(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "annotation-evaluation.json"
    markdown_path = output_dir / "annotation-evaluation.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_evaluation_markdown(report), encoding="utf-8")
    return json_path, markdown_path
