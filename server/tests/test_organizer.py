import asyncio
from pathlib import Path

from app.config import Settings
from app.db import Database, utc_now
from app.deepseek import DeepSeekClient
from app.organizer import Organizer, classify_locally, safe_filename, sha256_file
from app.storage import StorageService


def make_settings(tmp_path: Path, auto_organize: bool = True) -> Settings:
    settings = Settings(
        NAS_LINK_TOKEN="test-token-that-is-long-enough",
        NAS_LINK_DATA_ROOT=tmp_path,
        NAS_LINK_AUTO_ORGANIZE=auto_organize,
        DEEPSEEK_API_KEY="",
    )
    settings.ensure_directories()
    return settings


def test_safe_filename_and_local_classification(tmp_path: Path) -> None:
    path = tmp_path / "2026德国发票.xlsx"
    path.write_bytes(b"placeholder")
    assert safe_filename('../a:b?.xlsx') == 'a_b_.xlsx'
    result = classify_locally(path)
    assert result.category == "表格"
    assert result.confidence > 0.9
    assert sha256_file(path) == sha256_file(path)


def test_dropbox_ingest_and_reversible_organize(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    storage = StorageService(settings, db)
    source = settings.data_root / "dropbox" / "客户说明.txt"
    source.write_text("这是一个客户说明文件，包含订单处理方法。", encoding="utf-8")

    item = storage.ingest_local_file(source)
    assert item["status"] == "inbox"
    assert not source.exists()

    organizer = Organizer(settings, db, DeepSeekClient(settings))
    organized = asyncio.run(organizer.process(item["id"]))
    assert organized["status"] == "organized"
    assert organized["category"] == "文档"
    assert (settings.data_root / organized["relative_path"]).exists()

    restored = organizer.undo(item["id"])
    assert restored["status"] == "needs_review"
    assert restored["relative_path"].startswith("inbox/restored/")
    assert (settings.data_root / restored["relative_path"]).exists()

