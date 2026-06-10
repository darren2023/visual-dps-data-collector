#!/usr/bin/env python3
"""将 localdata_staging/{批次}/ 合并入主库 localdata/。

每个 staging 批次目录应含 json/、video/（由 batch_staging_parallel.py 生成）。
合并策略与 merge_pose_tier_data 一致；可选合并后执行 consolidate_camera_slugs。

用法:
  python scripts/data/merge_staging_batches.py --dry-run
  python scripts/data/merge_staging_batches.py --tier rtmpose-t
  python scripts/data/merge_staging_batches.py --consolidate-after
  python scripts/data/merge_staging_batches.py --only 6.1,video1
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.collect.staging_paths import list_staging_batches  # noqa: E402

MERGE_SCRIPT = ROOT / "scripts" / "data" / "merge_pose_tier_data.py"
CONSOLIDATE_SCRIPT = ROOT / "scripts" / "data" / "consolidate_camera_slugs.py"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="合并 localdata_staging 各批次到主 localdata")
    p.add_argument("--tier", default="rtmpose-t", help="模型层（默认 rtmpose-t）")
    p.add_argument("--only", default="", help="仅合并指定批次文件夹名，逗号分隔")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--on-conflict",
        choices=("skip", "newer", "overwrite"),
        default="skip",
        help="记录冲突策略（默认 skip=保留主库）",
    )
    p.add_argument(
        "--consolidate-after",
        action="store_true",
        help="全部 merge 完成后执行 consolidate_camera_slugs",
    )
    p.add_argument(
        "--no-merge-annotations",
        action="store_true",
        help="不合并 annotations/（默认会尝试合并）",
    )
    args = p.parse_args(argv)

    only = {s.strip() for s in str(args.only or "").split(",") if s.strip()} or None
    batches = list_staging_batches()
    if only:
        batches = [b for b in batches if b.name in only]

    if not batches:
        print("❌ 未找到 localdata_staging 批次目录", file=sys.stderr)
        return 2

    print(f"📦 待合并 staging 批次 ({len(batches)}):")
    for b in batches:
        print(f"   - {b.name} → {b}")

    failed = 0
    for batch_dir in batches:
        print(f"\n{'=' * 60}")
        print(f"合并批次: {batch_dir.name}")
        print(f"{'=' * 60}")
        cmd = [
            sys.executable,
            str(MERGE_SCRIPT),
            "--source",
            str(batch_dir.resolve()),
            "--tier",
            str(args.tier),
            "--on-conflict",
            args.on_conflict,
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        if args.no_merge_annotations:
            cmd.append("--no-merge-annotations")
        rc = subprocess.call(cmd, cwd=str(ROOT))
        if rc != 0:
            failed += 1
            print(f"❌ 批次 {batch_dir.name} 合并失败 (exit={rc})", file=sys.stderr)

    if failed:
        print(f"\n⚠️ {failed}/{len(batches)} 个批次合并失败", file=sys.stderr)
        return 2

    print(f"\n✅ 全部 {len(batches)} 个 staging 批次已合并到 localdata/")

    if args.consolidate_after and not args.dry_run:
        print(f"\n{'=' * 60}")
        print("机位 slug 归并 (consolidate_camera_slugs)")
        print(f"{'=' * 60}")
        rc = subprocess.call(
            [sys.executable, str(CONSOLIDATE_SCRIPT), "--tier", str(args.tier)],
            cwd=str(ROOT),
        )
        if rc != 0:
            return rc

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
