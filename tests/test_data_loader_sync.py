from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

import pytest

from shared import data_loader


class _FakeResponse:
    def __init__(self, content: bytes = b"", headers: dict[str, str] | None = None, error: Exception | None = None):
        self.content = content
        self.headers = headers or {}
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error


@pytest.fixture()
def data_dir(monkeypatch, tmp_path) -> Path:
    directory = tmp_path / "CSV_data"
    directory.mkdir()
    monkeypatch.setattr(data_loader, "DATA_DIR", directory)
    monkeypatch.setattr(data_loader, "_SYNC_MARKER", directory / ".remote_sync.json")
    monkeypatch.setattr(data_loader, "_last_sync_time", 0.0)
    for name in ("AUTOSNIPER_DATA_URL", "AUTOSNIPER_DATA_TOKEN", "AUTOSNIPER_DATA_UPLOAD_URL"):
        monkeypatch.delenv(name, raising=False)
    return directory


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_dataset_relpath_maps_known_names_and_passes_through_paths() -> None:
    assert data_loader._dataset_relpath("sold_cars.csv") == Path("scrapers") / "sold_cars.csv"
    assert data_loader._dataset_relpath("custom/thing.csv") == Path("custom/thing.csv")
    assert data_loader._dataset_relpath("unmapped.csv") == Path("unmapped.csv")


def test_dataset_path_is_relative_to_data_dir(data_dir) -> None:
    assert data_loader.dataset_path("sold_cars.csv") == data_dir / "scrapers" / "sold_cars.csv"


def test_missing_required_files(data_dir) -> None:
    assert data_loader._missing_required_files() == data_loader.REQUIRED_FILES

    for name in data_loader.REQUIRED_FILES:
        path = data_loader.dataset_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("col\n", encoding="utf-8")

    assert data_loader._missing_required_files() == []


def test_should_refresh_rules(monkeypatch, data_dir) -> None:
    monkeypatch.setenv("AUTOSNIPER_DATA_URL", "https://example.com/data.zip")

    assert data_loader._should_refresh(0) is True
    assert data_loader._should_refresh(30) is True  # no marker yet

    data_loader._SYNC_MARKER.write_text("{not json", encoding="utf-8")
    assert data_loader._should_refresh(30) is True

    data_loader._SYNC_MARKER.write_text(
        json.dumps({"timestamp": time.time(), "url": "https://example.com/other.zip"}), encoding="utf-8"
    )
    assert data_loader._should_refresh(30) is True

    data_loader._SYNC_MARKER.write_text(
        json.dumps({"timestamp": time.time(), "url": "https://example.com/data.zip"}), encoding="utf-8"
    )
    assert data_loader._should_refresh(30) is False

    data_loader._SYNC_MARKER.write_text(
        json.dumps({"timestamp": time.time() - 7200, "url": "https://example.com/data.zip"}), encoding="utf-8"
    )
    assert data_loader._should_refresh(30) is True


def test_extract_zip_skips_directories_and_maps_flat_names(data_dir) -> None:
    payload = _zip_bytes({"nested/": b"", "sold_cars.csv": b"col\n1\n"})

    data_loader._extract_zip(payload)

    assert (data_dir / "scrapers" / "sold_cars.csv").read_text(encoding="utf-8") == "col\n1\n"


def test_extract_zip_rejects_absolute_member_paths(data_dir) -> None:
    with pytest.raises(ValueError, match="Unsafe archive member path"):
        data_loader._extract_zip(_zip_bytes({"/etc/passwd": b"x"}))


def test_download_remote_bundle_extracts_zip(monkeypatch, data_dir) -> None:
    monkeypatch.setenv("AUTOSNIPER_DATA_URL", "https://example.com/bundle.zip")
    monkeypatch.setenv("AUTOSNIPER_DATA_TOKEN", "secret-token")
    captured: dict[str, object] = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update({"url": url, "headers": headers, "timeout": timeout})
        return _FakeResponse(_zip_bytes({"CSV_data/scrapers/sold_cars.csv": b"col\n1\n"}))

    monkeypatch.setattr(data_loader.requests, "get", fake_get)

    data_loader._download_remote_bundle()

    assert captured["headers"] == {"Authorization": "Bearer secret-token"}
    assert (data_dir / "scrapers" / "sold_cars.csv").exists()
    marker = json.loads(data_loader._SYNC_MARKER.read_text(encoding="utf-8"))
    assert marker["url"] == "https://example.com/bundle.zip"


def test_download_remote_bundle_writes_single_csv(monkeypatch, data_dir) -> None:
    monkeypatch.setenv("AUTOSNIPER_DATA_URL", "https://example.com/sold_cars.csv")
    monkeypatch.setattr(
        data_loader.requests,
        "get",
        lambda url, headers=None, timeout=None: _FakeResponse(b"col\n1\n", {"Content-Type": "text/csv"}),
    )

    data_loader._download_remote_bundle()

    assert (data_dir / "scrapers" / "sold_cars.csv").read_text(encoding="utf-8") == "col\n1\n"


def test_download_remote_bundle_noop_without_url(monkeypatch, data_dir) -> None:
    def fail(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("network access attempted")

    monkeypatch.setattr(data_loader.requests, "get", fail)

    data_loader._download_remote_bundle()

    assert not data_loader._SYNC_MARKER.exists()


def test_build_zip_bytes_skips_missing_files(data_dir) -> None:
    path = data_loader.dataset_path("sold_cars.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("col\n1\n", encoding="utf-8")

    payload = data_loader._build_zip_bytes(["sold_cars.csv", "referred_cars.csv"])

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["CSV_data/scrapers/sold_cars.csv"]


def test_upload_remote_data_bundle_requires_url(data_dir) -> None:
    assert data_loader.upload_remote_data_bundle() is False


def test_upload_remote_data_bundle_puts_zip(monkeypatch, data_dir) -> None:
    monkeypatch.setenv("AUTOSNIPER_DATA_UPLOAD_URL", "https://example.com/upload")
    path = data_loader.dataset_path("sold_cars.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("col\n1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_put(url, headers=None, data=None, timeout=None):
        captured.update({"url": url, "data": data})
        return _FakeResponse()

    monkeypatch.setattr(data_loader.requests, "put", fake_put)

    assert data_loader.upload_remote_data_bundle(["sold_cars.csv"]) is True
    with zipfile.ZipFile(io.BytesIO(captured["data"])) as archive:
        assert archive.namelist() == ["CSV_data/scrapers/sold_cars.csv"]


def test_upload_remote_data_bundle_swallows_errors(monkeypatch, data_dir) -> None:
    monkeypatch.setenv("AUTOSNIPER_DATA_UPLOAD_URL", "https://example.com/upload")

    def fake_put(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(data_loader.requests, "put", fake_put)

    assert data_loader.upload_remote_data_bundle() is False


def test_sync_remote_data_skips_when_not_configured(monkeypatch, data_dir) -> None:
    monkeypatch.setattr(
        data_loader, "_download_remote_bundle", lambda: pytest.fail("download should not run")
    )

    data_loader.sync_remote_data()


def test_sync_remote_data_downloads_when_forced(monkeypatch, data_dir) -> None:
    monkeypatch.setenv("AUTOSNIPER_DATA_URL", "https://example.com/bundle.zip")
    calls: list[int] = []
    monkeypatch.setattr(data_loader, "_download_remote_bundle", lambda: calls.append(1))

    data_loader.sync_remote_data(force=True)

    assert calls == [1]


def test_ensure_datasets_available_reports_missing(monkeypatch, data_dir) -> None:
    monkeypatch.setattr(data_loader, "sync_remote_data", lambda force=False: None)
    path = data_loader.dataset_path("sold_cars.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("col\n", encoding="utf-8")

    missing = data_loader.ensure_datasets_available(["sold_cars.csv", "referred_cars.csv"])

    assert missing == ["referred_cars.csv"]


def test_sync_once_runs_at_most_once_per_cache_window(monkeypatch, data_dir) -> None:
    monkeypatch.setattr(data_loader, "_missing_required_files", lambda: [])
    calls: list[bool] = []
    monkeypatch.setattr(data_loader, "sync_remote_data", lambda force=False: calls.append(force))

    data_loader._sync_once()
    data_loader._sync_once()

    assert calls == [False]
