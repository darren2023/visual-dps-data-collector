# 在已激活的 visual-dps-datacollect 环境中执行（勿用 base Python）
# 用法:
#   conda activate visual-dps-datacollect
#   .\scripts\repair_env_after_ocr.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $env:CONDA_DEFAULT_ENV -or $env:CONDA_DEFAULT_ENV -ne "visual-dps-datacollect") {
    Write-Warning "请先: conda activate visual-dps-datacollect"
    Write-Warning "当前 CONDA_DEFAULT_ENV=$($env:CONDA_DEFAULT_ENV)"
}

Write-Host "==> 固定 NumPy 1.x + protobuf（PaddleOCR / Paddle）..."
pip install "numpy==1.26.4" "protobuf==3.20.2"

Write-Host "==> 恢复 GPU 推理（不拉高 NumPy）..."
pip uninstall -y onnxruntime 2>$null
pip install "onnxruntime-gpu==1.23.2" --no-deps
pip install coloredlogs flatbuffers packaging sympy

Write-Host "==> OpenCV 仅保留 headless（卸掉 Paddle/rtmlib 拉的 opencv-python）..."
pip uninstall -y opencv-python opencv-contrib-python 2>$null
pip install "opencv-python-headless==4.10.0.84" --no-deps

Write-Host "==> 自检 ..."
python -c @"
import onnxruntime as ort
import cv2
import numpy as np
print('numpy:', np.__version__)
print('cv2:', cv2.__version__)
print('onnxruntime:', ort.__version__, 'device:', ort.get_device())
print('providers:', ort.get_available_providers()[:3])
import os
os.environ['FLAGS_use_mkldnn'] = '0'
from paddleocr import PaddleOCR
print('PaddleOCR: import ok')
"@

Write-Host ""
Write-Host "完成。pip 若仍提示 paddleocr 需要 opencv-python<=4.6，可忽略（实际用 headless 的 cv2）。"
Write-Host "首次 OCR 会下载模型；探针: python scripts/ocr_probe.py --video your.mp4 --engine paddle"
