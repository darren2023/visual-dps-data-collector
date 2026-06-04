"""reflection.json：货位编号 annotation ↔ 画面机位 camera。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from event_engine.annotation_boxes import flatten_annotation_boxes, load_annotation_config


class ReflectionMap:
    def __init__(self, camera_to_annotations: dict[str, list[str]]) -> None:
        self._by_camera = {k: list(v) for k, v in camera_to_annotations.items()}

    def annotations_for_camera(self, camera_label: str) -> list[str]:
        key = normalize_corner_label(camera_label)
        return list(self._by_camera.get(key, []))

    def has_camera(self, camera_label: str) -> bool:
        return normalize_corner_label(camera_label) in self._by_camera

    @property
    def cameras(self) -> list[str]:
        return sorted(self._by_camera.keys())


def normalize_corner_label(raw: str) -> str:
    s = str(raw or "").strip()
    s = s.replace("－", "-").replace("—", "-").replace(" ", "")
    return s


def load_reflection(path: str | Path) -> ReflectionMap:
    p = Path(path)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"reflection 须为 JSON 数组: {p}")

    by_camera: dict[str, list[str]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        cam = normalize_corner_label(str(item.get("camera") or item.get("corner_label") or ""))
        ann = str(item.get("annotation") or item.get("box_id") or "").strip()
        if not cam or not ann:
            continue
        by_camera.setdefault(cam, [])
        if ann not in by_camera[cam]:
            by_camera[cam].append(ann)

    if not by_camera:
        raise ValueError(f"reflection 无有效 camera↔annotation 条目: {p}")
    return ReflectionMap(by_camera)


def annotation_json_path(annotation_id: str, annotations_dir: Path) -> Path:
    aid = str(annotation_id).strip()
    if aid.endswith(".json"):
        return annotations_dir / aid
    return annotations_dir / f"{aid}.json"


def resolve_annotation_paths_for_camera(
    camera_label: str,
    reflection: ReflectionMap,
    annotations_dir: Path,
) -> list[Path]:
    ann_ids = reflection.annotations_for_camera(camera_label)
    if not ann_ids:
        raise FileNotFoundError(
            f"机位 {camera_label!r} 在 reflection 中无 annotation，或拼写不一致"
        )
    paths: list[Path] = []
    missing: list[str] = []
    for aid in ann_ids:
        p = annotation_json_path(aid, annotations_dir)
        if p.is_file():
            paths.append(p)
        else:
            missing.append(p.name)
    if missing:
        raise FileNotFoundError(
            f"缺少标注文件（{annotations_dir}）: {', '.join(missing)}"
        )
    return paths


def merge_annotation_files(paths: list[Path]) -> dict[str, Any]:
    if not paths:
        raise ValueError("无标注文件可合并")
    if len(paths) == 1:
        return load_annotation_config(paths[0])

    shelves: list[dict[str, Any]] = []
    annotation_size: dict[str, int] | None = None
    for p in paths:
        data = load_annotation_config(p)
        if annotation_size is None:
            ann = data.get("annotation_size")
            if isinstance(ann, dict):
                annotation_size = {
                    "width": int(ann.get("width") or 0),
                    "height": int(ann.get("height") or 0),
                }
        raw_shelves = data.get("shelves")
        if isinstance(raw_shelves, list) and raw_shelves:
            shelves.extend(raw_shelves)
        else:
            boxes = flatten_annotation_boxes(data)
            if boxes:
                shelves.append({"shelf_code": p.stem, "boxes": boxes})

    if not shelves:
        raise ValueError("合并后无有效 shelves/boxes")

    out: dict[str, Any] = {"shelves": shelves}
    if annotation_size:
        out["annotation_size"] = annotation_size
    return out
