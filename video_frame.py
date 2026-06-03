"""从视频提取标注用首帧。"""

from __future__ import annotations

import base64
from pathlib import Path

import cv2

from collect_core import validate_video_path


def extract_first_frame_jpeg(video_path: str | Path, *, max_width: int = 0) -> tuple[bytes, int, int]:
    path = validate_video_path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {path}")
    try:
        ret, frame = cap.read()
        if not ret or frame is None:
            raise RuntimeError(f"无法读取视频首帧: {path}")
        h, w = frame.shape[:2]
        if max_width > 0 and w > max_width:
            scale = max_width / float(w)
            frame = cv2.resize(
                frame,
                (int(round(w * scale)), int(round(h * scale))),
                interpolation=cv2.INTER_AREA,
            )
            h, w = frame.shape[:2]
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            raise RuntimeError("首帧 JPEG 编码失败")
        return buf.tobytes(), w, h
    finally:
        cap.release()


def first_frame_base64(video_path: str | Path, *, max_width: int = 0) -> dict:
    jpeg, w, h = extract_first_frame_jpeg(video_path, max_width=max_width)
    return {
        "image": base64.b64encode(jpeg).decode("ascii"),
        "width": w,
        "height": h,
    }
