"""localdata_staging 目录与 per-batch 配置生成。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from config_loader import load_config_file, project_root, resolve_config_path


def staging_batch_dir(project_root: Path, batch_name: str) -> Path:
    return project_root / "localdata_staging" / batch_name


def ensure_staging_layout(batch_dir: Path) -> None:
    for sub in ("json", "video", "upload"):
        (batch_dir / sub).mkdir(parents=True, exist_ok=True)


def write_staging_config(
    batch_name: str,
    *,
    project: Path | None = None,
    base_config_path: Path | None = None,
) -> Path:
    """为单个批次生成 config.staging.json（共享主库 models / annotations）。"""
    root = project or project_root()
    batch_dir = staging_batch_dir(root, batch_name)
    ensure_staging_layout(batch_dir)

    cfg_path = base_config_path or resolve_config_path(None)
    base_cfg = load_config_file(cfg_path)
    if not base_cfg:
        base_cfg = load_config_file(root / "config.json")

    cfg: dict[str, Any] = json.loads(json.dumps(base_cfg))
    paths = cfg.setdefault("paths", {})
    rel = f"localdata_staging/{batch_name}"
    paths["base_localdata_dir"] = rel
    paths["json_dir"] = f"{rel}/json"
    paths["video_dir"] = f"{rel}/video"
    paths["upload_dir"] = f"{rel}/upload"
    # 模型与全局标注仍用主库，避免重复下载 / 复制
    if not str(paths.get("models_onnx_dir") or "").strip():
        paths["models_onnx_dir"] = "localdata/models/onnx"
    if not str(paths.get("annotation_dir") or "").strip():
        paths["annotation_dir"] = "localdata/json/annotations"

    out = batch_dir / "config.staging.json"
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def list_staging_batches(staging_root: Path | None = None) -> list[Path]:
    """列出含 json 子目录的 staging 批次。"""
    root = staging_root or (project_root() / "localdata_staging")
    if not root.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name):
        if child.is_dir() and not child.name.startswith(".") and (child / "json").is_dir():
            out.append(child)
    return out


def staging_status_marker(batch_dir: Path) -> Path:
    return batch_dir / ".batch_status.json"


def read_batch_status(batch_dir: Path) -> dict[str, Any] | None:
    marker = staging_status_marker(batch_dir)
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_batch_status(batch_dir: Path, payload: dict[str, Any]) -> None:
    staging_status_marker(batch_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def detect_terminal_command() -> str | None:
  for name in ("gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
      if shutil.which(name):
          return name
  return None
