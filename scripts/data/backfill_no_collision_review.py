#!/usr/bin/env python3
"""为无碰撞/告警事件的采集记录批量写入 event_review.json（status=no_collision）。

无需打开回放页，直接扫描 localdata/json 下全部活跃记录并落盘复核状态。

用法:
  python scripts/data/backfill_no_collision_review.py
  python scripts/data/backfill_no_collision_review.py --dry-run
  python scripts/data/backfill_no_collision_review.py 2-1-3
  python scripts/data/backfill_no_collision_review.py --dry-run 2-1-3

说明:
  - 仅当 timeline 中无碰撞/告警事件时写入「无碰撞」
  - 已有「无碰撞」或「已复核」的记录跳过
  - 有事件的记录仅缓存 event_total（若尚未缓存），不改变复核状态
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import resolve_app_paths, resolve_config_path
from pose_store import (
    REVIEW_STATUS_COMPLETED,
    REVIEW_STATUS_NO_COLLISION,
    iter_active_records,
    load_event_review,
    load_events,
    meta_sidecar_path,
    persisted_event_review_status,
)

from api.record_service import _parse_event_total, sync_event_review_for_list


def _camera_slug_for_record(record_id: str, paths) -> str:
    if "/" in record_id:
        return record_id.split("/", 1)[0]
    sidecar = meta_sidecar_path(paths.json_dir, record_id)
    if sidecar.is_file():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            slug = str(meta.get("camera_slug") or "").strip()
            if slug:
                return slug
        except (OSError, json.JSONDecodeError):
            pass
    return ""


def _filter_records(paths, slug_filter: str) -> list:
    items = iter_active_records(paths.json_dir)
    if not slug_filter:
        return items
    out = []
    for loc in items:
        rid = loc.record_id
        bucket = rid.split("/", 1)[0] if "/" in rid else ""
        if bucket == slug_filter or _camera_slug_for_record(rid, paths) == slug_filter:
            out.append(loc)
    return out


def process_record(locator, *, dry_run: bool) -> tuple[str, str]:
    """返回 (结果类别, 说明)。"""
    review = load_event_review(locator)
    persisted = persisted_event_review_status(review)
    if persisted == REVIEW_STATUS_NO_COLLISION:
        return "already_no_collision", "已是无碰撞"
    if persisted == REVIEW_STATUS_COMPLETED:
        return "already_completed", "已是已复核"

    cached = _parse_event_total(review)

    if cached is not None and cached > 0:
        return "has_events", f"有 {cached} 条事件，跳过"

    try:
        event_count = cached if cached is not None else len(load_events(locator))
    except (RuntimeError, OSError, ValueError) as exc:
        return "error", str(exc)

    if event_count > 0:
        if dry_run:
            return "has_events", f"有 {event_count} 条事件，跳过"
        sync_event_review_for_list(locator)
        return "has_events", f"有 {event_count} 条事件，已缓存 event_total"

    if dry_run:
        return "would_mark", "将写入无碰撞"

    sync_event_review_for_list(locator)
    after = persisted_event_review_status(load_event_review(locator))
    if after == REVIEW_STATUS_NO_COLLISION:
        return "marked", "已写入无碰撞"
    return "unchanged", f"落盘 status={after or '（空）'}"


def main() -> int:
    parser = argparse.ArgumentParser(description="批量为无碰撞记录写入 event_review（无碰撞）")
    parser.add_argument(
        "camera_slug",
        nargs="?",
        default="",
        help="可选：仅处理该机位目录（如 2-1-3）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计，不写入 event_review.json",
    )
    args = parser.parse_args()
    slug_filter = str(args.camera_slug or "").strip()

    resolve_config_path(None)
    paths = resolve_app_paths()
    locators = _filter_records(paths, slug_filter)
    if not locators:
        print(f"未找到记录（filter={slug_filter or '全部'}）")
        return 1

    counts: Counter[str] = Counter()
    errors = 0

    mode = "预览" if args.dry_run else "执行"
    print(f"{mode}：共 {len(locators)} 条记录（filter={slug_filter or '全部'}）\n")

    for loc in sorted(locators, key=lambda x: x.record_id):
        kind, note = process_record(loc, dry_run=args.dry_run)
        counts[kind] += 1
        if kind == "error":
            errors += 1
        if kind in ("marked", "would_mark", "error") or args.dry_run:
            print(f"  {loc.record_id}: [{kind}] {note}")

    print(
        f"\n汇总："
        f" 新标无碰撞 {counts['marked'] + counts['would_mark']}"
        f" · 已无碰撞 {counts['already_no_collision']}"
        f" · 已复核 {counts['already_completed']}"
        f" · 有事件 {counts['has_events']}"
        f" · 未变 {counts['unchanged']}"
        f" · 失败 {counts['error']}"
    )
    if args.dry_run and counts["would_mark"]:
        print("\n去掉 --dry-run 后将实际写入。")

    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
