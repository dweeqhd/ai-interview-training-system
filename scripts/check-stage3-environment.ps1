$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$ffmpegPath = Join-Path $projectRoot ".tools\ffmpeg-9.0.1\ffmpeg-9.0.1-full_build\bin\ffmpeg.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到项目 Python 虚拟环境。"
}
if (-not (Test-Path -LiteralPath $ffmpegPath)) {
    throw "未找到项目 FFmpeg。"
}

$env:Path = "$(Split-Path -Parent $ffmpegPath);$env:Path"
$env:MODELSCOPE_CACHE = Join-Path $projectRoot "models\modelscope"
$env:HF_HOME = Join-Path $projectRoot "models\huggingface"
$env:TEMP = Join-Path $projectRoot "runtime\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null

& $pythonPath -m pip check
& $pythonPath -c @"
import funasr
import modelscope
import torch
import torchaudio

print(f"torch={torch.__version__}")
print(f"torchaudio={torchaudio.__version__}")
print(f"funasr={funasr.__version__}")
print(f"modelscope={modelscope.__version__}")
print(f"cuda_available={torch.cuda.is_available()}")
"@
& $ffmpegPath -version | Select-Object -First 1
