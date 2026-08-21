from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.backup_runtime_data import create_runtime_backup, verify_runtime_backup


def _write_csv(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("value\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_runtime_backup_includes_reports_and_verifies_core_csvs(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    backup_dir = tmp_path / "backups"
    _write_csv(repo_root / "CSV_data/scrapers/sold_cars.csv", ["sold"])
    _write_csv(repo_root / "CSV_data/restricted/sold_cars_restricted.csv", ["restricted"])
    _write_csv(repo_root / "CSV_data/ai/ai_listing_valuations.csv", [])
    _write_csv(repo_root / "CSV_data/reports/repair_review_live_queue.csv", ["review"])

    backup_path = create_runtime_backup(
        repo_root=repo_root,
        backup_dir=backup_dir,
        created_at=datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc),
    )

    with ZipFile(backup_path) as archive:
        assert "CSV_data/reports/repair_review_live_queue.csv" in archive.namelist()
        assert "backup_manifest.txt" in archive.namelist()
    assert verify_runtime_backup(backup_path)["CSV_data/reports/repair_review_live_queue.csv"] == 1
    if os.name != "nt":
        assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600


def test_runtime_backup_rejects_destination_inside_runtime_tree(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    _write_csv(repo_root / "CSV_data/scrapers/sold_cars.csv", ["sold"])

    with pytest.raises(ValueError, match="outside the repository"):
        create_runtime_backup(repo_root=repo_root, backup_dir=repo_root / "backups")
