"""在 import onnxruntime 之前配置 NVIDIA CUDA/cuDNN 库搜索路径（跨平台）。

- Windows：将 pip 安装的 nvidia/*/bin 加入 PATH，并调用 add_dll_directory。
- Linux：将 nvidia/*/lib 加入 LD_LIBRARY_PATH，并用 ctypes 预加载 .so
  （进程启动后仅改 LD_LIBRARY_PATH 无法让 ORT CUDA EP 找到 libcudnn.so.9）。
"""

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


def _nvidia_subdirs(sub: str) -> list[str]:
    """收集 site-packages 下 nvidia/<pkg>/{sub} 目录。"""
    dirs: list[str] = []
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        if not base or not os.path.isdir(base):
            continue
        nvidia_root = os.path.join(base, "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for pkg in _NVIDIA_SUBPACKAGES:
            path = os.path.join(nvidia_root, pkg, sub)
            if os.path.isdir(path):
                dirs.append(path)
    return dirs


def _nvidia_bin_dirs() -> list[str]:
    return _nvidia_subdirs("bin")


def _nvidia_lib_dirs() -> list[str]:
    return _nvidia_subdirs("lib")


def _runtime_search_dirs() -> list[str]:
    """Windows 用 bin；Linux 用 lib（LD_LIBRARY_PATH）。"""
    if sys.platform == "win32":
        return _nvidia_bin_dirs()
    return _nvidia_lib_dirs()


def _preload_linux_nvidia_libs(lib_dirs: list[str]) -> None:
    """Linux 下进程启动后改 LD_LIBRARY_PATH 对 dlopen 无效，需 RTLD_GLOBAL 预加载。"""
    if sys.platform == "win32":
        return
    import ctypes

    names = (
        "libcudnn.so.9",
        "libcublas.so.12",
        "libcublasLt.so.12",
        "libcudart.so.12",
    )
    for lib_dir in lib_dirs:
        for name in names:
            path = os.path.join(lib_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


def prepare_ort_cuda_dll_path() -> list[str]:
    """返回已加入 PATH / LD_LIBRARY_PATH 的目录列表（重复调用返回同一结果）。"""
    global _PREPARED, _ADDED_DIRS
    if _PREPARED:
        return list(_ADDED_DIRS)

    search_dirs = _runtime_search_dirs()
    added: list[str] = []
    for lib_dir in search_dirs:
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(lib_dir)
            except OSError:
                pass
        if sys.platform == "win32":
            path = os.environ.get("PATH", "")
            if lib_dir not in path.split(os.pathsep):
                os.environ["PATH"] = lib_dir + os.pathsep + path
        else:
            ld = os.environ.get("LD_LIBRARY_PATH", "")
            if lib_dir not in ld.split(os.pathsep):
                os.environ["LD_LIBRARY_PATH"] = (
                    lib_dir + (os.pathsep + ld if ld else "")
                )
        added.append(lib_dir)

    _preload_linux_nvidia_libs(search_dirs)

    _ADDED_DIRS = added
    _PREPARED = True
    return list(_ADDED_DIRS)


def nvidia_dll_dirs_available() -> list[str]:
    """探测当前 Python 环境中 nvidia 库目录（不修改 PATH / LD_LIBRARY_PATH）。"""
    return _runtime_search_dirs()
