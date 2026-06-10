# 安装 Windows GPU 依赖（requirements-windows-gpu.txt + rtmlib --no-deps）
# 完整部署（模型、验证）请用: powershell -ExecutionPolicy Bypass -File scripts/setup/setup_windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $Root

Write-Host ">> pip install -r requirements-windows-gpu.txt"
python -m pip install -U pip
python -m pip install -r requirements-windows-gpu.txt
Write-Host ">> pip install rtmlib --no-deps"
python -m pip install "rtmlib>=0.0.13" --no-deps
Write-Host ">> pip check"
python -m pip check 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ pip check 有已知告警（rtmlib --no-deps），可忽略"
}
Write-Host "Done. 验证 GPU: python scripts/setup/verify_gpu.py"
