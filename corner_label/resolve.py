"""OCR 机位 → reflection → localdata/json/annotations/{编号}.json。"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from corner_label.ocr import CornerRoi, read_corner_label_from_video
from corner_label.reflection import (
    ReflectionMap,
    merge_annotation_files,
    normalize_corner_label,
    resolve_annotation_paths_for_camera,
)


@dataclass
class ResolveResult:
    video_path: Path
    corner_label: str
    annotation_path: Path
    source_annotation_paths: list[Path]
    annotation_ids: list[str]
    ocr_meta: dict


def _write_merged_temp(data: dict, corner_label: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=f"_{normalize_corner_label(corner_label).replace('-', '_')}.json",
        delete=False,
        encoding="utf-8",
    )
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return Path(tmp.name)


def resolve_annotation_for_video(
    video_path: str | Path,
    *,
    reflection: ReflectionMap,
    annotations_dir: Path,
    ocr_engine: str = "auto",
    roi: CornerRoi | None = None,
    sample_frames: tuple[int, ...] = (0, 30, 60, 90),
) -> ResolveResult:
    vpath = Path(video_path).resolve()
    corner_label, ocr_meta = read_corner_label_from_video(
        vpath,
        roi=roi,
        sample_frame_indices=sample_frames,
        engine=ocr_engine,
    )
    if not corner_label:
        raise ValueError(
            f"无法 OCR 机位: {vpath.name}；{ocr_meta.get('error') or '无匹配'}。"
            f"请查看运行 server 的控制台 [corner-ocr] raw= 输出。"
        )

    ann_ids = reflection.annotations_for_camera(corner_label)
    src_paths = resolve_annotation_paths_for_camera(
        corner_label, reflection, Path(annotations_dir)
    )
    merged = merge_annotation_files(src_paths)
    out_path = _write_merged_temp(merged, corner_label) if len(src_paths) > 1 else src_paths[0]

    return ResolveResult(
        video_path=vpath,
        corner_label=corner_label,
        annotation_path=out_path,
        source_annotation_paths=src_paths,
        annotation_ids=ann_ids,
        ocr_meta=ocr_meta,
    )
