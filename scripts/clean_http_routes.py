#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "api" / "routes" / "http.py"
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
out: list[str] = []
skip = False
for line in lines:
    if line.startswith("# --- 以下为误提取"):
        skip = True
        continue
    if skip and line.startswith('@router.get("/api/records")'):
        skip = False
    if not skip:
        out.append(line)
text = "".join(out)
text = re.sub(
    r"\ndef annotation_path_for_record\(record_id: str, locator=None\)[\s\S]*?return None\n\n\n@router.get\(\"/api/records/\{record_id:path\}/export",
    '\n\n@router.get("/api/records/{record_id:path}/export',
    text,
    count=1,
)
text = text.replace(
    """    set_job(job_id, {
            "job_id": job_id,
            "record_id": record_id,
            "status": "pending",
            "progress": 0,
            "message": "排队中",
            "backend": settings.backend,
            "pose_file": pose_path.name,
        }

    background_tasks""",
    """    set_job(job_id, {
        "job_id": job_id,
        "record_id": record_id,
        "status": "pending",
        "progress": 0,
        "message": "排队中",
        "backend": settings.backend,
        "pose_file": pose_path.name,
    })

    background_tasks""",
)
text = text.replace(
    '@router.get("/api/jobs/{job_id}")\ndef get_job(job_id: str)',
    '@router.get("/api/jobs/{job_id}")\ndef get_job_status(job_id: str)',
)
p.write_text(text, encoding="utf-8")
print("ok", len(text))
