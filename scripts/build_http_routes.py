#!/usr/bin/env python3
"""从 server.py 生成 api/routes/http.py（路由层）。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / "server.py").read_text(encoding="utf-8")
start = src.index('@app.get("/api/health")')
end = src.index("\nWEB_DIR = ")
body = src[start:end]

body = body.replace("@app.", "@router.")
body = re.sub(r"^def _(\w+)", r"def \1", body, flags=re.M)

replacements = {
    "_get_job": "get_job",
    "_update_job": "update_job",
    "_jobs": "_jobs",
    "_jobs_lock": "_jobs_lock",
    "_locate_record": "locate_record_by_id",
    "_record_id_from_pose_path": "record_id_from_pose_path",
    "_meta_path_for_record": "meta_path_for_record",
    "_resolve_video_stem_for_record": "resolve_video_stem_for_record",
    "_annotation_path_for_video_stem": "stem_annotation_path",
    "_persist_annotation_for_video": "persist_annotation_for_video",
    "_annotation_frame_size": "annotation_frame_size",
    "_parse_save_video_flag": "parse_save_video_flag",
    "_video_path_for_record": "video_path_for_record",
    "_video_path_for_video_stem": "video_path_for_video_stem",
    "_record_meta_for_list": "record_meta_for_list",
    "_annotation_path_for_record": "annotation_path_for_record",
    "_build_collect_config_snapshot": "build_collect_config_snapshot",
    "_run_job": "run_job",
    "_run_batch_job": "run_batch_job",
    "_resolve_collect_annotation": "resolve_collect_annotation",
    "_reflection_json_path": "reflection_json_path",
    "_load_reflection_or_http": "load_reflection_or_http",
    "_VIDEO_MIME": "VIDEO_MIME",
    "_REFLECTION_OK": "REFLECTION_OK",
    "normalize_corner_label": "normalize_corner_label",
}

# 删除已迁到 service 的函数定义块
body = re.sub(
    r"^def reflection_json_path\(\)[\s\S]*?^def resolve_collect_annotation\([\s\S]*?return annotation_path, cam_label, cam_slug\n\n",
    "",
    body,
    count=1,
    flags=re.M,
)
body = re.sub(
    r"^def get_inference_config",
    "def get_inference_config",
    body,
    count=1,
)
# 移除内联 helper（若在 routes 里重复）
for pattern in [
    r"^def reflection_json_path\(\) -> Path:.*?^@router",
    r"^def load_reflection_or_http\(\) -> Any:.*?^@router",
    r"^def resolve_collect_annotation\([\s\S]*?^@router",
]:
    body = re.sub(pattern, "@router", body, count=1, flags=re.M)

for old, new in replacements.items():
    body = body.replace(old, new)

# 去掉 routes 中残留的 service 函数
body = re.sub(
    r"^def reflection_json_path\(\)[\s\S]*?(?=^@router)",
    "",
    body,
    flags=re.M,
)
body = re.sub(
    r"^def load_reflection_or_http\(\)[\s\S]*?(?=^@router)",
    "",
    body,
    flags=re.M,
)
body = re.sub(
    r"^def resolve_collect_annotation\([\s\S]*?(?=^@router)",
    "",
    body,
    flags=re.M,
)

header = '''"""HTTP 路由（FastAPI APIRouter）。"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from annotation_store import (
    annotation_path_for_video_stem,
    load_annotation_json,
    resolve_video_stem_from_record,
    validate_annotation_payload,
)
from collect_core import validate_video_path
from config_loader import (
    build_settings,
    camera_storage_slug,
    default_pose_json_path,
    load_config_file,
    resolve_app_paths,
    resolve_config_path,
    sanitize_file_stem,
)
from export_pose_xlsx import export_pose_to_xlsx_bytes
from model_assets import VIDEO_EXTENSIONS
from pose_store import (
    STORAGE_V2_PARQUET,
    delete_record,
    iter_active_records,
    load_events,
    load_frames_range,
    load_pose_document,
    load_pose_header,
    load_timeline,
)
from video_frame import first_frame_base64

from api.collect_service import (
    build_collect_config_snapshot,
    resolve_collect_annotation,
    run_batch_job,
    run_job,
)
from api.constants import VIDEO_MIME
from api.job_store import get_job, set_job
from api.record_service import (
    annotation_frame_size,
    annotation_path_for_record,
    locate_record_by_id,
    meta_path_for_record,
    parse_save_video_flag,
    persist_annotation_for_video,
    record_id_from_pose_path,
    record_meta_for_list,
    video_path_for_record,
    video_path_for_video_stem,
)
from api.reflection_service import (
    REFLECTION_OK,
    load_reflection_or_http,
    normalize_corner_label,
    reflection_json_path,
)

router = APIRouter()

'''

# 修复 set_job 用法：原 with _jobs_lock 块改为 set_job
body = body.replace("with _jobs_lock:\n        _jobs[job_id] =", "set_job(job_id,")
body = re.sub(
    r"set_job\(job_id,\s*\{",
    "set_job(job_id, {",
    body,
)

# collect 里 set_job 需要手工修 - 原代码是 with _jobs_lock: _jobs[id]=...
body = re.sub(
    r"    with _jobs_lock:\n        _jobs\[(\w+)\] = (\{[\s\S]*?\n        \})",
    r"    set_job(\1, \2)",
    body,
)

out = header + body
(ROOT / "api" / "routes").mkdir(exist_ok=True)
(ROOT / "api" / "routes" / "__init__.py").write_text(
    'from api.routes.http import router\n\n__all__ = ["router"]\n',
    encoding="utf-8",
)
(ROOT / "api" / "routes" / "http.py").write_text(out, encoding="utf-8")
print("wrote api/routes/http.py", len(out))
