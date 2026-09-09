import json
import subprocess
from pathlib import Path

from app.settings import (
    FFMPEG_PATH,
    FFPROBE_PATH,
    MAX_AUDIO_DURATION_SEC,
    MIN_AUDIO_DURATION_SEC,
)


class AudioProcessingError(RuntimeError):
    """Raised when uploaded audio cannot be validated or normalized."""


def _require_tool(path: Path, name: str) -> None:
    if not path.is_file():
        raise AudioProcessingError(f"缺少{name}，请先运行阶段 3 环境配置")


def probe_audio_duration(audio_path: Path) -> float:
    _require_tool(FFPROBE_PATH, "FFprobe")
    command = [
        str(FFPROBE_PATH),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(audio_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=True,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise AudioProcessingError("无法读取音频，请确认文件未损坏") from exc

    if duration < MIN_AUDIO_DURATION_SEC:
        raise AudioProcessingError(
            f"回答仅 {duration:.1f} 秒，请至少录制 {MIN_AUDIO_DURATION_SEC:.0f} 秒"
        )
    if duration > MAX_AUDIO_DURATION_SEC:
        raise AudioProcessingError(
            f"回答为 {duration:.1f} 秒，请控制在 {MAX_AUDIO_DURATION_SEC:.0f} 秒内"
        )
    return duration


def normalize_audio(source: Path, destination: Path) -> None:
    _require_tool(FFMPEG_PATH, "FFmpeg")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(FFMPEG_PATH),
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=True,
        )
    except subprocess.SubprocessError as exc:
        raise AudioProcessingError("音频标准化失败") from exc
