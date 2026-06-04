"""后台采集任务状态（内存）。"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import HTTPException

_jobs_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def get_job(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    return job


def update_job(job_id: str, **fields: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def set_job(job_id: str, initial: dict[str, Any]) -> None:
    with _jobs_lock:
        _jobs[job_id] = initial


def get_job_snapshot(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
    return dict(job) if job else None


def batch_timing_from_progress(
    *,
    batch_started_at: float,
    video_started_at: float,
    video_index: int,
    video_total: int,
    inner: float,
    completed_video_secs: list[float],
) -> tuple[float, float, int | None]:
    """根据批处理整体进度估算总进度百分比、已用秒数、剩余秒数。"""
    vt = max(1, int(video_total))
    vi = max(0, min(int(video_index), vt - 1))
    inner_clamped = max(0.0, min(1.0, float(inner)))
    overall_pct = min(99.9, (vi + inner_clamped) / vt * 100.0)
    elapsed = max(0.0, time.perf_counter() - batch_started_at)
    eta_sec: int | None = None
    if inner_clamped > 0.001:
        elapsed_video = max(0.0, time.perf_counter() - video_started_at)
        remain_this = elapsed_video * (1.0 - inner_clamped) / inner_clamped
        videos_after = max(0, vt - vi - 1)
        if completed_video_secs:
            avg = sum(completed_video_secs) / len(completed_video_secs)
            eta_sec = int(max(0, remain_this + avg * videos_after))
        else:
            est_per_video = elapsed_video / inner_clamped
            eta_sec = int(max(0, remain_this + est_per_video * videos_after))
    return round(overall_pct, 1), round(elapsed, 1), eta_sec
