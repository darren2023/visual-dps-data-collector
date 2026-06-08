"""将 web/app.js 拆分为 app/ 目录下多个模块（共享全局作用域，按 script 顺序加载）。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SRC = WEB / "app.js"
OUT = WEB / "app"
BACKUP = WEB / "app.monolith.js"

# (输出文件名, 起始行 1-based 含, 结束行 1-based 含, 文件头注释)
SECTIONS: list[tuple[str, int, int, str]] = [
    ("00-core.js", 1, 41, "/** 常量与共享状态 */\n"),
    ("01-layout-frames.js", 42, 180, "/** 布局换算、帧分块拉取与缓存 */\n"),
    ("02-playback-selection.js", 181, 242, "/** 回放记录选中与 Tab 离开挂起 */\n"),
    ("03-tabs.js", 244, 276, "/** 页签切换与采集表单联动 */\n"),
    ("04-collision-config.js", 278, 356, "/** 碰撞参数（表单 + localStorage） */\n"),
    ("05-collect.js", 358, 888, "/** 采集页：单视频与批处理 */\n"),
    ("06-records.js", 890, 1302, "/** 回放记录列表与打开记录 */\n"),
    ("07-playback-stage.js", 1304, 1340, "/** 回放舞台 DOM 与尺寸监听 */\n"),
    ("08-event-review.js", 1341, 1963, "/** 事件复核（标真 / 取消 / 保存） */\n"),
    ("09-playback-events.js", 1964, 2154, "/** 回放事件加载、定位与清除 */\n"),
    ("10-render-collision.js", 2155, 2648, "/** 画布渲染、货框叠加与碰撞追踪 */\n"),
    ("11-playback-controls.js", 2649, 2842, "/** 回放控件绑定与页面初始化 */\n"),
]


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing {SRC}")

    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) < 2800:
        raise SystemExit(f"app.js too short ({len(lines)} lines); already split?")

    if not BACKUP.exists():
        BACKUP.write_text("".join(lines), encoding="utf-8")
        print(f"backup -> {BACKUP.name}")

    OUT.mkdir(parents=True, exist_ok=True)

    covered: set[int] = set()
    for name, start, end, header in SECTIONS:
        for i in range(start, end + 1):
            covered.add(i)
        chunk = "".join(lines[start - 1 : end])
        path = OUT / name
        path.write_text(header + chunk, encoding="utf-8")
        print(f"wrote app/{name} ({end - start + 1} lines)")

    missing = [i for i in range(1, len(lines) + 1) if i not in covered]
    if missing:
        print("warn: uncovered lines:", missing[:20], ("..." if len(missing) > 20 else ""))

    bootstrap = """/**
 * 骨架采集回放 · 入口占位
 * 实际逻辑已拆分至 app/ 目录，由 index.html 按序加载。
 * 完整单文件备份见 app.monolith.js
 */
"""
    SRC.write_text(bootstrap, encoding="utf-8")
    print("updated web/app.js (bootstrap)")


if __name__ == "__main__":
    main()
