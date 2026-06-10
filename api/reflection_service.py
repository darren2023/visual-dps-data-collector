"""reflection.json 机位映射。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config_loader import load_config_file, project_root, resolve_config_path

try:
    from corner_label.reflection import load_reflection, normalize_corner_label
    from corner_label.resolve import resolve_annotation_for_camera

    REFLECTION_OK = True
except ImportError:
    load_reflection = None  # type: ignore
    normalize_corner_label = None  # type: ignore
    resolve_annotation_for_camera = None  # type: ignore
    REFLECTION_OK = False


def reflection_json_path() -> Path:
    cfg = load_config_file(resolve_config_path(None))
    ref = cfg.get("reflection") if isinstance(cfg.get("reflection"), dict) else {}
    ocr = cfg.get("ocr") if isinstance(cfg.get("ocr"), dict) else {}
    rel = str(ref.get("path") or ocr.get("reflection_path") or "reflection.json").strip()
    return (project_root() / rel).resolve()


def load_reflection_or_error() -> Any:
    """加载 reflection.json；CLI 用，抛 ValueError / FileNotFoundError。"""
    if not REFLECTION_OK or not load_reflection:
        raise ValueError("reflection 模块未就绪")
    reflection_path = reflection_json_path()
    if not reflection_path.is_file():
        raise FileNotFoundError(
            f"缺少 reflection.json: {reflection_path}（可复制 examples/reflection.example.json）"
        )
    return load_reflection(reflection_path)


def load_reflection_or_http() -> Any:
    try:
        return load_reflection_or_error()
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
