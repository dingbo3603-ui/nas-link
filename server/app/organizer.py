import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .db import Database, utc_now
from .deepseek import Classification, DeepSeekClient
from .extractors import extract_text, guess_mime, image_metadata


CATEGORY_BY_EXTENSION = {
    ".pdf": "文档",
    ".doc": "文档",
    ".docx": "文档",
    ".txt": "文档",
    ".md": "文档",
    ".rtf": "文档",
    ".xlsx": "表格",
    ".xls": "表格",
    ".xlsm": "表格",
    ".csv": "表格",
    ".ods": "表格",
    ".jpg": "图片",
    ".jpeg": "图片",
    ".png": "图片",
    ".webp": "图片",
    ".gif": "图片",
    ".svg": "图片",
    ".heic": "图片",
    ".mp4": "视频",
    ".mov": "视频",
    ".mkv": "视频",
    ".avi": "视频",
    ".mp3": "音频",
    ".wav": "音频",
    ".m4a": "音频",
    ".flac": "音频",
    ".zip": "压缩包",
    ".rar": "压缩包",
    ".7z": "压缩包",
    ".tar": "压缩包",
    ".gz": "压缩包",
    ".py": "代码",
    ".js": "代码",
    ".ts": "代码",
    ".tsx": "代码",
    ".jsx": "代码",
    ".html": "代码",
    ".css": "代码",
    ".sql": "代码",
    ".json": "代码",
    ".yaml": "代码",
    ".yml": "代码",
    ".exe": "安装包",
    ".msi": "安装包",
    ".dmg": "安装包",
    ".pkg": "安装包",
    ".apk": "安装包",
}


@dataclass
class LocalClassification:
    category: str
    subcategory: str
    tags: list[str]
    summary: str
    confidence: float
    source: str = "local"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def classify_locally(path: Path, mime_type: str | None = None) -> LocalClassification:
    suffix = path.suffix.lower()
    category = CATEGORY_BY_EXTENSION.get(suffix, "其他")
    confidence = 0.96 if suffix in CATEGORY_BY_EXTENSION else 0.55
    stem_tokens = [token for token in re.split(r"[_\-\s.]+", path.stem) if len(token) > 1][:6]
    metadata = image_metadata(path)
    summary = f"{category}文件，原文件名为 {path.name}"
    if metadata:
        summary += f"；{metadata}"
    return LocalClassification(
        category=category,
        subcategory="未分类",
        tags=[suffix.lstrip("."), *stem_tokens][:8],
        summary=summary[:160],
        confidence=confidence,
    )


def safe_filename(name: str) -> str:
    name = Path(name).name
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", name).strip(" .")
    return cleaned[:220] or "未命名文件"


def unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / safe_filename(filename)
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for counter in range(2, 10_000):
        alternate = directory / f"{stem} ({counter}){suffix}"
        if not alternate.exists():
            return alternate
    raise RuntimeError("Unable to allocate a unique destination filename")


class Organizer:
    def __init__(self, settings: Settings, db: Database, deepseek: DeepSeekClient):
        self.settings = settings
        self.db = db
        self.deepseek = deepseek

    async def process(self, file_id: str) -> dict:
        row = self.db.fetch_one("SELECT * FROM files WHERE id=?", (file_id,))
        if not row:
            raise FileNotFoundError(file_id)
        source = self.settings.data_root / row["relative_path"]
        if not source.exists():
            self.db.execute("UPDATE files SET status='error', error=? WHERE id=?", ("Source file is missing", file_id))
            raise FileNotFoundError(source)

        extracted = extract_text(source)
        local = classify_locally(source, row.get("mime_type"))
        classification: LocalClassification | Classification = local
        ai_error = ""
        if self.deepseek.configured:
            try:
                classification = await self.deepseek.classify(
                    row["original_name"], row.get("mime_type") or guess_mime(source), row["size"], extracted
                )
            except Exception as exc:
                ai_error = f"DeepSeek分类失败，已使用本地规则：{type(exc).__name__}"

        now = datetime.now(UTC)
        destination_dir = (
            self.settings.data_root
            / "library"
            / classification.category
            / classification.subcategory
            / f"{now.year:04d}"
            / f"{now.month:02d}"
        )
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = unique_destination(destination_dir, row["original_name"])
        relative_destination = destination.relative_to(self.settings.data_root).as_posix()

        if self.settings.auto_organize:
            os.replace(source, destination)
            status = "organized"
            organized_at = utc_now()
        else:
            status = "needs_review"
            organized_at = None
            relative_destination = row["relative_path"]

        with self.db.transaction() as connection:
            connection.execute(
                """
                UPDATE files
                SET relative_path=?, category=?, subcategory=?, tags_json=?, summary=?, extracted_text=?,
                    status=?, confidence=?, organized_at=?, error=?
                WHERE id=?
                """,
                (
                    relative_destination,
                    classification.category,
                    classification.subcategory,
                    json.dumps(classification.tags, ensure_ascii=False),
                    classification.summary,
                    extracted,
                    status,
                    classification.confidence,
                    organized_at,
                    ai_error or None,
                    file_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO file_events(file_id,event_type,from_path,to_path,details_json,created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    file_id,
                    "organized" if status == "organized" else "classified",
                    row["relative_path"],
                    relative_destination,
                    json.dumps({"classification_source": classification.source}, ensure_ascii=False),
                    utc_now(),
                ),
            )
        updated = self.db.fetch_one("SELECT * FROM files WHERE id=?", (file_id,))
        return Database.decode_file(updated or row)

    def undo(self, file_id: str) -> dict:
        row = self.db.fetch_one("SELECT * FROM files WHERE id=?", (file_id,))
        if not row:
            raise FileNotFoundError(file_id)
        source = self.settings.data_root / row["relative_path"]
        if not source.exists():
            raise FileNotFoundError(source)
        inbox_dir = self.settings.data_root / "inbox" / "restored"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        destination = unique_destination(inbox_dir, row["original_name"])
        os.replace(source, destination)
        relative = destination.relative_to(self.settings.data_root).as_posix()
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE files SET relative_path=?, status='needs_review', organized_at=NULL WHERE id=?",
                (relative, file_id),
            )
            connection.execute(
                """
                INSERT INTO file_events(file_id,event_type,from_path,to_path,details_json,created_at)
                VALUES(?,?,?,?,?,?)
                """,
                (file_id, "undo", row["relative_path"], relative, "{}", utc_now()),
            )
        return Database.decode_file(self.db.fetch_one("SELECT * FROM files WHERE id=?", (file_id,)) or row)

