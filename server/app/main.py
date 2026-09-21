import asyncio
import hashlib
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .config import get_settings
from .db import Database, utc_now
from .deepseek import DeepSeekClient, _basic_keywords
from .organizer import Organizer
from .realtime import ConnectionManager
from .schemas import BackupPlan, ClipboardCreate, DeviceRegistration, SearchRequest
from .security import _valid_token, require_token
from .storage import StorageService


settings = get_settings()
db = Database(settings.db_path)
deepseek = DeepSeekClient(settings)
organizer = Organizer(settings, db, deepseek)
storage = StorageService(settings, db)
realtime = ConnectionManager()
dropbox_observations: dict[str, tuple[int, int]] = {}
dropbox_task: asyncio.Task | None = None

async def watch_dropbox() -> None:
    dropbox = settings.data_root / "dropbox"
    while True:
        try:
            current_paths: set[str] = set()
            for path in dropbox.rglob("*"):
                if not path.is_file() or path.is_symlink() or path.name.startswith(".") or path.name.endswith(".uploading"):
                    continue
                key = str(path)
                current_paths.add(key)
                stat = path.stat()
                signature = (stat.st_size, stat.st_mtime_ns)
                if dropbox_observations.get(key) == signature:
                    item = storage.ingest_local_file(path)
                    dropbox_observations.pop(key, None)
                    if item.get("status") == "inbox":
                        await organize_in_background(item["id"])
                    else:
                        await realtime.broadcast({"type": "library_updated", "file": item})
                else:
                    dropbox_observations[key] = signature
            for missing in set(dropbox_observations) - current_paths:
                dropbox_observations.pop(missing, None)
        except Exception:
            pass
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global dropbox_task
    dropbox_task = asyncio.create_task(watch_dropbox())
    try:
        yield
    finally:
        if dropbox_task:
            dropbox_task.cancel()
            try:
                await dropbox_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="NAS Link",
    version="0.1.0",
    description="Private clipboard, file organization, search and backup hub for a home NAS.",
    lifespan=lifespan,
)


def cleanup_clipboard() -> None:
    db.execute("DELETE FROM clipboard_items WHERE expires_at < ?", (utc_now(),))


async def organize_in_background(file_id: str) -> None:
    try:
        item = await organizer.process(file_id)
        await realtime.broadcast({"type": "library_updated", "file": item})
    except Exception as exc:
        db.execute("UPDATE files SET status='error', error=? WHERE id=?", (str(exc)[:500], file_id))


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "nas-link-server",
        "version": app.version,
        "deepseek_configured": deepseek.configured,
        "security_ready": settings.token != "development-token" and len(settings.token) >= 24,
        "time": utc_now(),
    }


@app.get("/api/dashboard", dependencies=[Depends(require_token)])
def dashboard() -> dict:
    cleanup_clipboard()
    file_counts = {
        row["status"]: row["count"]
        for row in db.fetch_all("SELECT status,COUNT(*) AS count FROM files GROUP BY status")
    }
    snapshots = db.fetch_one(
        "SELECT COUNT(*) AS count,COALESCE(SUM(total_bytes),0) AS bytes FROM backup_snapshots WHERE status='complete'"
    ) or {"count": 0, "bytes": 0}
    disk = shutil.disk_usage(settings.data_root)
    return {
        "devices": len(realtime.online_ids()),
        "registered_devices": db.fetch_one("SELECT COUNT(*) AS count FROM devices")["count"],
        "files": file_counts,
        "backup_snapshots": snapshots,
        "storage": {"total": disk.total, "used": disk.used, "free": disk.free},
        "deepseek_configured": deepseek.configured,
    }


@app.post("/api/devices/register", dependencies=[Depends(require_token)])
def register_device(payload: DeviceRegistration, request: Request) -> dict:
    client_ip = request.client.host if request.client else None
    db.execute(
        """
        INSERT INTO devices(id,name,platform,last_seen,last_ip,app_version)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,platform=excluded.platform,last_seen=excluded.last_seen,
            last_ip=excluded.last_ip,app_version=excluded.app_version
        """,
        (payload.id, payload.name, payload.platform, utc_now(), client_ip, payload.app_version),
    )
    return {"ok": True, "device": payload.model_dump()}


@app.get("/api/devices", dependencies=[Depends(require_token)])
def list_devices() -> list[dict]:
    online = realtime.online_ids()
    result = db.fetch_all("SELECT * FROM devices ORDER BY last_seen DESC")
    for item in result:
        item["online"] = item["id"] in online
        item.pop("last_ip", None)
    return result


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, device_id: str = Query(...), token: str = Query(default="")) -> None:
    if not _valid_token(token):
        await websocket.close(code=4401)
        return
    await realtime.connect(device_id, websocket)
    try:
        await websocket.send_json({"type": "ready", "device_id": device_id, "server_time": utc_now()})
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "time": utc_now()})
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.disconnect(device_id, websocket)


@app.post("/api/clipboard", dependencies=[Depends(require_token)])
async def create_clipboard(payload: ClipboardCreate) -> dict:
    cleanup_clipboard()
    item_id = str(uuid.uuid4())
    created = datetime.now(UTC)
    content_hash = hashlib.sha256(payload.content.encode("utf-8")).hexdigest()
    expires = created + timedelta(minutes=settings.clipboard_ttl_minutes)
    db.execute(
        """
        INSERT INTO clipboard_items(id,source_device,content,content_hash,created_at,expires_at)
        VALUES(?,?,?,?,?,?)
        """,
        (item_id, payload.source_device, payload.content, content_hash, created.isoformat(), expires.isoformat()),
    )
    item = {
        "id": item_id,
        "source_device": payload.source_device,
        "content": payload.content,
        "content_hash": content_hash,
        "created_at": created.isoformat(),
        "expires_at": expires.isoformat(),
    }
    await realtime.broadcast({"type": "clipboard", "item": item}, exclude_device=payload.source_device)
    return item


@app.get("/api/clipboard", dependencies=[Depends(require_token)])
def clipboard_history(limit: int = Query(default=30, ge=1, le=100)) -> list[dict]:
    cleanup_clipboard()
    return db.fetch_all(
        "SELECT * FROM clipboard_items WHERE expires_at>=? ORDER BY created_at DESC LIMIT ?",
        (utc_now(), limit),
    )


@app.delete("/api/clipboard", dependencies=[Depends(require_token)])
def clear_clipboard() -> dict:
    db.execute("DELETE FROM clipboard_items")
    return {"ok": True}


@app.post("/api/library/upload", dependencies=[Depends(require_token)])
async def upload_library_file(
    request: Request,
    background: BackgroundTasks,
    filename: str = Query(..., min_length=1, max_length=500),
    source_device: str | None = Query(default=None, max_length=100),
) -> dict:
    item = await storage.receive_library_file(request, filename, source_device)
    if item.get("status") == "inbox":
        background.add_task(organize_in_background, item["id"])
    return item


@app.get("/api/library/files", dependencies=[Depends(require_token)])
def list_library_files(
    status_value: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    if status_value:
        rows = db.fetch_all("SELECT * FROM files WHERE status=? ORDER BY created_at DESC LIMIT ?", (status_value, limit))
    else:
        rows = db.fetch_all("SELECT * FROM files ORDER BY created_at DESC LIMIT ?", (limit,))
    return [Database.decode_file(row) for row in rows]


@app.get("/api/library/files/{file_id}/download", dependencies=[Depends(require_token)])
def download_library_file(file_id: str) -> FileResponse:
    item = db.fetch_one("SELECT * FROM files WHERE id=?", (file_id,))
    if not item:
        raise HTTPException(status_code=404, detail="File not found")
    path = settings.data_root / item["relative_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing")
    return FileResponse(path, filename=item["original_name"], media_type=item.get("mime_type"))


@app.post("/api/library/files/{file_id}/organize", dependencies=[Depends(require_token)])
async def organize_file(file_id: str) -> dict:
    return await organizer.process(file_id)


@app.post("/api/library/files/{file_id}/undo", dependencies=[Depends(require_token)])
def undo_organize(file_id: str) -> dict:
    try:
        return organizer.undo(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None


@app.post("/api/library/search", dependencies=[Depends(require_token)])
async def search_library(payload: SearchRequest) -> dict:
    try:
        keywords = await deepseek.expand_query(payload.query)
    except Exception:
        keywords = _basic_keywords(payload.query)
    rows = db.fetch_all(
        "SELECT * FROM files WHERE status IN ('organized','needs_review') ORDER BY created_at DESC LIMIT 1000"
    )
    scored: list[tuple[int, dict]] = []
    for row in rows:
        haystack = " ".join(
            str(row.get(field) or "")
            for field in ("original_name", "relative_path", "category", "subcategory", "tags_json", "summary", "extracted_text")
        ).lower()
        score = sum((8 if keyword.lower() in str(row.get("original_name") or "").lower() else 1) for keyword in keywords if keyword.lower() in haystack)
        if score:
            scored.append((score, row))
    if not scored:
        scored = [(0, row) for row in rows[: min(50, len(rows))]]
    scored.sort(key=lambda pair: (pair[0], pair[1]["created_at"]), reverse=True)
    candidates = [Database.decode_file(row) for _, row in scored[: payload.limit]]
    try:
        answer = await deepseek.answer_search(payload.query, candidates)
    except Exception as exc:
        answer = {
            "answer": "DeepSeek暂时不可用，已返回本地检索结果。",
            "file_ids": [item["id"] for item in candidates[:10]],
            "provider": "local",
            "warning": type(exc).__name__,
        }
    ordered = {item["id"]: item for item in candidates}
    selected = [ordered[item_id] for item_id in answer.get("file_ids", []) if item_id in ordered]
    if not selected:
        selected = candidates[:10]
    return {**answer, "keywords": keywords, "files": selected}


@app.post("/api/transfers", dependencies=[Depends(require_token)])
async def upload_transfer(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=500),
    source_device: str = Query(..., min_length=3, max_length=100),
    target_device: str | None = Query(default=None, max_length=100),
) -> dict:
    transfer = await storage.receive_transfer(request, filename, source_device, target_device)
    message = {"type": "file_offer", "transfer": transfer}
    if target_device:
        await realtime.send_to(target_device, message)
    else:
        await realtime.broadcast(message, exclude_device=source_device)
    return transfer


@app.get("/api/transfers", dependencies=[Depends(require_token)])
def list_transfers(device_id: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    if device_id:
        return db.fetch_all(
            "SELECT * FROM transfers WHERE target_device IS NULL OR target_device=? ORDER BY created_at DESC LIMIT ?",
            (device_id, limit),
        )
    return db.fetch_all("SELECT * FROM transfers ORDER BY created_at DESC LIMIT ?", (limit,))


@app.get("/api/transfers/{transfer_id}/download", dependencies=[Depends(require_token)])
def download_transfer(transfer_id: str) -> FileResponse:
    item = db.fetch_one("SELECT * FROM transfers WHERE id=?", (transfer_id,))
    if not item:
        raise HTTPException(status_code=404, detail="Transfer not found")
    path = settings.data_root / item["relative_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transfer file is missing")
    db.execute("UPDATE transfers SET status='downloaded', downloaded_at=? WHERE id=?", (utc_now(), transfer_id))
    return FileResponse(path, filename=item["filename"])


@app.post("/api/backups/plan", dependencies=[Depends(require_token)])
def create_backup_plan(payload: BackupPlan) -> dict:
    return storage.create_backup_plan(payload)


@app.put("/api/backups/{snapshot_id}/blobs/{sha256}", dependencies=[Depends(require_token)])
async def upload_backup_blob(snapshot_id: str, sha256: str, request: Request) -> dict:
    return await storage.receive_blob(request, snapshot_id, sha256)


@app.post("/api/backups/{snapshot_id}/commit", dependencies=[Depends(require_token)])
def commit_backup(snapshot_id: str) -> dict:
    return storage.commit_snapshot(snapshot_id)


@app.get("/api/backups", dependencies=[Depends(require_token)])
def list_backups(limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return db.fetch_all("SELECT * FROM backup_snapshots ORDER BY created_at DESC LIMIT ?", (limit,))


@app.get("/api/backups/{snapshot_id}/manifest", dependencies=[Depends(require_token)])
def backup_manifest(snapshot_id: str) -> dict:
    snapshot = db.fetch_one("SELECT * FROM backup_snapshots WHERE id=?", (snapshot_id,))
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    entries = db.fetch_all(
        "SELECT relative_path,sha256,size,mtime_ns FROM backup_entries WHERE snapshot_id=? ORDER BY relative_path",
        (snapshot_id,),
    )
    return {**snapshot, "entries": entries}


@app.get("/api/backups/{snapshot_id}/restore", dependencies=[Depends(require_token)])
def restore_backup_file(snapshot_id: str, path: str = Query(...)) -> FileResponse:
    try:
        blob, filename = storage.blob_path_for_snapshot_file(snapshot_id, path)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Backup file not found") from None
    return FileResponse(blob, filename=filename)
