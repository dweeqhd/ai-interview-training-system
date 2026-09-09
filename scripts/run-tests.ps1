$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$nodeRoot = Join-Path $projectRoot ".tools\node-v24.21.0-win-x64"
$npmPath = Join-Path $nodeRoot "npm.cmd"
$ffmpegBin = Join-Path $projectRoot ".tools\ffmpeg-9.0.1\ffmpeg-9.0.1-full_build\bin"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到项目虚拟环境。"
}

if (-not (Test-Path -LiteralPath $npmPath)) {
    throw "未找到项目本地 Node.js。"
}

$env:Path = "$ffmpegBin;$env:Path"
$env:MODELSCOPE_CACHE = Join-Path $projectRoot "models\modelscope"
$env:HF_HOME = Join-Path $projectRoot "models\huggingface"
$env:TEMP = Join-Path $projectRoot "runtime\tmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
Push-Location (Join-Path $projectRoot "backend")
try {
    & $pythonPath -m pytest
    if ($LASTEXITCODE -ne 0) {
        throw "后端测试失败。"
    }
}
finally {
    Pop-Location
}

$env:Path = "$nodeRoot;$env:Path"
Push-Location (Join-Path $projectRoot "frontend")
try {
    & $npmPath run build
    if ($LASTEXITCODE -ne 0) {
        throw "前端构建失败。"
    }
}
finally {
    Pop-Location
}
