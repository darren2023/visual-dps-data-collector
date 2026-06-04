#!/usr/bin/env python3
"""一次性脚本：从 server.py 提取 record_service 与 collect_service（重构用）。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "server.py").read_text(encoding="utf-8")


def extract_between(start: str, end: str) -> str:
    i = src.find(start)
    j = src.find(end, i + 1)
    if i < 0 or j < 0:
        raise SystemExit(f"block not found: {start!r} .. {end!r}")
    return src[i:j]


def strip_private_prefix(body: str) -> str:
    return re.sub(r"\bdef _", "def ", body)


def write_record_service() -> None:
    body = extract_between("def _json_archive_dir", "def _build_collect_config_snapshot")
    body = strip_private_prefix(body)
    body = body.replace("locate_record(", "locate_record(")  # keep
    renames = {
        "_locate_record": "locate_record_by_id",
        "_record_id_from_pose_path": "record_id_from_pose_path",
        "_meta_path_for_record": "meta_path_for_record",
        "_resolve_video_stem_for_record": "resolve_video_stem_for_record",
        "_annotation_path_for_video_stem": "local_annotation_path_for_stem",
        "_persist_annotation_for_video": "persist_annotation_for_video",
        "_annotation_frame_size": "annotation_frame_size",
        "_parse_save_video_flag": "parse_save_video_flag",
        "_video_path_for_record": "video_path_for_record",
        "_video_path_for_video_stem": "video_path_for_video_stem",
        "_persist_record_video": "persist_record_video",
        "_record_meta_for_list": "record_meta_for_list",
        "_annotation_path_for_record": "annotation_path_for_record",
        "locate_record(paths.json_dir": "locate_record(paths.json_dir",  # no-op
    }
    for old, new in renames.items():
        body = body.replace(old, new)
    body = body.replace("resolved_stem != record_stem", "resolved_stem != pkg_stem")

    meta_block = extract_between("def _record_meta_for_list", "@app.get(\"/api/records\")")
    meta_block = strip_private_prefix(meta_block)
    for old, new in renames.items():
        meta_block = meta_block.replace(old, new)

    header = '''"""记录定位、元数据与配套视频路径。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from annotation_store import (
    annotation_path_for_video_stem,
    load_annotation_json,
    normalize_annotation_payload,
    save_annotation_json,
    validate_annotation_payload,
)
from config_loader import (
    record_id_for_pose_path,
    record_video_path,
    resolve_app_paths,
    sanitize_file_stem,
    variant_to_backend,
)
from model_assets import VIDEO_EXTENSIONS
from pose_store import (
    STORAGE_V2_PARQUET,
    load_pose_header,
    locate_record,
    meta_sidecar_path,
    resolve_video_stem_from_record,
)

'''
    out = header + body + "\n\n" + meta_block
    (ROOT / "api" / "record_service.py").write_text(out, encoding="utf-8")
    print("wrote record_service.py", len(out))


def write_collect_service() -> None:
    body = extract_between("def _build_collect_config_snapshot", "@app.get(\"/api/health\")")
    body = strip_private_prefix(body)
    renames = {
        "_build_collect_config_snapshot": "build_collect_config_snapshot",
        "_display_name_from_pose_file": "display_name_from_pose_file",
        "_run_job": "run_collect_job_task",
        "_run_batch_job": "run_batch_collect_task",
        "_resolve_collect_annotation": "resolve_collect_annotation",
        "_persist_record_video": "persist_record_video",
        "_record_id_from_pose_path": "record_id_from_pose_path",
        "_batch_timing_from_progress": "batch_timing_from_progress",
        "_update_job": "update_job",
        "_jobs_lock": "_JOBS_LOCK_SENTINEL",
        "_jobs": "_JOBS_SENTINEL",
        "_load_reflection_or_http": "load_reflection_or_http",
    }
    for old, new in renames.items():
        body = body.replace(old, new)

    header = '''"""视频采集后台任务（单条与批处理）。"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from annotation_store import (
    load_annotation_json,
    require_annotation_for_collect,
    validate_annotation_payload,
)
from collect_core import run_collect_job
from config_loader import (
    build_settings,
    camera_storage_slug,
    default_pose_json_path,
    json_bucket_dir,
    resolve_app_paths,
    resolve_config_path,
    sanitize_file_stem,
)
from pose_store import STORAGE_V2_PARQUET, meta_sidecar_path

from api.job_store import (
    batch_timing_from_progress,
    get_job_snapshot,
    update_job,
)
from api.job_store import _jobs, _jobs_lock
from api.record_service import persist_record_video, record_id_from_pose_path
from api.reflection_service import (
    REFLECTION_OK,
    load_reflection_or_http,
    normalize_corner_label,
    resolve_annotation_for_camera,
)
from event_engine.annotation_boxes import load_annotation_config

'''
    out = header + body
    (ROOT / "api" / "collect_service.py").write_text(out, encoding="utf-8")
    print("wrote collect_service.py", len(out))


if __name__ == "__main__":
    write_record_service()
    write_collect_service()
