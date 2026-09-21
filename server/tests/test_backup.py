from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.schemas import BackupPlan
from app.storage import StorageService, normalize_relative_path


def test_backup_plan_is_deduplicated_and_rejects_traversal(tmp_path: Path) -> None:
    settings = Settings(NAS_LINK_TOKEN="test-token-that-is-long-enough", NAS_LINK_DATA_ROOT=tmp_path)
    settings.ensure_directories()
    service = StorageService(settings, Database(settings.db_path))
    digest = "a" * 64
    plan = BackupPlan(
        device_id="windows-office",
        root_name="Documents",
        files=[{"path": "合同/报价.txt", "sha256": digest, "size": 12, "mtime_ns": 123}],
    )
    result = service.create_backup_plan(plan)
    assert result["missing_hashes"] == [digest]
    assert result["total_files"] == 1
    with pytest.raises(ValueError):
        normalize_relative_path("../../outside.txt")

