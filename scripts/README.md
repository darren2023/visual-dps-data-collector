# 脚本工具索引

按用途分类；均在项目根目录下执行。

## setup/ — 环境与模型

| 脚本 | 用途 |
|------|------|
| `setup/setup_linux.sh` | Linux 一键部署：conda 环境、GPU 依赖、ONNX 模型、GPU 验证 |
| `setup/setup_windows.ps1` | Windows 一键部署（同上） |
| `setup/install_requirements.sh` | 仅安装 Linux GPU 依赖（无 conda / 模型） |
| `setup/install_requirements.ps1` | 仅安装 Windows GPU 依赖 |
| `setup/download_onnx_models.py` | 下载 RTMDet + RTMPose ONNX 权重 |
| `setup/verify_gpu.py` | 验证 ONNX Runtime CUDA 是否可用 |

```bash
bash scripts/setup/setup_linux.sh
python scripts/setup/verify_gpu.py
python scripts/setup/download_onnx_models.py --det t,m --pose t
```

## collect/ — 批量采集

| 脚本 | 用途 |
|------|------|
| `collect/batch_skeleton_collect.py` | 单机位 / 多机位文件夹递归批处理（骨架 + 可选碰撞） |
| `collect/batch_video_workspace.py` | 工作区下多个批次根目录依次调用批处理 |

```bash
python scripts/collect/batch_skeleton_collect.py /path/videos --group-by-subfolder --with-collision
python scripts/collect/batch_video_workspace.py /path/workspace --variant t --skip-existing
```

## data/ — 数据迁移与维护

推荐顺序：**模型层迁移 → slug 归并 → 跨机合并**。

| 脚本 | 用途 |
|------|------|
| `data/migrate_pose_model_tiers.py` | 扁平 `localdata/json|video/{机位}` → `rtmpose-t/{机位}` |
| `data/consolidate_camera_slugs.py` | 同机位 `-(2)/(3)` slug 归并到 canonical 机位（同名记录加后缀，不覆盖） |
| `data/merge_pose_tier_data.py` | 合并另一台机器/导出目录的采集数据（含复核 `event_review` 并集） |
| `data/repair_batch_records.py` | 为已有记录补 `annotation.json` 回放副本 |
| `data/restore_source_videos.py` | 将 `localdata/video` 配套视频复制回批处理源目录 |
| `data/backfill_no_collision_review.py` | 批量为无碰撞记录写入 `event_review`（无碰撞） |

```bash
# 本机 slug 归并（先 --dry-run）
python scripts/data/consolidate_camera_slugs.py --tier rtmpose-t --dry-run
python scripts/data/consolidate_camera_slugs.py --tier rtmpose-t

# 跨机合并
python scripts/data/merge_pose_tier_data.py --source /path/to/export --tier rtmpose-t --dry-run
```

## archive/ — 历史工具（勿日常运行）

| 脚本 | 说明 |
|------|------|
| `archive/split_app_js.py` | 将 `web/app.monolith.js` 拆分为 `web/app/` 模块（拆分已完成） |

已删除的失效脚本（重构一次性工具，勿恢复）：`build_http_routes.py`、`split_server_modules.py`、`clean_http_routes.py`、`test_manifest_api.py`。
