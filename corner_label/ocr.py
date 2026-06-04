"""从视频 ROI 识别机位标签（如 2-1组-3）。同一环境内默认 CPU 版 PaddleOCR。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2

from corner_label.reflection import normalize_corner_label

CORNER_LABEL_RE = re.compile(r"\d+-\d+组-\d+")

# 与主环境共存：CPU paddle；未安装时 auto 回退 easyocr
_DEFAULT_ENGINE = "paddle"


def _ocr_log(msg: str) -> None:
    print(f"[corner-ocr] {msg}", flush=True)


def default_ocr_engine() -> str:
    try:
        cfg = __import__("config_loader", fromlist=["load_config_file", "resolve_config_path"])
        data = cfg.load_config_file(cfg.resolve_config_path(None))
        eng = str((data.get("ocr") or {}).get("engine") or "").strip().lower()
        if eng in ("paddle", "easy", "auto"):
            return eng
    except Exception:
        pass
    return _DEFAULT_ENGINE


@dataclass(frozen=True)
class CornerRoi:
    """画面比例 ROI：默认中心右半区域。"""

    x0: float = 0.5
    y0: float = 0.25
    x1: float = 1.0
    y1: float = 0.75


def extract_corner_label_candidates(text: str) -> list[str]:
    found = CORNER_LABEL_RE.findall(str(text or ""))
    return [normalize_corner_label(x) for x in found]


def _crop_roi(frame, roi: CornerRoi):
    h, w = frame.shape[:2]
    x0 = max(0, int(w * roi.x0))
    y0 = max(0, int(h * roi.y0))
    x1 = min(w, int(w * roi.x1))
    y1 = min(h, int(h * roi.y1))
    if x1 <= x0 or y1 <= y0:
        return frame
    return frame[y0:y1, x0:x1]


def _preprocess_for_ocr(bgr):
    if len(bgr.shape) == 2:
        gray = bgr
    else:
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)


_EASYOCR_READER = None
_PADDLE_OCR = None
_PADDLE_INIT_ERROR: str | None = None


def _paddle_env_setup() -> None:
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("DISABLE_MODEL_SOURCE_CHECK", "True")


def _get_easyocr_reader():
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr

        _EASYOCR_READER = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
    return _EASYOCR_READER


def _ocr_easy(image_bgr) -> str:
    reader = _get_easyocr_reader()
    rgb = (
        cv2.cvtColor(image_bgr, cv2.COLOR_GRAY2RGB)
        if len(image_bgr.shape) == 2
        else cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    )
    lines = reader.readtext(rgb, detail=0, paragraph=True)
    return " ".join(str(x) for x in lines)


def _get_paddle_ocr():
    global _PADDLE_OCR, _PADDLE_INIT_ERROR
    if _PADDLE_OCR is not None:
        return _PADDLE_OCR
    if _PADDLE_INIT_ERROR:
        raise RuntimeError(_PADDLE_INIT_ERROR)
    _paddle_env_setup()
    try:
        from paddleocr import PaddleOCR

        try:
            _PADDLE_OCR = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False)
        except TypeError:
            try:
                _PADDLE_OCR = PaddleOCR(lang="ch")
            except TypeError:
                _PADDLE_OCR = PaddleOCR(use_angle_cls=False, lang="ch")
    except Exception as exc:
        _PADDLE_INIT_ERROR = f"PaddleOCR 初始化失败: {exc}"
        raise RuntimeError(_PADDLE_INIT_ERROR) from exc
    return _PADDLE_OCR


def _collect_text_from_paddle_result(result) -> list[str]:
    parts: list[str] = []
    if result is None:
        return parts
    if isinstance(result, list):
        for item in result:
            parts.extend(_collect_text_from_paddle_result(item))
        return parts
    if isinstance(result, dict):
        for key in ("rec_text", "text", "transcription"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str) and v.strip():
                        parts.append(v.strip())
        res = result.get("res") or result.get("result")
        if res is not None:
            parts.extend(_collect_text_from_paddle_result(res))
        return parts
    if isinstance(result, tuple) and len(result) >= 2:
        text_part = result[1]
        if isinstance(text_part, (list, tuple)) and text_part:
            parts.append(str(text_part[0]))
        elif isinstance(text_part, str):
            parts.append(text_part)
    return parts


def _ocr_paddle(image_bgr) -> str:
    ocr = _get_paddle_ocr()
    rgb = (
        cv2.cvtColor(image_bgr, cv2.COLOR_GRAY2RGB)
        if len(image_bgr.shape) == 2
        else cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    )
    parts: list[str] = []
    if hasattr(ocr, "predict"):
        try:
            for batch in ocr.predict(rgb):
                parts.extend(_collect_text_from_paddle_result(batch))
        except NotImplementedError as exc:
            raise RuntimeError(
                "Paddle 3.x 在 Windows 上 oneDNN 报错，请: pip install paddlepaddle==2.6.2 paddleocr==2.7.3"
            ) from exc
    if not parts and hasattr(ocr, "ocr"):
        try:
            legacy = ocr.ocr(rgb, cls=False)
        except TypeError:
            legacy = ocr.ocr(rgb)
        parts.extend(_collect_text_from_paddle_result(legacy))
    return " ".join(parts)


def ocr_image_corner(image_bgr, *, engine: str = "auto") -> str:
    proc = _preprocess_for_ocr(image_bgr)
    eng = str(engine or "auto").strip().lower()
    if eng == "auto":
        eng = default_ocr_engine()

    errors: list[str] = []
    if eng in ("paddle", "auto"):
        try:
            return _ocr_paddle(proc)
        except ImportError:
            errors.append("未安装 paddleocr（见 requirements-ocr.txt）")
        except Exception as exc:
            errors.append(f"paddle: {exc}")
            if eng == "paddle":
                raise

    if eng in ("easy", "auto"):
        try:
            return _ocr_easy(proc)
        except ImportError:
            errors.append("未安装 easyocr")
        except Exception as exc:
            errors.append(f"easyocr: {exc}")

    hint = "；".join(errors) if errors else f"未知引擎 {engine}"
    raise RuntimeError(f"OCR 失败（{hint}）")


def read_frames_at_indices(
    video_path: str | Path,
    indices: tuple[int, ...],
) -> list[tuple[int, object]]:
    path = Path(video_path)
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {path}")
    out: list[tuple[int, object]] = []
    try:
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
            ret, frame = cap.read()
            if ret and frame is not None:
                out.append((idx, frame))
    finally:
        cap.release()
    return out


def read_corner_label_from_video(
    video_path: str | Path,
    *,
    roi: CornerRoi | None = None,
    sample_frame_indices: tuple[int, ...] = (0, 30, 60, 90),
    engine: str = "auto",
) -> tuple[str | None, dict]:
    roi = roi or CornerRoi()
    path = Path(video_path)
    eng = str(engine or "auto").strip().lower() or default_ocr_engine()
    votes: dict[str, int] = {}
    meta: dict = {"video": str(path), "engine": eng, "frames": []}

    _ocr_log(f"开始 OCR: {path.name} engine={eng} roi=({roi.x0},{roi.y0},{roi.x1},{roi.y1})")

    frames = read_frames_at_indices(path, sample_frame_indices)
    if not frames:
        cap = cv2.VideoCapture(str(path))
        ret, frame = cap.read()
        cap.release()
        if not ret or frame is None:
            return None, {**meta, "error": "无法读取视频帧"}
        frames = [(0, frame)]

    last_error = ""
    for frame_idx, frame in frames:
        crop = _crop_roi(frame, roi)
        h, w = crop.shape[:2]
        try:
            raw = ocr_image_corner(crop, engine=eng)
        except Exception as exc:
            last_error = str(exc)
            _ocr_log(f"帧 {frame_idx} 失败: {last_error}")
            meta["frames"].append({"frame": frame_idx, "error": last_error})
            continue
        cands = extract_corner_label_candidates(raw)
        _ocr_log(f"帧 {frame_idx} crop={w}x{h} raw={raw!r} candidates={cands!r}")
        meta["frames"].append({"frame": frame_idx, "raw": raw, "candidates": cands})
        for c in cands:
            votes[c] = votes.get(c, 0) + 1

    if not votes:
        err = last_error or "未识别到符合 数字-数字组-数字 的标签"
        _ocr_log(f"未匹配: {err}")
        meta["error"] = err
        return None, meta

    best = max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0]
    meta["votes"] = votes
    meta["chosen"] = best
    _ocr_log(f"选用机位: {best!r} votes={votes}")
    return best, meta
