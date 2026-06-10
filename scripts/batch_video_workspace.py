#!/usr/bin/env python3
"""对工作区根目录下多个批次文件夹依次执行批处理采集。

典型目录结构（如 /home/zyqiao/video/）::

    video/
      6.1/           ← 批次 1
        1-2组-1/
          clips/*.mp4
        1-3组-1/
      video2/        ← 批次 2
        2-1组-3/
      ...

每个批次文件夹作为独立 root，调用 batch_skeleton_collect.py --group-by-subfolder。

用法:
  # 预览全部批次（不推理）
  python scripts/batch_video_workspace.py /home/zyqiao/video --dry-run

  # RTMPose-T + 碰撞，跳过已有记录
  python scripts/batch_video_workspace.py /home/zyqiao/video \\
    --variant t --with-collision --skip-existing

  # 只处理指定批次
  python scripts/batch_video_workspace.py /home/zyqiao/video \\
    --only 6.1,video3 --variant s --with-collision --dry-run

  # 每批次试跑 2 个视频
  python scripts/batch_video_workspace.py /home/zyqiao/video --limit 2 --variant t
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH_SCRIPT = ROOT / "scripts" / "batch_skeleton_collect.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config_loader import pose_model_tier_from_backend, variant_to_backend
from model_assets import VIDEO_EXTENSIONS


def _count_videos(root: Path) -> int:
    root = root.resolve()
    if not root.is_dir():
        return 0
    n = 0
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            n += 1
    return n


def discover_batch_folders(
    workspace: Path,
    *,
    only: set[str] | None = None,
    exclude: set[str] | None = None,
) -> list[Path]:
    """发现工作区下含视频的批次子目录（仅第一级）。"""
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise FileNotFoundError(f"工作区不存在: {workspace}")

    out: list[Path] = []
    for child in sorted(workspace.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if only and child.name not in only:
            continue
        if exclude and child.name in exclude:
            continue
        if _count_videos(child) <= 0:
            continue
        out.append(child)
    return out


def build_batch_collect_argv(
    batch_dir: Path,
    *,
    variant: str | None,
    backend: str | None,
    with_collision: bool,
    skip_existing: bool,
    dry_run: bool,
    limit: int,
    save_video: bool | None,
    det_variant: str | None,
    device: str | None,
    config: str | None,
) -> list[str]:
    cmd = [
        sys.executable,
        str(BATCH_SCRIPT),
        str(batch_dir.resolve()),
        "--group-by-subfolder",
    ]
    if variant:
        cmd.extend(["--variant", variant])
    if backend:
        cmd.extend(["--backend", backend])
    if det_variant:
        cmd.extend(["--det-variant", det_variant])
    if device:
        cmd.extend(["--device", device])
    if config and str(config).strip():
        cmd.extend(["--config", str(config)])
    if with_collision:
        cmd.append("--with-collision")
    if skip_existing:
        cmd.append("--skip-existing")
    if dry_run:
        cmd.append("--dry-run")
    if limit > 0:
        cmd.extend(["--limit", str(limit)])
    if save_video is True:
        cmd.append("--save-video")
    elif save_video is False:
        cmd.append("--no-save-video")
    return cmd


def print_workspace_plan(
    workspace: Path,
    batches: list[Path],
    *,
    variant: str,
    with_collision: bool,
    skip_existing: bool,
    dry_run: bool,
) -> int:
    tier = pose_model_tier_from_backend(variant_to_backend(variant))
    total_videos = 0
    print(f"📂 工作区: {workspace}")
    print(f"📦 模型: rtmpose_{variant} → 数据层 {tier}/")
    print(f"🦴 模式: {'骨架 + 碰撞' if with_collision else '仅骨架'}")
    print(f"⏭️ 跳过已有: {'是' if skip_existing else '否'}")
    print(f"🔍 dry-run: {'是' if dry_run else '否'}")
    print(f"\n共 {len(batches)} 个批次文件夹：\n")
    print(f"{'批次':<20} {'视频数':>8}  {'机位文件夹':>10}")
    print("-" * 42)
    for batch_dir in batches:
        n = _count_videos(batch_dir)
        total_videos += n
        camera_dirs = sum(
            1
            for p in batch_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".") and _count_videos(p) > 0
        )
        print(f"{batch_dir.name:<20} {n:>8}  {camera_dirs:>10}")
    print("-" * 42)
    print(f"{'合计':<20} {total_videos:>8}")
    sys.stdout.flush()
    return total_videos


def run_workspace(
    workspace: Path,
    batches: list[Path],
    *,
    argv_builder_kwargs: dict,
    stop_on_error: bool,
) -> int:
    failed = 0
    for i, batch_dir in enumerate(batches):
        print(f"\n{'=' * 60}")
        print(f"[{i + 1}/{len(batches)}] 批次: {batch_dir.name}")
        print(f"{'=' * 60}")
        cmd = build_batch_collect_argv(batch_dir, **argv_builder_kwargs)
        print("执行:", " ".join(cmd))
        result = subprocess.run(cmd, cwd=str(ROOT))
        if result.returncode != 0:
            failed += 1
            print(f"❌ 批次 {batch_dir.name} 失败 (exit {result.returncode})", file=sys.stderr)
            if stop_on_error:
                return result.returncode
    if failed:
        print(f"\n完成：{len(batches) - failed}/{len(batches)} 批次成功，{failed} 失败", file=sys.stderr)
        return 2
    print(f"\n✅ 全部 {len(batches)} 个批次处理完成")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="对工作区下多个批次视频文件夹依次批处理采集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "workspace",
        type=Path,
        help="工作区根目录（其下每个子文件夹为一个批次，如 /home/zyqiao/video）",
    )
    p.add_argument(
        "--only",
        default="",
        help="仅处理指定批次文件夹名，逗号分隔（如 6.1,video3）",
    )
    p.add_argument(
        "--exclude",
        default="",
        help="排除的批次文件夹名，逗号分隔",
    )
    p.add_argument(
        "--variant",
        choices=["t", "s", "m"],
        default="t",
        help="RTMPose 规格，决定输出目录 rtmpose-t/s/m（默认 t）",
    )
    p.add_argument("--backend", default=None, help="覆盖 config 的 backend（如 rtmpose_s）")
    p.add_argument("--det-variant", default=None, help="检测模型规格 t/s/m")
    p.add_argument("--device", choices=("cpu", "cuda"), default=None)
    p.add_argument("-c", "--config", default=None, help="config.json 路径")
    p.add_argument(
        "--with-collision",
        action="store_true",
        help="骨架 + 碰撞（需 reflection.json 与 annotations）",
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="已有 manifest.json 的记录跳过",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="每个批次调用 batch_skeleton_collect --dry-run，列出全部待处理视频",
    )
    p.add_argument(
        "--plan-only",
        action="store_true",
        help="仅打印工作区批次汇总表（不调用子批处理，最快预览）",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="每个批次最多处理 N 个视频（0=不限）",
    )
    p.add_argument("--save-video", action="store_true", default=None)
    p.add_argument("--no-save-video", action="store_true")
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="某批次失败后继续处理后续批次（默认遇错即停）",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    workspace = args.workspace.resolve()

    only = {s.strip() for s in str(args.only or "").split(",") if s.strip()} or None
    exclude = {s.strip() for s in str(args.exclude or "").split(",") if s.strip()} or None

    try:
        batches = discover_batch_folders(workspace, only=only, exclude=exclude)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    if not batches:
        print(f"❌ 未找到含视频的批次文件夹: {workspace}", file=sys.stderr)
        if only:
            print(f"   --only 过滤: {', '.join(sorted(only))}", file=sys.stderr)
        return 2

    save_video: bool | None = None
    if args.no_save_video:
        save_video = False
    elif args.save_video:
        save_video = True

    print_workspace_plan(
        workspace,
        batches,
        variant=args.variant,
        with_collision=args.with_collision,
        skip_existing=args.skip_existing,
        dry_run=args.dry_run or args.plan_only,
    )

    if args.plan_only:
        print("\n[plan-only] 未执行批处理；去掉 --plan-only 后加 --dry-run 可查看逐条视频列表")
        return 0

    kwargs = {
        "variant": args.variant,
        "backend": args.backend,
        "with_collision": args.with_collision,
        "skip_existing": args.skip_existing,
        "dry_run": args.dry_run,
        "limit": int(args.limit or 0),
        "save_video": save_video,
        "det_variant": args.det_variant,
        "device": args.device,
        "config": args.config,
    }

    return run_workspace(
        workspace,
        batches,
        argv_builder_kwargs=kwargs,
        stop_on_error=not args.continue_on_error,
    )


if __name__ == "__main__":
    raise SystemExit(main())
