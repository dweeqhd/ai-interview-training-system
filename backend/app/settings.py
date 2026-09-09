import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
UPLOAD_DIR = PROJECT_ROOT / "uploads" / "private"
PROCESSED_AUDIO_DIR = PROJECT_ROOT / "data" / "processed_audio"
MODEL_ROOT = PROJECT_ROOT / "models"
MODELSCOPE_CACHE = MODEL_ROOT / "modelscope"
HUGGINGFACE_CACHE = MODEL_ROOT / "huggingface"
MODELSCOPE_MODELS_DIR = MODELSCOPE_CACHE / "models"
ASR_MODEL_DIR = (
    MODELSCOPE_MODELS_DIR
    / "iic--speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    / "snapshots"
    / "master"
)
VAD_MODEL_DIR = (
    MODELSCOPE_MODELS_DIR
    / "iic--speech_fsmn_vad_zh-cn-16k-common-pytorch"
    / "snapshots"
    / "master"
)
PUNC_MODEL_DIR = (
    MODELSCOPE_MODELS_DIR
    / "iic--punc_ct-transformer_cn-en-common-vocab471067-large"
    / "snapshots"
    / "master"
)
DATABASE_FILE = RUNTIME_DIR / "app.db"
DATABASE_URL = f"sqlite:///{DATABASE_FILE.as_posix()}"

FFMPEG_BIN_DIR = (
    PROJECT_ROOT
    / ".tools"
    / "ffmpeg-9.0.1"
    / "ffmpeg-9.0.1-full_build"
    / "bin"
)
FFMPEG_PATH = FFMPEG_BIN_DIR / "ffmpeg.exe"
FFPROBE_PATH = FFMPEG_BIN_DIR / "ffprobe.exe"

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MIN_AUDIO_DURATION_SEC = 5.0
MAX_AUDIO_DURATION_SEC = 180.0

os.environ.setdefault("MODELSCOPE_CACHE", str(MODELSCOPE_CACHE))
os.environ.setdefault("HF_HOME", str(HUGGINGFACE_CACHE))


def ensure_runtime_directories() -> None:
    for directory in (
        RUNTIME_DIR,
        UPLOAD_DIR,
        PROCESSED_AUDIO_DIR,
        MODELSCOPE_CACHE,
        HUGGINGFACE_CACHE,
        RUNTIME_DIR / "tmp",
    ):
        directory.mkdir(parents=True, exist_ok=True)
