$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$ffmpegBin = Join-Path $projectRoot ".tools\ffmpeg-9.0.1\ffmpeg-9.0.1-full_build\bin"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到项目虚拟环境。"
}

$env:Path = "$ffmpegBin;$env:Path"
$env:MODELSCOPE_CACHE = Join-Path $projectRoot "models\modelscope"
$env:HF_HOME = Join-Path $projectRoot "models\huggingface"
$env:TEMP = Join-Path $projectRoot "runtime\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:MODELSCOPE_CACHE -Force | Out-Null
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null

& $pythonPath -c @"
from funasr import AutoModel

print("准备中文 Paraformer、FSMN-VAD 和 CT-Punc 模型……")
AutoModel(
    model="paraformer-zh",
    vad_model="fsmn-vad",
    punc_model="ct-punc",
    vad_kwargs={"max_single_segment_time": 30000},
    device="cpu",
    disable_update=True,
    trust_remote_code=False,
)
print("模型已下载并成功加载。")
"@

if ($LASTEXITCODE -ne 0) {
    throw "模型下载或加载失败。"
}
