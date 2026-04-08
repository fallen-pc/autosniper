from __future__ import annotations

import io
import zipfile

import pytest

from shared import data_loader


def _zip_bytes(filename: str, payload: bytes = b"test") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, payload)
    return buffer.getvalue()


def test_extract_zip_rejects_path_traversal(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "CSV_data"
    data_dir.mkdir()
    monkeypatch.setattr(data_loader, "DATA_DIR", data_dir)

    with pytest.raises(ValueError, match="Unsafe archive member path|escapes data directory"):
        data_loader._extract_zip(_zip_bytes("../outside.txt"))


def test_extract_zip_writes_under_data_dir(monkeypatch, tmp_path) -> None:
    data_dir = tmp_path / "CSV_data"
    data_dir.mkdir()
    monkeypatch.setattr(data_loader, "DATA_DIR", data_dir)

    data_loader._extract_zip(_zip_bytes("CSV_data/scrapers/vehicle_static_details.csv", b"col\n1\n"))

    assert (data_dir / "scrapers" / "vehicle_static_details.csv").read_text(encoding="utf-8") == "col\n1\n"
