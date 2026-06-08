#!/usr/bin/env bash
# Linux GPU 环境一键部署：conda 环境、依赖、ONNX 模型、GPU 验证
#
# 用法：
#   bash scripts/setup_linux.sh                  # 新建/更新 conda 环境 visual-dps
#   bash scripts/setup_linux.sh --env myenv      # 指定环境名
#   bash scripts/setup_linux.sh --skip-conda     # 已在目标 Python 环境中，仅装依赖
#   bash scripts/setup_linux.sh --skip-models    # 跳过模型下载
#   bash scripts/setup_linux.sh --cpu            # 安装 CPU 版依赖
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_NAME="visual-dps"
PYTHON_VERSION="3.10"
SKIP_CONDA=0
SKIP_MODELS=0
USE_CPU=0

usage() {
  sed -n '2,8p' "$0"
  echo "  --env NAME        conda 环境名（默认 visual-dps）"
  echo "  --skip-conda      不创建 conda 环境，使用当前 python"
  echo "  --skip-models     跳过 ONNX 模型下载"
  echo "  --cpu             安装 CPU 推理依赖（requirements-cpu.txt）"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --env) ENV_NAME="$2"; shift 2 ;;
    --skip-conda) SKIP_CONDA=1; shift ;;
    --skip-models) SKIP_MODELS=1; shift ;;
    --cpu) USE_CPU=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage; exit 1 ;;
  esac
done

# Cursor 沙箱可能把 CONDA_PKGS_DIRS 指到不可写目录
if [ -n "${CONDA_PKGS_DIRS:-}" ] && [ ! -w "${CONDA_PKGS_DIRS%%:*}" ] 2>/dev/null; then
  unset CONDA_PKGS_DIRS
fi

if [ "$SKIP_CONDA" -eq 0 ]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "❌ 未找到 conda，请先安装 Miniconda/Anaconda，或使用 --skip-conda" >&2
    exit 1
  fi
  source "$(conda info --base)/etc/profile.d/conda.sh"
  if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo ">> 使用已有 conda 环境: $ENV_NAME"
  else
    echo ">> 创建 conda 环境: $ENV_NAME (Python $PYTHON_VERSION)"
    conda create -n "$ENV_NAME" "python=$PYTHON_VERSION" -y
  fi
  conda activate "$ENV_NAME"
fi

echo ">> Python: $(python -V) ($(which python))"

if [ "$USE_CPU" -eq 1 ]; then
  REQ="requirements-cpu.txt"
else
  REQ="requirements-linux-gpu.txt"
fi

echo ">> pip install -r $REQ"
python -m pip install -U pip
python -m pip install -r "$REQ"
echo ">> pip install rtmlib --no-deps"
python -m pip install "rtmlib>=0.0.13" --no-deps
python -m pip check || echo "⚠️ pip check 有已知告警（rtmlib --no-deps），可忽略"

if [ "$SKIP_CONDA" -eq 0 ] && [ "$USE_CPU" -eq 0 ]; then
  ACTIVATE_D="$CONDA_PREFIX/etc/conda/activate.d"
  DEACTIVATE_D="$CONDA_PREFIX/etc/conda/deactivate.d"
  mkdir -p "$ACTIVATE_D" "$DEACTIVATE_D"
  cat > "$ACTIVATE_D/visual-dps-gpu.sh" << 'EOS'
# visual-dps：为子进程设置 NVIDIA 库路径
if [ -d "${CONDA_PREFIX}/lib" ]; then
  _VDC_NVIDIA_LIBS=""
  for _sub in cudnn cublas cuda_nvrtc cuda_runtime; do
    for _pylib in "${CONDA_PREFIX}"/lib/python*/site-packages/nvidia/${_sub}/lib; do
      if [ -d "${_pylib}" ]; then
        _VDC_NVIDIA_LIBS="${_pylib}:${_VDC_NVIDIA_LIBS}"
      fi
    done
  done
  if [ -n "${_VDC_NVIDIA_LIBS}" ]; then
    export _VDC_OLD_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"
    export LD_LIBRARY_PATH="${_VDC_NVIDIA_LIBS}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
  fi
fi
EOS
  cat > "$DEACTIVATE_D/visual-dps-gpu.sh" << 'EOS'
if [ -n "${_VDC_OLD_LD_LIBRARY_PATH+x}" ]; then
  export LD_LIBRARY_PATH="${_VDC_OLD_LD_LIBRARY_PATH}"
  unset _VDC_OLD_LD_LIBRARY_PATH
fi
unset _VDC_NVIDIA_LIBS
EOS
  echo ">> 已写入 conda activate.d/deactivate.d（子进程 LD_LIBRARY_PATH）"
fi

if [ "$SKIP_MODELS" -eq 0 ]; then
  echo ">> 下载 ONNX 模型（det t,m + pose t）"
  python scripts/download_onnx_models.py --det t,m --pose t
fi

if [ "$USE_CPU" -eq 0 ]; then
  echo ">> 验证 GPU"
  python scripts/verify_gpu.py
else
  echo ">> CPU 模式，跳过 GPU 验证"
fi

echo ""
echo "✅ Linux 环境就绪"
if [ "$SKIP_CONDA" -eq 0 ]; then
  echo "   conda activate $ENV_NAME"
fi
echo "   cd $ROOT && python server.py"
