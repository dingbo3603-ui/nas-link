import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import AsyncIterator

from fastapi import HTTPException, Request, status

from .config import Settings
from .db import Database, utc_now
from .extractors import guess_mime
from .organizer import safe_filename, sha256_file
from .schemas import BackupPlan


def normalize_relative_path(value: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ValueError(f"Unsafe relative path: {value}")
    return candidate.as_posix()


async def stream_request_to_file(request: Request, destination: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        async for chunk in request.stream():
            if not chunk:
                continue
            digest.update(chunk)
            size += len(chunk)
            handle.write(chunk)
    return digest.hexdigest(), size


class StorageService:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db

    def ingest_local_file(self, source: Path, source_device: str = "nas-dropbox") -> dict:
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(source)
        file_id = str(uuid.uuid4())
        safe_name = safe_filename(source.name)
        sha256 = sha256_file(source)
        size = source.stat().st_size
        duplicate = self.db.fetch_one(
            "SELECT id,relative_path FROM files WHERE sha256=? AND status IN ('organized','needs_review') ORDER BY created_at LIMIT 1",
            (sha256,),
        )
        if duplicate:
            destination = self.settings.data_root / "review" / "duplicates" / f"{file_id}-{safe_name}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            status_value = "duplicate"
            duplicate_of = duplicate["id"]
        else:
            destination = self.settings.data_root / "inbox" / utc_now()[:10] / f"{file_id}-{safe_name}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            status_value = "inbox"
            duplicate_of = None
        relative = destination.relative_to(self.settings.data_root).as_posix()
        self.db.execute(
            """
            INSERT INTO files(
                id,original_name,relative_path,source_device,sha256,size,mime_type,extension,
                status,duplicate_of,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                file_id,
                safe_name,
                relative,
                source_device,
                sha256,
                size,
                guess_mime(Path(safe_name)),
                Path(safe_name).suffix.lower(),
                status_value,
                duplicate_of,
                utc_now(),
            ),
        )
        row = self.db.fetch_one("SELECT * FROM files WHERE id=?", (file_id,))
        return Database.decode_file(row or {})

    async def receive_library_file(
        self,
        request: Request,
        filename: str,
        source_device: str | None,
    ) -> dict:
        file_id = str(uuid.uuid4())
        safe_name = safe_filename(filename)
        day = utc_now()[:10]
        relative = Path("inbox") / day / f"{file_id}-{safe_name}"
        destination = self.settings.data_root / relative
        temp = destination.with_suffix(destination.suffix + ".uploading")
        try:
            sha256, size = await stream_request_to_file(request, temp)
            duplicate = self.db.fetch_one(
                "SELECT id,relative_path FROM files WHERE sha256=? AND status IN ('organized','needs_review') ORDER BY created_at LIMIT 1",
                (sha256,),
            )
            if duplicate:
                temp.unlink(missing_ok=True)
                status_value = "duplicate"
                duplicate_of = duplicate["id"]
                relative_value = duplicate["relative_path"]
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp, destination)
                status_value = "inbox"
                duplicate_of = None
                relative_value = relative.as_posix()
            self.db.execute(
                """
                INSERT INTO files(
                    id,original_name,relative_path,source_device,sha256,size,mime_type,extension,
                    status,duplicate_of,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    file_id,
                    safe_name,
                    relative_value,
                    source_device,
                    sha256,
                    size,
                    guess_mime(Path(safe_name)),
                    Path(safe_name).suffix.lower(),
                    status_value,
                    duplicate_of,
                    utc_now(),
                ),
            )
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        row = self.db.fetch_one("SELECT * FROM files WHERE id=?", (file_id,))
        return Database.decode_file(row or {})

    async def receive_transfer(
        self,
        request: Request,
        filename: str,
        source_device: str,
        target_device: str | None,
    ) -> dict:
        transfer_id = str(uuid.uuid4())
        safe_name = safe_filename(filename)
        relative = Path("transfers") / "pending" / f"{transfer_id}-{safe_name}"
        destination = self.settings.data_root / relative
        temp = destination.with_suffix(destination.suffix + ".uploading")
        try:
            sha256, size = await stream_request_to_file(request, temp)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp, destination)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        self.db.execute(
            """
            INSERT INTO transfers(id,source_device,target_device,filename,relative_path,sha256,size,status,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                transfer_id,
                source_device,
                target_device,
                safe_name,
                relative.as_posix(),
                sha256,
                size,
                "pending",
                utc_now(),
            ),
        )
        return self.db.fetch_one("SELECT * FROM transfers WHERE id=?", (transfer_id,)) or {}

    def create_backup_plan(self, plan: BackupPlan) -> dict:
        snapshot_id = str(uuid.uuid4())
        rows = []
        hashes: set[str] = set()
        total_bytes = 0
        for item in plan.files:
            relative = normalize_relative_path(item.path)
            rows.append((snapshot_id, relative, item.sha256, item.size, item.mtime_ns))
            hashes.add(item.sha256)
            total_bytes += item.size
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO backup_snapshots(id,device_id,root_name,status,created_at,total_files,total_bytes)
                VALUES(?,?,?,?,?,?,?)
                """,
                (snapshot_id, plan.device_id, plan.root_name, "uploading", utc_now(), len(rows), total_bytes),
            )
            connection.executemany(
                "INSERT INTO backup_entries(snapshot_id,relative_path,sha256,size,mtime_ns) VALUES(?,?,?,?,?)",
                rows,
            )
        existing = {
            row["sha256"]
            for row in self.db.fetch_all("SELECT sha256,relative_path FROM blobs")
            if (self.settings.data_root / row["relative_path"]).exists()
        }
        return {
            "snapshot_id": snapshot_id,
            "missing_hashes": sorted(hashes - existing),
            "deduplicated_files": len(rows) - sum(1 for row in rows if row[2] not in existing),
            "total_files": len(rows),
            "total_bytes": total_bytes,
        }

    async def receive_blob(self, request: Request, snapshot_id: str, sha256: str) -> dict:
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sha256")
        entry = self.db.fetch_one(
            "SELECT size FROM backup_entries WHERE snapshot_id=? AND sha256=? LIMIT 1",
            (snapshot_id, sha256),
        )
        if not entry:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blob is not part of this snapshot")
        existing = self.db.fetch_one("SELECT * FROM blobs WHERE sha256=?", (sha256,))
        if existing and (self.settings.data_root / existing["relative_path"]).exists():
            return {"sha256": sha256, "status": "exists"}
        relative = Path("backups") / "blobs" / sha256[:2] / sha256[2:4] / sha256
        destination = self.settings.data_root / relative
        temp = destination.with_suffix(".uploading")
        try:
            actual_hash, actual_size = await stream_request_to_file(request, temp)
            if actual_hash != sha256:
                raise HTTPException(status_code=422, detail="Blob checksum mismatch")
            if actual_size != entry["size"]:
                raise HTTPException(status_code=422, detail="Blob size mismatch")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp, destination)
            self.db.execute(
                "INSERT OR IGNORE INTO blobs(sha256,relative_path,size,created_at) VALUES(?,?,?,?)",
                (sha256, relative.as_posix(), actual_size, utc_now()),
            )
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return {"sha256": sha256, "status": "stored", "size": actual_size}

    def commit_snapshot(self, snapshot_id: str) -> dict:
        snapshot = self.db.fetch_one("SELECT * FROM backup_snapshots WHERE id=?", (snapshot_id,))
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        entries = self.db.fetch_all(
            "SELECT relative_path,sha256,size,mtime_ns FROM backup_entries WHERE snapshot_id=? ORDER BY relative_path",
            (snapshot_id,),
        )
        blobs = {row["sha256"]: row for row in self.db.fetch_all("SELECT * FROM blobs")}
        missing = [entry["sha256"] for entry in entries if entry["sha256"] not in blobs]
        if missing:
            raise HTTPException(status_code=409, detail={"message": "Snapshot still has missing blobs", "missing": missing[:100]})
        manifest_relative = Path("backups") / "manifests" / f"{snapshot_id}.json"
        manifest = {
            "id": snapshot_id,
            "device_id": snapshot["device_id"],
            "root_name": snapshot["root_name"],
            "created_at": snapshot["created_at"],
            "entries": entries,
        }
        (self.settings.data_root / manifest_relative).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.db.execute(
            "UPDATE backup_snapshots SET status='complete', completed_at=? WHERE id=?",
            (utc_now(), snapshot_id),
        )
        return self.db.fetch_one("SELECT * FROM backup_snapshots WHERE id=?", (snapshot_id,)) or {}

    def blob_path_for_snapshot_file(self, snapshot_id: str, relative_path: str) -> tuple[Path, str]:
        normalized = normalize_relative_path(relative_path)
        row = self.db.fetch_one(
            """
            SELECT e.sha256,b.relative_path
            FROM backup_entries e JOIN blobs b ON b.sha256=e.sha256
            WHERE e.snapshot_id=? AND e.relative_path=?
            """,
            (snapshot_id, normalized),
        )
        if not row:
            raise FileNotFoundError(normalized)
        return self.settings.data_root / row["relative_path"], Path(normalized).name
