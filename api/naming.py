"""记录展示名等命名辅助。"""

from __future__ import annotations

from pathlib import Path


def display_name_from_pose_file(pose_file: str, backend: str = "") -> str:
    """从 multi-samples_rtmpose_t.json 还原展示名 multi-samples。"""
    stem = Path(pose_file).stem
    if backend:
        suffix = f"_{backend}"
        if stem.endswith(suffix):
            return stem[: -len(suffix)] or stem
    for tag in ("_rtmpose_t", "_rtmpose_s", "_rtmpose_m"):
        if stem.endswith(tag):
            return stem[: -len(tag)] or stem
    return stem
