# 安装本项目依赖（GPU 默认），避免 rtmlib 拉入冲突包
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host ">> pip install -r requirements.txt"
python -m pip install -r requirements.txt
Write-Host ">> pip install rtmlib --no-deps"
python -m pip install "rtmlib>=0.0.13" --no-deps
Write-Host ">> pip check"
python -m pip check
Write-Host "Done."
