$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$ffmpegBin = Join-Path $projectRoot ".tools\ffmpeg-9.0.1\ffmpeg-9.0.1-full_build\bin"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到项目虚拟环境，请先完成阶段 2 环境配置。"
}

$env:Path = "$ffmpegBin;$env:Path"
$env:MODELSCOPE_CACHE = Join-Path $projectRoot "models\modelscope"
$env:HF_HOME = Join-Path $projectRoot "models\huggingface"
$env:TEMP = Join-Path $projectRoot "runtime\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
Set-Location (Join-Path $projectRoot "backend")
& $pythonPath -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
