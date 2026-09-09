$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "未找到项目虚拟环境，请先完成阶段 2 环境配置。"
}

Set-Location (Join-Path $projectRoot "backend")
& $pythonPath -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

