#!/usr/bin/env bash
# 安装本项目依赖（GPU 默认），避免 rtmlib 拉入冲突包
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python -m pip install -r requirements.txt
python -m pip install "rtmlib>=0.0.13" --no-deps
python -m pip check
echo "Done."
