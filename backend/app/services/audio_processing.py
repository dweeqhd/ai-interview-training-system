import json
import math
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


def _finite_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _duration_from_packets(payload: object) -> float | None:
    if not isinstance(payload, dict):
        return None
    packets = payload.get("packets")
    if not isinstance(packets, list):
        return None

    starts: list[float] = []
    ends: list[float] = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        timestamp = _finite_float(packet.get("pts_time"))
        if timestamp is None:
            timestamp = _finite_float(packet.get("dts_time"))
        if timestamp is None:
            continue
        packet_duration = _finite_float(packet.get("duration_time")) or 0.0
        starts.append(timestamp)
        ends.append(timestamp + max(packet_duration, 0.0))

    if not starts:
        return None
    duration = max(ends) - min(starts)
    return duration if duration > 0 else None


def probe_audio_duration(audio_path: Path) -> float:
    _require_tool(FFPROBE_PATH, "FFprobe")
    format_command = [
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
            format_command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=True,
        )
        format_payload = json.loads(result.stdout)
        duration = _finite_float(format_payload.get("format", {}).get("duration"))

        # MediaRecorder 生成的 WebM 可以正常播放，但常不写入容器级总时长。
        # 此时用首尾音频包的时间戳计算实际时长。
        if duration is None or duration <= 0:
            packet_command = [
                str(FFPROBE_PATH),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "packet=pts_time,dts_time,duration_time",
                "-of",
                "json",
                str(audio_path),
            ]
            packet_result = subprocess.run(
                packet_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=True,
            )
            duration = _duration_from_packets(json.loads(packet_result.stdout))
    except (subprocess.SubprocessError, AttributeError, json.JSONDecodeError) as exc:
        raise AudioProcessingError("无法读取音频，请确认文件未损坏") from exc

    if duration is None:
        raise AudioProcessingError("无法读取音频，请确认文件未损坏")

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
