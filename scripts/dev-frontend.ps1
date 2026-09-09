$projectRoot = Split-Path -Parent $PSScriptRoot
$nodeRoot = Join-Path $projectRoot ".tools\node-v24.21.0-win-x64"
$npmPath = Join-Path $nodeRoot "npm.cmd"

if (-not (Test-Path -LiteralPath $npmPath)) {
    throw "未找到项目本地 Node.js，请先完成阶段 2 环境配置。"
}

$env:Path = "$nodeRoot;$env:Path"
Set-Location (Join-Path $projectRoot "frontend")
& $npmPath run dev

