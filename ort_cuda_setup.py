"""在 import onnxruntime 之前把 pip 安装的 NVIDIA CUDA/cuDNN DLL 目录加入搜索路径（Windows）。"""

from __future__ import annotations

import os
import site
import sys

_PREPARED = False
_ADDED_DIRS: list[str] = []

_NVIDIA_SUBPACKAGES = (
    "cudnn",
    "cublas",
    "cuda_nvrtc",
    "cuda_runtime",
)


def _nvidia_bin_dirs() -> list[str]:
    dirs: list[str] = []
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        if not base or not os.path.isdir(base):
            continue
        nvidia_root = os.path.join(base, "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for sub in _NVIDIA_SUBPACKAGES:
            bin_dir = os.path.join(nvidia_root, sub, "bin")
            if os.path.isdir(bin_dir):
                dirs.append(bin_dir)
    return dirs


def prepare_ort_cuda_dll_path() -> list[str]:
    """返回已加入 PATH / add_dll_directory 的目录列表（重复调用返回同一结果）。"""
    global _PREPARED, _ADDED_DIRS
    if _PREPARED:
        return list(_ADDED_DIRS)

    added: list[str] = []
    for bin_dir in _nvidia_bin_dirs():
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(bin_dir)
            except OSError:
                pass
        path = os.environ.get("PATH", "")
        if bin_dir not in path.split(os.pathsep):
            os.environ["PATH"] = bin_dir + os.pathsep + path
        added.append(bin_dir)

    _ADDED_DIRS = added
    _PREPARED = True
    return list(_ADDED_DIRS)


def nvidia_dll_dirs_available() -> list[str]:
    """探测当前 Python 环境中 nvidia/*/bin 目录（不修改 PATH）。"""
    return _nvidia_bin_dirs()
