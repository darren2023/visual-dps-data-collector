#!/usr/bin/env python3
"""将同机位多批次 slug（如 1-1-1-(2)）归并到 canonical slug（1-1-1），并同步 json/video 引用。

同名记录/视频冲突时自动追加 -(2)、-(3)… 后缀，**绝不覆盖**已有文件。

用法:
  python scripts/data/consolidate_camera_slugs.py --tier rtmpose-t --dry-run
  python scripts/data/consolidate_camera_slugs.py --tier rtmpose-t
  python scripts/data/consolidate_camera_slugs.py --slug-map 1-1-1-(2)=1-1-1,1-2-1-(3)=1-2-1 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import (  # noqa: E402
    is_pose_model_tier,
    parse_camera_folder_name,
    resolve_app_paths,
)
from pose_store import EVENT_REVIEW_FILE, MANIFEST_FILE  # noqa: E402

SKIP_JSON_TOP = frozenset({"annotations", "archive"})
_RECORD_REF_KEYS = frozenset({"record_id", "pose_file", "pose_url", "manifest_url"})
_SLUG_MAP_RE = re.compile(r"^\s*([^=]+?)\s*=\s*([^=]+?)\s*$")


@dataclass
class ConsolidateStats:
    records_moved: int = 0
    records_renamed: int = 0
    videos_moved: int = 0
    videos_renamed: int = 0
    meta_patched: int = 0
    batch_patched: int = 0
    slug_dirs_removed: int = 0
    id_remaps: dict[str, str] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)


def _log(stats: ConsolidateStats, msg: str, *, dry_run: bool) -> None:
    prefix = "[dry-run] " if dry_run else ""
    line = f"{prefix}{msg}"
    print(line)
    stats.actions.append(line)


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data: dict[str, Any], *, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _rewrite_record_id(val: str, old_prefix: str, new_prefix: str) -> str | None:
    if val == old_prefix or val.startswith(old_prefix + "/"):
        return new_prefix + val[len(old_prefix) :]
    return None


def _apply_id_remap(val: str, remap: dict[str, str]) -> str:
    if val in remap:
        return remap[val]
    return val


def _rewrite_record_refs(obj: Any, remap: dict[str, str]) -> bool:
    changed = False
    if isinstance(obj, dict):
        for key, val in list(obj.items()):
            if isinstance(val, str) and key in _RECORD_REF_KEYS:
                new_val = _apply_id_remap(val, remap)
                if new_val != val:
                    obj[key] = new_val
                    changed = True
            elif isinstance(val, (dict, list)):
                if _rewrite_record_refs(val, remap):
                    changed = True
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                new_val = _apply_id_remap(item, remap)
                if new_val != item:
                    obj[i] = new_val
                    changed = True
            elif isinstance(item, (dict, list)):
                if _rewrite_record_refs(item, remap):
                    changed = True
    return changed


def _patch_json_with_remap(path: Path, remap: dict[str, str], *, dry_run: bool) -> bool:
    data = _load_json(path)
    if not data or not remap:
        return False
    if not _rewrite_record_refs(data, remap):
        return False
    _write_json(path, data, dry_run=dry_run)
    return True


def _is_record_package(path: Path) -> bool:
    return path.is_dir() and (path / MANIFEST_FILE).is_file()


def _parse_slug_map(raw: str | None) -> dict[str, str]:
    if not raw or not str(raw).strip():
        return {}
    out: dict[str, str] = {}
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        m = _SLUG_MAP_RE.match(part)
        if not m:
            raise ValueError(f"无效 --slug-map 片段: {part!r}（期望 src=dest）")
        src, dest = m.group(1).strip(), m.group(2).strip()
        if not src or not dest:
            raise ValueError(f"无效 --slug-map 片段: {part!r}")
        out[src] = dest
    return out


def _canonical_base_slug(slug: str) -> str:
    base, _ = parse_camera_folder_name(slug)
    return base or slug


def _dup_index(slug: str) -> int:
    _, n = parse_camera_folder_name(slug)
    return int(n) if n is not None else 1


def discover_auto_slug_map(tier_json: Path) -> dict[str, str]:
    """自动将 -(2)/(3)… slug 映射到无后缀 base slug。"""
    groups: dict[str, list[str]] = defaultdict(list)
    for cam_dir in sorted(tier_json.iterdir(), key=lambda p: p.name):
        if not cam_dir.is_dir() or cam_dir.name.startswith("."):
            continue
        slug = cam_dir.name
        base = _canonical_base_slug(slug)
        groups[base].append(slug)

    mapping: dict[str, str] = {}
    for base, slugs in groups.items():
        for slug in slugs:
            if slug == base:
                continue
            _, dup_n = parse_camera_folder_name(slug)
            if dup_n is not None:
                mapping[slug] = base
    return mapping


def _record_taken(cam_json_dir: Path, name: str, reserved: set[str]) -> bool:
    if name in reserved:
        return True
    pkg = cam_json_dir / name
    meta = cam_json_dir / f"{name}.meta.json"
    return _is_record_package(pkg) or meta.is_file()


def allocate_record_name(cam_json_dir: Path, base_name: str, reserved: set[str]) -> str:
    if not _record_taken(cam_json_dir, base_name, reserved):
        return base_name
    for n in range(2, 10_000):
        candidate = f"{base_name}-({n})"
        if not _record_taken(cam_json_dir, candidate, reserved):
            return candidate
    raise ValueError(f"机位目录 {cam_json_dir} 下可用记录名过多: {base_name}")


def _video_taken(video_dir: Path, name: str, reserved: set[str]) -> bool:
    if name in reserved:
        return True
    return (video_dir / name).is_file()


def allocate_video_name(video_dir: Path, base_name: str, reserved: set[str]) -> str:
    if not _video_taken(video_dir, base_name, reserved):
        return base_name
    stem = Path(base_name).stem
    ext = Path(base_name).suffix or ".mp4"
    for n in range(2, 10_000):
        candidate = f"{stem}-({n}){ext}"
        if not _video_taken(video_dir, candidate, reserved):
            return candidate
    raise ValueError(f"视频目录 {video_dir} 下可用文件名过多: {base_name}")


def _iter_record_packages(cam_json_dir: Path) -> list[tuple[str, Path]]:
    items: list[tuple[str, Path]] = []
    if not cam_json_dir.is_dir():
        return items
    for child in sorted(cam_json_dir.iterdir(), key=lambda p: p.name):
        if child.name.startswith(".") or child.name.endswith(".meta.json"):
            continue
        if child.name.startswith("_batch_"):
            continue
        if _is_record_package(child):
            items.append((child.name, child))
    return items


def _patch_record_meta(
    meta: dict[str, Any],
    *,
    tier: str,
    dest_slug: str,
    record_name: str,
    video_file: str | None,
) -> None:
    record_id = f"{tier}/{dest_slug}/{record_name}"
    meta["record_id"] = record_id
    meta["camera_slug"] = dest_slug
    meta["pose_model_tier"] = tier
    meta["pose_file"] = f"{record_id}/manifest.json"
    meta["video_url"] = f"/api/records/{record_id}/video"
    if video_file:
        meta["video_file"] = video_file
    cc = meta.get("collect_config")
    if isinstance(cc, dict):
        cc["camera_slug"] = dest_slug


def _patch_package_internals(
    pkg_dir: Path,
    *,
    record_name: str,
    full_record_id: str,
    dry_run: bool,
) -> None:
    manifest = _load_json(pkg_dir / MANIFEST_FILE)
    if manifest is not None:
        manifest["record_id"] = record_name
        _write_json(pkg_dir / MANIFEST_FILE, manifest, dry_run=dry_run)
    review = _load_json(pkg_dir / EVENT_REVIEW_FILE)
    if review is not None:
        review["record_id"] = full_record_id
        _write_json(pkg_dir / EVENT_REVIEW_FILE, review, dry_run=dry_run)


def _move_path(src: Path, dest: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"拒绝覆盖已存在目标: {dest}")
    shutil.move(str(src), str(dest))


def _copy_batch_to_dest(
    batch_path: Path,
    dest_cam_json: Path,
    *,
    src_slug: str,
    dest_slug: str,
    tier: str,
    remap: dict[str, str],
    dry_run: bool,
    stats: ConsolidateStats,
) -> None:
    data = _load_json(batch_path)
    if not data:
        return
    data["camera_slug"] = dest_slug
    if isinstance(data.get("collect_config"), dict):
        data["collect_config"]["camera_slug"] = dest_slug
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("record_id") or "")
        if rid:
            item["record_id"] = _apply_id_remap(rid, remap)
    dest_batch = dest_cam_json / batch_path.name
    if dest_batch.is_file():
        # 批处理清单同名：追加后缀，不覆盖
        stem = batch_path.stem
        for n in range(2, 10_000):
            candidate = dest_cam_json / f"{stem}-({n}).json"
            if not candidate.is_file():
                dest_batch = candidate
                break
        else:
            raise ValueError(f"无法为批处理清单分配唯一名: {batch_path.name}")
        _log(stats, f"批处理清单重命名: {batch_path.name} → {dest_batch.name}", dry_run=dry_run)
    _write_json(dest_batch, data, dry_run=dry_run)
    stats.batch_patched += 1
    if not dry_run and batch_path.is_file() and batch_path.parent.resolve() != dest_cam_json.resolve():
        batch_path.unlink()


def _patch_all_batches_in_dir(cam_json_dir: Path, remap: dict[str, str], *, dry_run: bool, stats: ConsolidateStats) -> None:
    if not remap or not cam_json_dir.is_dir():
        return
    for batch_path in sorted(cam_json_dir.glob("_batch_*.json")):
        if _patch_json_with_remap(batch_path, remap, dry_run=dry_run):
            stats.batch_patched += 1
            _log(stats, f"更新批处理清单引用: {batch_path.name}", dry_run=dry_run)


def consolidate_slug(
    *,
    tier: str,
    src_slug: str,
    dest_slug: str,
    tier_json: Path,
    tier_video: Path,
    dry_run: bool,
    stats: ConsolidateStats,
) -> None:
    if src_slug == dest_slug:
        return

    src_cam_json = tier_json / src_slug
    dest_cam_json = tier_json / dest_slug
    src_cam_video = tier_video / src_slug
    dest_cam_video = tier_video / dest_slug

    if not src_cam_json.is_dir():
        _log(stats, f"跳过（源机位不存在）: {src_slug}", dry_run=dry_run)
        return

    if not dry_run:
        dest_cam_json.mkdir(parents=True, exist_ok=True)
        dest_cam_video.mkdir(parents=True, exist_ok=True)

    reserved_records: set[str] = set()
    reserved_videos: set[str] = set()
    slug_remap: dict[str, str] = {}

    packages = _iter_record_packages(src_cam_json)
    _log(stats, f"归并机位 {src_slug} → {dest_slug}（{len(packages)} 条记录）", dry_run=dry_run)

    for record_name, pkg_dir in packages:
        dest_record_name = allocate_record_name(dest_cam_json, record_name, reserved_records)
        reserved_records.add(dest_record_name)
        renamed = dest_record_name != record_name

        old_record_id = f"{tier}/{src_slug}/{record_name}"
        new_record_id = f"{tier}/{dest_slug}/{dest_record_name}"
        slug_remap[old_record_id] = new_record_id
        stats.id_remaps[old_record_id] = new_record_id

        dest_pkg = dest_cam_json / dest_record_name
        dest_meta = dest_cam_json / f"{dest_record_name}.meta.json"
        src_meta = src_cam_json / f"{record_name}.meta.json"

        if renamed:
            stats.records_renamed += 1
            _log(
                stats,
                f"记录重命名: {old_record_id} → {new_record_id}",
                dry_run=dry_run,
            )
        else:
            _log(stats, f"记录迁移: {old_record_id} → {new_record_id}", dry_run=dry_run)

        if not dry_run:
            _move_path(pkg_dir, dest_pkg, dry_run=False)
        stats.records_moved += 1

        meta = _load_json(src_meta) or {}
        video_file = str(meta.get("video_file") or "").strip()
        if not video_file:
            video_file = f"{record_name}.mp4"

        ext = Path(video_file).suffix or ".mp4"
        preferred_video = f"{dest_record_name}{ext}"
        dest_vid_name = allocate_video_name(dest_cam_video, preferred_video, reserved_videos)
        reserved_videos.add(dest_vid_name)

        _patch_record_meta(
            meta,
            tier=tier,
            dest_slug=dest_slug,
            record_name=dest_record_name,
            video_file=dest_vid_name,
        )
        _write_json(dest_meta, meta, dry_run=dry_run)
        stats.meta_patched += 1
        if not dry_run and src_meta.is_file() and src_meta.resolve() != dest_meta.resolve():
            src_meta.unlink()

        _patch_package_internals(
            dest_pkg if not dry_run else pkg_dir,
            record_name=dest_record_name,
            full_record_id=new_record_id,
            dry_run=dry_run,
        )

        src_vid = src_cam_video / video_file
        if not src_vid.is_file():
            alt = src_cam_video / f"{record_name}.mp4"
            if alt.is_file():
                src_vid = alt
                video_file = alt.name

        if src_vid.is_file():
            dest_vid = dest_cam_video / dest_vid_name
            if dest_vid_name != Path(video_file).name:
                stats.videos_renamed += 1
                _log(
                    stats,
                    f"视频重命名: {tier}/{src_slug}/{video_file} → {tier}/{dest_slug}/{dest_vid_name}",
                    dry_run=dry_run,
                )
            else:
                _log(
                    stats,
                    f"视频迁移: {tier}/{src_slug}/{video_file} → {tier}/{dest_slug}/{dest_vid_name}",
                    dry_run=dry_run,
                )
            _move_path(src_vid, dest_vid, dry_run=dry_run)
            stats.videos_moved += 1

    # 批处理清单迁入目标机位目录
    for batch_path in sorted(src_cam_json.glob("_batch_*.json")):
        _copy_batch_to_dest(
            batch_path,
            dest_cam_json,
            src_slug=src_slug,
            dest_slug=dest_slug,
            tier=tier,
            remap=slug_remap,
            dry_run=dry_run,
            stats=stats,
        )

    # 目标机位内其它批处理清单同步 record_id 映射
    _patch_all_batches_in_dir(dest_cam_json, slug_remap, dry_run=dry_run, stats=stats)

    # 移除已搬空的源机位目录
    if not dry_run:
        if src_cam_json.is_dir() and not any(
            p for p in src_cam_json.iterdir() if not p.name.startswith(".")
        ):
            src_cam_json.rmdir()
            stats.slug_dirs_removed += 1
            _log(stats, f"删除空机位目录 json/{tier}/{src_slug}", dry_run=dry_run)
        if src_cam_video.is_dir() and not any(
            p for p in src_cam_video.iterdir() if not p.name.startswith(".")
        ):
            src_cam_video.rmdir()
            _log(stats, f"删除空机位目录 video/{tier}/{src_slug}", dry_run=dry_run)


def run_consolidate(
    *,
    tier: str,
    slug_map: dict[str, str],
    dry_run: bool,
) -> ConsolidateStats:
    paths = resolve_app_paths()
    tier_json = paths.json_dir / tier
    tier_video = paths.video_dir / tier
    if not tier_json.is_dir():
        raise FileNotFoundError(f"未找到 json 模型层目录: {tier_json}")

    stats = ConsolidateStats()
    if not slug_map:
        _log(stats, "无可归并的机位 slug（已全部为 canonical 名称）", dry_run=dry_run)
        return stats

    # 先归并 -(2)，再 -(3)…；手动映射同样按 dup index 排序
    ordered = sorted(
        slug_map.items(),
        key=lambda kv: (_dup_index(kv[0]), kv[0]),
    )

    for src_slug, dest_slug in ordered:
        if src_slug == dest_slug:
            continue
        consolidate_slug(
            tier=tier,
            src_slug=src_slug,
            dest_slug=dest_slug,
            tier_json=tier_json,
            tier_video=tier_video,
            dry_run=dry_run,
            stats=stats,
        )

    return stats


def verify_records(tier: str, sample_limit: int = 5) -> tuple[int, list[str]]:
    from api.record_service import video_path_for_record
    from pose_store import iter_active_records, locate_record, meta_sidecar_path

    paths = resolve_app_paths()
    recs = iter_active_records(paths.json_dir, pose_tier=tier)
    errors: list[str] = []

    for loc in recs[:sample_limit]:
        if not locate_record(paths.json_dir, loc.record_id):
            errors.append(f"定位失败: {loc.record_id}")
            continue
        meta = _load_json(meta_sidecar_path(paths.json_dir, loc.record_id))
        if meta and meta.get("has_video") and not video_path_for_record(loc.record_id):
            errors.append(f"视频缺失: {loc.record_id}")
    return len(recs), errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="归并同机位多批次 slug 到 canonical 目录（同名记录自动加后缀，不覆盖）"
    )
    p.add_argument("--tier", default="rtmpose-t", help="模型层目录（默认 rtmpose-t）")
    p.add_argument(
        "--slug-map",
        default="",
        help="手动映射，逗号分隔：1-1-1-(2)=1-1-1,1-2-1-(3)=1-2-1（默认自动发现 -(n) slug）",
    )
    p.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    p.add_argument("--verify", action="store_true", help="完成后抽样校验记录定位与视频")
    args = p.parse_args(argv)

    tier = str(args.tier or "rtmpose-t").strip().lower()
    if not is_pose_model_tier(tier):
        print(f"❌ 无效 tier: {tier}", file=sys.stderr)
        return 2

    paths = resolve_app_paths()
    tier_json = paths.json_dir / tier

    try:
        manual = _parse_slug_map(args.slug_map)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    slug_map = discover_auto_slug_map(tier_json)
    slug_map.update(manual)  # 手动映射覆盖自动发现

    stats = run_consolidate(tier=tier, slug_map=slug_map, dry_run=args.dry_run)

    mode = "[dry-run] " if args.dry_run else ""
    print(
        f"\n{mode}完成：记录 {stats.records_moved}（重命名 {stats.records_renamed}），"
        f"视频 {stats.videos_moved}（重命名 {stats.videos_renamed}），"
        f"meta {stats.meta_patched}，批处理 {stats.batch_patched}，"
        f"删除空机位目录 {stats.slug_dirs_removed}，id 映射 {len(stats.id_remaps)}"
    )

    if args.verify and not args.dry_run:
        total, errs = verify_records(tier)
        print(f"校验：活跃记录 {total}，抽样问题 {len(errs)}")
        for e in errs:
            print(f"  ⚠️ {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
