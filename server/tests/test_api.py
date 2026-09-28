import hashlib
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


TEST_ROOT = Path(tempfile.mkdtemp(prefix="nas-link-api-"))
os.environ["NAS_LINK_DATA_ROOT"] = str(TEST_ROOT)
os.environ["NAS_LINK_AUTO_ORGANIZE"] = "true"
os.environ["DEEPSEEK_API_KEY"] = ""

from app.main import app  # noqa: E402


def test_library_clipboard_search_and_backup_round_trip() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json()["ok"] is True
        assert client.get("/api/dashboard").status_code == 200

        for device_id, name in (("windows-office", "办公室Windows"), ("macbook-home", "MacBook")):
            response = client.post(
                "/api/devices/register",
                json={"id": device_id, "name": name, "platform": "test", "app_version": "0.1.0"},
            )
            assert response.status_code == 200

        with client.websocket_connect("/ws?device_id=macbook-home") as websocket:
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json()["type"] == "pong"
            response = client.post(
                "/api/clipboard",
                json={"source_device": "windows-office", "content": "跨设备测试文字"},
            )
            assert response.status_code == 200
            message = websocket.receive_json()
            assert message["type"] == "clipboard"
            assert message["item"]["content"] == "跨设备测试文字"

        upload = client.post(
            "/api/library/upload",
            params={"filename": "德国站2026发票.txt", "source_device": "windows-office"},
            headers={"Content-Type": "application/octet-stream"},
            content="订单发票 DE-2026-001".encode(),
        )
        assert upload.status_code == 200
        file_id = upload.json()["id"]
        files = client.get("/api/library/files").json()
        stored = next(item for item in files if item["id"] == file_id)
        assert stored["status"] == "organized"
        assert stored["category"] == "文档"

        search = client.post(
            "/api/library/search", json={"query": "德国站2026发票", "limit": 10}
        )
        assert search.status_code == 200
        assert search.json()["files"][0]["id"] == file_id

        content = b"versioned backup content"
        digest = hashlib.sha256(content).hexdigest()
        plan = client.post(
            "/api/backups/plan",
            json={
                "device_id": "windows-office",
                "root_name": "Documents",
                "files": [{"path": "reports/test.txt", "sha256": digest, "size": len(content), "mtime_ns": 1}],
            },
        ).json()
        assert plan["missing_hashes"] == [digest]
        snapshot_id = plan["snapshot_id"]
        uploaded = client.put(
            f"/api/backups/{snapshot_id}/blobs/{digest}", content=content
        )
        assert uploaded.status_code == 200
        committed = client.post(f"/api/backups/{snapshot_id}/commit")
        assert committed.json()["status"] == "complete"
        restored = client.get(
            f"/api/backups/{snapshot_id}/restore", params={"path": "reports/test.txt"}
        )
        assert restored.content == content
