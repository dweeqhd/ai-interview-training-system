import re
import threading
import wave
from pathlib import Path
from typing import Any

from app.settings import ASR_MODEL_DIR, PUNC_MODEL_DIR, VAD_MODEL_DIR


_model: Any | None = None
_model_lock = threading.Lock()
FILLER_WORDS = ("嗯", "呃", "额", "啊", "那个", "就是", "然后")
SPEECH_METRIC_VERSION = "speech-metrics-v2-token-timestamps"


def _local_model_or_alias(model_path: Path, alias: str) -> str:
    return str(model_path) if (model_path / "config.yaml").is_file() else alias


def get_speech_model() -> Any:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from funasr import AutoModel

                _model = AutoModel(
                    model=_local_model_or_alias(ASR_MODEL_DIR, "paraformer-zh"),
                    vad_model=_local_model_or_alias(VAD_MODEL_DIR, "fsmn-vad"),
                    punc_model=_local_model_or_alias(PUNC_MODEL_DIR, "ct-punc"),
                    vad_kwargs={"max_single_segment_time": 30000},
                    device="cpu",
                    disable_update=True,
                    trust_remote_code=False,
                )
    return _model


def get_wav_duration(audio_path: Path) -> float:
    with wave.open(str(audio_path), "rb") as audio:
        return audio.getnframes() / float(audio.getframerate())


def _normalize_segments(result: dict[str, Any]) -> list[dict[str, Any]]:
    token_timestamps = []
    for item in result.get("timestamp", []):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        start_ms = int(item[0])
        end_ms = int(item[1])
        if end_ms > start_ms:
            token_timestamps.append((start_ms, end_ms))
    token_timestamps.sort()
    if token_timestamps:
        # Paraformer 的 sentence_info 只保留整句边界，会漏掉句内卡顿。
        # 使用字词时间戳，并把小于 500ms 的自然间隔合并为同一语音段。
        segments = []
        current_start, current_end = token_timestamps[0]
        for start_ms, end_ms in token_timestamps[1:]:
            if start_ms - current_end < 500:
                current_end = max(current_end, end_ms)
                continue
            segments.append(
                {"start_ms": current_start, "end_ms": current_end, "text": ""}
            )
            current_start, current_end = start_ms, end_ms
        segments.append(
            {"start_ms": current_start, "end_ms": current_end, "text": ""}
        )
        return segments

    segments = []
    for item in result.get("sentence_info", []):
        start_ms = int(item.get("start", 0))
        end_ms = int(item.get("end", start_ms))
        if end_ms <= start_ms:
            continue
        segments.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": item.get("text", ""),
            }
        )
    return sorted(segments, key=lambda item: item["start_ms"])


def calculate_metrics(
    text: str,
    segments: list[dict[str, Any]],
    total_duration_sec: float,
) -> dict[str, Any]:
    pauses = []
    for previous, current in zip(segments, segments[1:], strict=False):
        gap_ms = current["start_ms"] - previous["end_ms"]
        if gap_ms >= 500:
            pauses.append(
                {
                    "start_ms": previous["end_ms"],
                    "end_ms": current["start_ms"],
                    "duration_ms": gap_ms,
                    "level": "long" if gap_ms >= 1500 else "noticeable",
                }
            )

    speech_duration_sec = sum(
        (item["end_ms"] - item["start_ms"]) / 1000 for item in segments
    )
    if not segments:
        speech_duration_sec = total_duration_sec

    chinese_characters = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9]+", text))
    speech_units = chinese_characters + latin_words
    speaking_rate = (
        speech_units / (speech_duration_sec / 60) if speech_duration_sec else 0
    )
    filler_counts = {word: text.count(word) for word in FILLER_WORDS}
    filler_counts = {word: count for word, count in filler_counts.items() if count}
    total_pause_sec = sum(item["duration_ms"] for item in pauses) / 1000

    return {
        "total_duration_sec": round(total_duration_sec, 2),
        "speech_duration_sec": round(speech_duration_sec, 2),
        "speech_units": speech_units,
        "speaking_rate_per_min": round(speaking_rate, 1),
        "pause_count": len(pauses),
        "long_pause_count": sum(item["level"] == "long" for item in pauses),
        "longest_pause_sec": round(
            max((item["duration_ms"] for item in pauses), default=0) / 1000, 2
        ),
        "pause_ratio": round(total_pause_sec / total_duration_sec, 3)
        if total_duration_sec
        else 0,
        "filler_count": sum(filler_counts.values()),
        "filler_details": filler_counts,
        "segments": segments,
        "pauses": pauses,
        "metric_version": SPEECH_METRIC_VERSION,
        "metric_note": "语速按中文字符与英文/数字词组计数；停顿阈值需用人工数据校准。",
    }


def analyze_audio(audio_path: Path) -> dict[str, Any]:
    model = get_speech_model()
    results = model.generate(
        input=str(audio_path),
        batch_size_s=60,
        batch_size_threshold_s=30,
        sentence_timestamp=True,
    )
    result = results[0] if results else {}
    text = result.get("text", "").strip()
    segments = _normalize_segments(result)
    total_duration_sec = get_wav_duration(audio_path)
    return {
        "transcript": text,
        "metrics": calculate_metrics(text, segments, total_duration_sec),
    }
