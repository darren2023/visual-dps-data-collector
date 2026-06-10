#!/usr/bin/env python3
"""并行批处理采集：每批次写入 localdata_staging/{批次名}/，默认最多 2 路同时跑。

工作区默认 /home/hqit/zyrao/skeleton-video/，其下每个子文件夹（6.1、video1…）为独立批次。
各批次互不写同一目录，适合多终端 / 多进程并行；完成后用 merge_staging_batches.py 合并入主库。

用法:
  # 预览计划
  python scripts/collect/batch_staging_parallel.py --plan-only

  # 在新终端窗口中跑（最多 2 个窗口同时推理，推荐有桌面环境时）
  python scripts/collect/batch_staging_parallel.py --terminal --with-collision --skip-existing

  # 当前终端内子进程跑（无 GUI 或 SSH）
  python scripts/collect/batch_staging_parallel.py --with-collision --skip-existing

  # 仅处理部分批次
  python scripts/collect/batch_staging_parallel.py --only 6.1,video1 --terminal

  # 全部完成后自动合并到 localdata（并可选 slug 归并）
  python scripts/collect/batch_staging_parallel.py --terminal --with-collision \\
    --merge-after --consolidate-after
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.collect.batch_video_workspace import (  # noqa: E402
    _count_videos,
    discover_batch_folders,
    print_workspace_plan,
)
from scripts.collect.staging_paths import (  # noqa: E402
    detect_terminal_command,
    read_batch_status,
    staging_batch_dir,
    write_batch_status,
    write_staging_config,
)

DEFAULT_WORKSPACE = Path("/home/hqit/zyrao/skeleton-video")
BATCH_COLLECT = ROOT / "scripts" / "collect" / "batch_skeleton_collect.py"
MERGE_SCRIPT = ROOT / "scripts" / "data" / "merge_staging_batches.py"
CONSOLIDATE_SCRIPT = ROOT / "scripts" / "data" / "consolidate_camera_slugs.py"


def _build_collect_argv(
    batch_video_dir: Path,
    config_path: Path,
    *,
    with_collision: bool,
    skip_existing: bool,
    dry_run: bool,
    limit: int,
    save_video: bool | None,
    variant: str | None,
    backend: str | None,
    det_variant: str | None,
    device: str | None,
) -> list[str]:
    cmd = [
        sys.executable,
        str(BATCH_COLLECT),
        str(batch_video_dir.resolve()),
        "--group-by-subfolder",
        "--config",
        str(config_path.resolve()),
    ]
    if variant:
        cmd.extend(["--variant", variant])
    if backend:
        cmd.extend(["--backend", backend])
    if det_variant:
        cmd.extend(["--det-variant", det_variant])
    if device:
        cmd.extend(["--device", device])
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


def _shell_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(str(a)) for a in argv)


def _wrapper_shell(batch_name: str, collect_argv: list[str], log_path: Path, status_path: Path) -> str:
    """在子 shell 中执行采集并写入状态文件。"""
    cmd = _shell_join(collect_argv)
    log_q = shlex.quote(str(log_path))
    status_q = shlex.quote(str(status_path))
    name_q = shlex.quote(batch_name)
    root_q = shlex.quote(str(ROOT))
    # JSON 状态文件供主控脚本轮询完成
    return (
        f"cd {root_q} && "
        f"echo '▶ 批次 {batch_name} 开始' | tee -a {log_q}; "
        f"({cmd}) 2>&1 | tee -a {log_q}; "
        f"ec=${{PIPESTATUS[0]}}; "
        f"finished_at=$(date +%Y-%m-%dT%H:%M:%S); "
        f"printf '{{\"batch\":%s,\"exit_code\":%s,\"finished_at\":\"%s\"}}\\n' "
        f"{name_q} \"$ec\" \"$finished_at\" > {status_q}; "
        f"echo ''; "
        f"if [ $ec -eq 0 ]; then echo '✅ 批次 {batch_name} 完成 (exit=0)'; "
        f"else echo '❌ 批次 {batch_name} 失败 (exit='$ec')'; fi; "
        f"read -r -p '按 Enter 关闭此窗口…' _"
    )


def _launch_in_terminal(batch_name: str, shell_body: str) -> subprocess.Popen:
    term = detect_terminal_command()
    title = f"pose-collect: {batch_name}"
    if term == "gnome-terminal":
        return subprocess.Popen(
            ["gnome-terminal", "--title", title, "--", "bash", "-lc", shell_body],
            cwd=str(ROOT),
        )
    if term == "konsole":
        return subprocess.Popen(
            ["konsole", "--new-tab", "-p", f"tabtitle={title}", "-e", "bash", "-lc", shell_body],
            cwd=str(ROOT),
        )
    if term == "xfce4-terminal":
        return subprocess.Popen(
            ["xfce4-terminal", "--title", title, "-e", f"bash -lc {shlex.quote(shell_body)}"],
            cwd=str(ROOT),
        )
    if term == "xterm":
        return subprocess.Popen(
            ["xterm", "-T", title, "-e", "bash", "-lc", shell_body],
            cwd=str(ROOT),
        )
    raise RuntimeError("未找到可用的终端模拟器（gnome-terminal / konsole / xfce4-terminal / xterm）")


def _is_batch_finished(batch_dir: Path) -> tuple[bool, int | None]:
    st = read_batch_status(batch_dir)
    if not st:
        return False, None
    if "exit_code" in st:
        try:
            return True, int(st["exit_code"])
        except (TypeError, ValueError):
            return True, 1
    return False, None


def run_parallel(
    batches: list[Path],
    *,
    max_workers: int,
    use_terminal: bool,
    collect_kwargs: dict,
    base_config_path: Path | None = None,
) -> int:
    pending = list(batches)
    running: dict[str, dict] = {}
    failed: list[str] = []

    print(f"\n🚀 并行采集：最多 {max_workers} 路同时运行，共 {len(pending)} 个批次")
    if use_terminal:
        term = detect_terminal_command()
        print(f"🖥️  终端模式: {term}")
    else:
        print("🖥️  子进程模式（当前终端）")

    while pending or running:
        while pending and len(running) < max_workers:
            batch_dir = pending.pop(0)
            name = batch_dir.name
            staging = staging_batch_dir(ROOT, name)
            config_path = write_staging_config(name, base_config_path=base_config_path)
            log_path = staging / "batch.log"
            status_path = staging / ".batch_status.json"
            if status_path.is_file():
                status_path.unlink()

            argv = _build_collect_argv(batch_dir, config_path, **collect_kwargs)
            print(f"\n📦 启动批次: {name}")
            print(f"   视频根: {batch_dir}")
            print(f"   staging: {staging}")
            print(f"   日志: {log_path}")

            if use_terminal:
                shell = _wrapper_shell(name, argv, log_path, status_path)
                try:
                    proc = _launch_in_terminal(name, shell)
                except RuntimeError as exc:
                    print(f"❌ {exc}", file=sys.stderr)
                    return 2
                running[name] = {"mode": "terminal", "proc": proc, "staging": staging, "status": status_path}
            else:
                log_f = open(log_path, "a", encoding="utf-8")
                log_f.write(f"\n▶ 批次 {name} 开始 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                log_f.flush()
                proc = subprocess.Popen(
                    argv,
                    cwd=str(ROOT),
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                )
                running[name] = {
                    "mode": "subprocess",
                    "proc": proc,
                    "staging": staging,
                    "log_f": log_f,
                    "status": status_path,
                }

        time.sleep(2.0)
        done_names: list[str] = []
        for name, info in list(running.items()):
            staging: Path = info["staging"]
            if info["mode"] == "subprocess":
                proc: subprocess.Popen = info["proc"]
                rc = proc.poll()
                if rc is None:
                    continue
                info.get("log_f") and info["log_f"].close()
                write_batch_status(
                    staging,
                    {
                        "batch": name,
                        "exit_code": int(rc),
                        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    },
                )
                if rc != 0:
                    failed.append(name)
                    print(f"❌ 批次 {name} 失败 (exit={rc})，见 {staging / 'batch.log'}")
                else:
                    print(f"✅ 批次 {name} 完成")
                done_names.append(name)
            else:
                finished, rc = _is_batch_finished(staging)
                if not finished:
                    continue
                if rc != 0:
                    failed.append(name)
                    print(f"❌ 批次 {name} 失败 (exit={rc})，见 {staging / 'batch.log'}")
                else:
                    print(f"✅ 批次 {name} 完成")
                done_names.append(name)

        for name in done_names:
            running.pop(name, None)

    if failed:
        print(f"\n⚠️ 失败批次 ({len(failed)}): {', '.join(failed)}", file=sys.stderr)
        return 2
    print(f"\n✅ 全部 {len(batches)} 个批次采集完成")
    return 0


def run_merge_after(*, tier: str, consolidate: bool, dry_run: bool) -> int:
    if not MERGE_SCRIPT.is_file():
        print(f"❌ 未找到合并脚本: {MERGE_SCRIPT}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(MERGE_SCRIPT), "--tier", tier]
    if consolidate:
        cmd.append("--consolidate-after")
    if dry_run:
        cmd.append("--dry-run")
    print("\n" + "=" * 60)
    print("合并 staging → localdata")
    print("=" * 60)
    return subprocess.call(cmd, cwd=str(ROOT))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="并行批处理采集到 localdata_staging（默认最多 2 路）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "workspace",
        type=Path,
        nargs="?",
        default=DEFAULT_WORKSPACE,
        help=f"视频工作区（默认 {DEFAULT_WORKSPACE}）",
    )
    p.add_argument("--only", default="", help="仅处理指定批次名，逗号分隔")
    p.add_argument("--exclude", default="", help="排除批次名，逗号分隔")
    p.add_argument(
        "--max-workers",
        type=int,
        default=2,
        help="同时运行的批次数（默认 2）",
    )
    p.add_argument(
        "--terminal",
        action="store_true",
        help="每个批次在新终端窗口中运行（需桌面环境）",
    )
    p.add_argument(
        "--no-terminal",
        action="store_true",
        help="强制在当前终端以子进程运行（忽略 --terminal）",
    )
    p.add_argument("--variant", choices=["t", "s", "m"], default="t")
    p.add_argument("--backend", default=None)
    p.add_argument("--det-variant", default=None)
    p.add_argument("--device", choices=("cpu", "cuda"), default=None)
    p.add_argument("-c", "--config", default=None, help="主 config.json（用于生成 staging 配置）")
    p.add_argument("--with-collision", action="store_true")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--plan-only", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--save-video", action="store_true", default=None)
    p.add_argument("--no-save-video", action="store_true")
    p.add_argument(
        "--merge-after",
        action="store_true",
        help="全部批次成功后合并到 localdata/",
    )
    p.add_argument(
        "--consolidate-after",
        action="store_true",
        help="与 --merge-after 联用：合并后执行 consolidate_camera_slugs",
    )
    p.add_argument(
        "--merge-only",
        action="store_true",
        help="跳过采集，仅合并已有 localdata_staging",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    workspace = Path(args.workspace).resolve()

    if args.merge_only:
        tier = f"rtmpose-{args.variant}"
        return run_merge_after(
            tier=tier,
            consolidate=args.consolidate_after,
            dry_run=args.dry_run,
        )

    only = {s.strip() for s in str(args.only or "").split(",") if s.strip()} or None
    exclude = {s.strip() for s in str(args.exclude or "").split(",") if s.strip()} or None

    try:
        batches = discover_batch_folders(workspace, only=only, exclude=exclude)
    except FileNotFoundError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2

    if not batches:
        print(f"❌ 未找到含视频的批次: {workspace}", file=sys.stderr)
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
    print(f"\n📁 staging 根目录: {ROOT / 'localdata_staging'}")

    if args.plan_only:
        print("\n[plan-only] 未启动采集")
        for b in batches:
            sd = staging_batch_dir(ROOT, b.name)
            print(f"  {b.name} → {sd}")
        return 0

    use_terminal = bool(args.terminal)
    if not args.no_terminal and not use_terminal and os.environ.get("DISPLAY") and detect_terminal_command():
        use_terminal = True
        print("ℹ️ 检测到桌面环境，默认使用 --terminal 新窗口模式（可用 --no-terminal 关闭）")

    if args.dry_run:
        # dry-run 串行预览，不并行开窗口
        base_cfg = Path(args.config) if args.config else None
        for b in batches:
            cfg = write_staging_config(b.name, base_config_path=base_cfg)
            cmd = _build_collect_argv(
                b,
                cfg,
                with_collision=args.with_collision,
                skip_existing=args.skip_existing,
                dry_run=True,
                limit=int(args.limit or 0),
                save_video=save_video,
                variant=args.variant,
                backend=args.backend,
                det_variant=args.det_variant,
                device=args.device,
            )
            print(f"\n--- dry-run: {b.name} ---")
            subprocess.call(cmd, cwd=str(ROOT))
        return 0

    collect_kwargs = {
        "with_collision": args.with_collision,
        "skip_existing": args.skip_existing,
        "dry_run": False,
        "limit": int(args.limit or 0),
        "save_video": save_video,
        "variant": args.variant,
        "backend": args.backend,
        "det_variant": args.det_variant,
        "device": args.device,
    }

    base_cfg = Path(args.config) if args.config else None
    rc = run_parallel(
        batches,
        max_workers=max(1, int(args.max_workers)),
        use_terminal=use_terminal,
        collect_kwargs=collect_kwargs,
        base_config_path=base_cfg,
    )

    if rc == 0 and args.merge_after:
        tier = f"rtmpose-{args.variant}"
        merge_rc = run_merge_after(
            tier=tier,
            consolidate=args.consolidate_after,
            dry_run=False,
        )
        if merge_rc != 0:
            return merge_rc

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
