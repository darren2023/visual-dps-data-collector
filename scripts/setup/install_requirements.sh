#!/usr/bin/env bash
# 安装 Linux GPU 依赖（requirements-linux-gpu.txt + rtmlib --no-deps）
# 完整部署（conda 环境、模型、验证）请用: bash scripts/setup/setup_linux.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
python -m pip install -U pip
python -m pip install -r requirements-linux-gpu.txt
python -m pip install "rtmlib>=0.0.13" --no-deps
python -m pip check || echo "⚠️ pip check 有已知告警（rtmlib --no-deps），可忽略"
echo "Done. 验证 GPU: python scripts/setup/verify_gpu.py"
