#!/usr/bin/env python3
"""Web 服务入口：CUDA 初始化后加载 api.app。"""

from __future__ import annotations

# 必须在 import onnxruntime / rtmlib 之前配置 NVIDIA 库路径（Windows PATH / Linux 预加载）
from ort_cuda_setup import prepare_ort_cuda_dll_path

prepare_ort_cuda_dll_path()

from api.app import app, main  # noqa: E402

__all__ = ["app", "main"]

if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
