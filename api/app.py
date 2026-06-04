"""FastAPI 应用工厂与启动入口。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes import router as http_router
from config_loader import (
    build_settings,
    default_save_video,
    load_config_file,
    project_root,
    resolve_app_paths,
    resolve_config_path,
)
from pose_store import migrate_v1_json_dir


def create_app() -> FastAPI:
    application = FastAPI(title="visual-dps-datacollect", version="0.2.0")
    application.include_router(http_router)
    web_dir = project_root() / "web"
    if web_dir.is_dir():
        application.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return application


app = create_app()


def main() -> None:
    import uvicorn

    cfg = load_config_file(resolve_config_path(None))
    server = cfg.get("server") if isinstance(cfg.get("server"), dict) else {}
    host = str(server.get("host") or "127.0.0.1")
    port = int(server.get("port") or 8765)
    paths = resolve_app_paths(cfg)
    for p in (
        paths.json_dir,
        paths.video_dir,
        paths.upload_dir,
        paths.playback_temp_dir,
        paths.annotation_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)
    migrated = migrate_v1_json_dir(paths.json_dir)
    if migrated:
        print(f"📦 已迁移 {len(migrated)} 条 v1 JSON → Parquet 包")
    settings = build_settings(config_path=resolve_config_path(None), cli={})
    print(f"🌐 Web UI: http://{host}:{port}")
    print(f"📁 JSON 目录: {paths.json_dir}")
    print(f"🎬 视频目录: {paths.video_dir}（默认保存: {default_save_video()})")
    print(f"📦 ONNX 目录: {paths.models_onnx_dir}")
    print(f"   ├─ detection: {paths.models_detection_dir}")
    print(f"   └─ pose: {paths.models_pose_dir}")
    print(f"🏷 标注目录: {paths.annotation_dir}（每视频一份，新保存覆盖旧文件）")
    print(f"🧠 推理设备: {settings.device}（models.use_gpu / INFERENCE_USE_GPU）")
    if settings.device == "cuda":
        try:
            from rtmpose_infer import assert_cuda_ort_available, ort_available_providers

            assert_cuda_ort_available()
            print(f"✅ ORT GPU 就绪: {ort_available_providers()}")
        except RuntimeError as exc:
            print(f"❌ {exc}")
    uvicorn.run("api.app:app", host=host, port=port, reload=False)
