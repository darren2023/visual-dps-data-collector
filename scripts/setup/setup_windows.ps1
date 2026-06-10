# Windows GPU 环境一键部署：依赖、ONNX 模型、GPU 验证
#
# 用法（PowerShell）：
#   powershell -ExecutionPolicy Bypass -File scripts/setup/setup_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/setup/setup_windows.ps1 -SkipModels
#   powershell -ExecutionPolicy Bypass -File scripts/setup/setup_windows.ps1 -Cpu
param(
    [switch]$SkipModels,
    [switch]$Cpu
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $Root

Write-Host ">> Python:" (python -V) (Get-Command python).Source

if ($Cpu) {
    $Req = "requirements-cpu.txt"
} else {
    $Req = "requirements-windows-gpu.txt"
}

Write-Host ">> pip install -r $Req"
python -m pip install -U pip
python -m pip install -r $Req

Write-Host ">> pip install rtmlib --no-deps"
python -m pip install "rtmlib>=0.0.13" --no-deps

Write-Host ">> pip check"
python -m pip check 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️ pip check 有已知告警（rtmlib --no-deps），可忽略"
}

if (-not $SkipModels) {
    Write-Host ">> 下载 ONNX 模型（det t,m + pose t）"
    python scripts/setup/download_onnx_models.py --det t,m --pose t
}

if (-not $Cpu) {
    Write-Host ">> 验证 GPU"
    python scripts/setup/verify_gpu.py
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ GPU 验证失败。请确认已安装 NVIDIA 驱动，且 nvidia-cudnn-cu12 可用。" -ForegroundColor Red
        exit $LASTEXITCODE
    }
} else {
    Write-Host ">> CPU 模式，跳过 GPU 验证"
}

Write-Host ""
Write-Host "✅ Windows 环境就绪"
Write-Host "   cd $Root"
Write-Host "   python server.py"
