#!/usr/bin/env python3
"""将 localdata/video 中已移动的配套视频复制回批处理源目录。"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import camera_storage_slug, resolve_app_paths


def _slug_dup_suffix(camera_slug: str, camera_label: str) -> int | None:
    base = camera_storage_slug(camera_label)
    m = re.match(rf"^{re.escape(base)}-\((\d+)\)$", str(camera_slug or "").strip())
    if not m:
        return None
    return int(m.group(1))


def _candidate_rel_paths(camera_label: str, camera_slug: str, source_video: str) -> list[str]:
    label = str(camera_label or "").strip()
    name = str(source_video or "").strip()
    if not label or not name:
        return []
    dup = _slug_dup_suffix(camera_slug, label)
    folders: list[str] = []
    if dup is not None:
        folders.append(f"{label}({dup})")
    folders.append(label)
    seen: set[str] = set()
    out: list[str] = []
    for folder in folders:
        for rel in (f"{folder}/clips/{name}", f"{folder}/{name}"):
            if rel not in seen:
                seen.add(rel)
                out.append(rel)
    return out


def restore_videos(
    *,
    source_root: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    paths = resolve_app_paths()
    video_dir = paths.video_dir
    json_dir = paths.json_dir
    source_root = source_root.resolve()

    stats = {"copied": 0, "skipped_exists": 0, "missing_saved": 0, "no_target": 0, "errors": 0}

    for meta_path in sorted(json_dir.rglob("*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats["errors"] += 1
            continue
        if not isinstance(meta, dict):
            continue

        video_file = str(meta.get("video_file") or "").strip()
        if not video_file:
            continue

        camera_slug = str(meta.get("camera_slug") or "").strip()
        if not camera_slug:
            rid = str(meta.get("record_id") or "")
            if "/" in rid:
                camera_slug = rid.split("/", 1)[0]
        if not camera_slug:
            stats["no_target"] += 1
            continue

        saved = video_dir / camera_slug / video_file
        if not saved.is_file():
            stats["missing_saved"] += 1
            continue

        collect_config = meta.get("collect_config") if isinstance(meta.get("collect_config"), dict) else {}
        rel = str(collect_config.get("relative_path") or "").strip().replace("\\", "/")
        candidates: list[Path] = []
        if rel:
            candidates.append(source_root / Path(rel))
        else:
            source_name = str(meta.get("source_video") or "").strip()
            camera_label = str(meta.get("camera_label") or "").strip()
            for rel_guess in _candidate_rel_paths(camera_label, camera_slug, source_name):
                candidates.append(source_root / Path(rel_guess))

        if not candidates:
            stats["no_target"] += 1
            continue

        dest = candidates[0]
        if dest.is_file():
            stats["skipped_exists"] += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        if dry_run:
            print(f"[dry-run] {saved.name} -> {dest}")
            stats["copied"] += 1
            continue
        try:
            shutil.copy2(saved, dest)
            stats["copied"] += 1
        except OSError as exc:
            print(f"❌ 复制失败 {saved} -> {dest}: {exc}", file=sys.stderr)
            stats["errors"] += 1

    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="将 localdata/video 配套视频复制回批处理源目录")
    p.add_argument(
        "source_root",
        type=Path,
        help="批处理时的视频根目录，如 D:/OutputDir202606/skeleton-video/video",
    )
    p.add_argument("--dry-run", action="store_true", help="仅打印将要复制的路径")
    args = p.parse_args(argv)

    if not args.source_root.is_dir():
        print(f"❌ 源目录不存在: {args.source_root}", file=sys.stderr)
        return 2

    stats = restore_videos(source_root=args.source_root, dry_run=args.dry_run)
    print(
        f"完成：复制 {stats['copied']}，源已存在跳过 {stats['skipped_exists']}，"
        f"localdata 无文件 {stats['missing_saved']}，无法推断路径 {stats['no_target']}，"
        f"错误 {stats['errors']}"
    )
    return 0 if stats["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
