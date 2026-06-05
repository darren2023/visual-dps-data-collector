#!/usr/bin/env python3
from fastapi.testclient import TestClient
from api.app import app

client = TestClient(app)
rid = "2-1-3/clip_0001_start_00-00-00_rtmpose_t"
urls = [
    f"/api/records/{rid}/manifest.json",
    "/api/records/2-1-3/clip_0001_start_00-00-00_rtmpose_t/manifest.json",
    "/api/records/2-1-3%2Fclip_0001_start_00-00-00_rtmpose_t/manifest.json",
]
for u in urls:
    r = client.get(u)
    print(r.status_code, u)
