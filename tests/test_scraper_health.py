from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import pytest

from shared import scraper_health


@pytest.mark.parametrize(
    ("job_name", "error_message", "expected_fragment"),
    [
        ("manheim_scrape", "boom", "Manheim scrape"),
        ("grays", "Playwright TimeoutError", "timed out"),
        ("grays", "timed out waiting for selector", "timed out"),
        (None, None, "did not complete"),
    ],
)
def test_friendly_health_failure(job_name, error_message, expected_fragment) -> None:
    assert expected_fragment in scraper_health.friendly_health_failure(job_name, error_message)


def test_load_csv_handles_missing_and_empty_files(tmp_path) -> None:
    assert scraper_health._load_csv(tmp_path / "missing.csv").empty

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    assert scraper_health._load_csv(empty).empty

    populated = tmp_path / "rows.csv"
    populated.write_text("a\n1\n2\n", encoding="utf-8")
    assert len(scraper_health._load_csv(populated)) == 2


def test_file_age_and_modified_helpers(tmp_path) -> None:
    missing = tmp_path / "missing.csv"
    assert scraper_health._file_age_minutes(missing) is None
    assert scraper_health._file_modified_iso(missing) is None

    path = tmp_path / "rows.csv"
    path.write_text("a\n1\n", encoding="utf-8")
    os.utime(path, (time.time() - 3600, time.time() - 3600))

    assert scraper_health._file_age_minutes(path) == pytest.approx(60.0, abs=1.0)
    assert scraper_health._file_modified_iso(path).endswith("+00:00")


@pytest.mark.parametrize(
    ("count", "age_minutes", "allow_zero", "expected"),
    [
        (10, None, False, "failure"),
        (0, 5.0, False, "partial"),
        (0, 5.0, True, "healthy"),
        (10, 5.0, False, "healthy"),
        (10, 120.0, False, "healthy"),
        (10, 121.0, False, "partial"),
        (10, 241.0, False, "failure"),
    ],
)
def test_stage_status(count, age_minutes, allow_zero, expected) -> None:
    assert scraper_health._stage_status(count, age_minutes, 120, allow_zero=allow_zero) == expected


def test_top_failure_reasons_counts_and_normalizes(monkeypatch, tmp_path) -> None:
    failures = tmp_path / "excluded_listings.csv"
    failures.write_text(
        "reason_code,url\nNO_PRICE,a\nNO_PRICE,b\n,c\nNO_VIN,d\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(scraper_health, "dataset_path", lambda name: tmp_path / name)

    counts = scraper_health._top_failure_reasons()

    assert dict(zip(counts["reason_code"], counts["count"])) == {"NO_PRICE": 2, "Unknown": 1, "NO_VIN": 1}


def test_top_failure_reasons_falls_back_to_legacy_path(monkeypatch, tmp_path) -> None:
    legacy = tmp_path / "scrape_failures.csv"
    legacy.write_text("reason_code\nTIMEOUT\n", encoding="utf-8")
    monkeypatch.setattr(scraper_health, "dataset_path", lambda name: tmp_path / "missing" / name)
    monkeypatch.setattr(scraper_health, "LEGACY_FAILURES_PATH", legacy)

    counts = scraper_health._top_failure_reasons()

    assert list(counts["reason_code"]) == ["TIMEOUT"]


def test_top_failure_reasons_missing_and_unreadable_sources(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(scraper_health, "dataset_path", lambda name: tmp_path / "missing" / name)
    monkeypatch.setattr(scraper_health, "LEGACY_FAILURES_PATH", tmp_path / "missing" / "legacy.csv")
    assert scraper_health._top_failure_reasons().empty

    broken = tmp_path / "broken.csv"
    broken.write_text("other_column\n1\n", encoding="utf-8")
    monkeypatch.setattr(scraper_health, "LEGACY_FAILURES_PATH", broken)
    counts = scraper_health._top_failure_reasons()
    assert counts.empty
    assert list(counts.columns) == ["reason_code", "count"]


def _configure_datasets(monkeypatch, tmp_path) -> None:
    """Point every configured dataset at tmp_path and write a couple of fixtures."""
    config = {}
    for key, entry in scraper_health.DATASET_CONFIG.items():
        path = tmp_path / f"{key}.csv"
        config[key] = {**entry, "path": path}
    monkeypatch.setattr(scraper_health, "DATASET_CONFIG", config)
    monkeypatch.setattr(scraper_health, "_top_failure_reasons", lambda: pd.DataFrame([{"reason_code": "NO_VIN", "count": 3}]))

    Path(config["links"]["path"]).write_text("url\nhttps://example.com/a\n", encoding="utf-8")
    Path(config["active"]["path"]).write_text("url,status\na,Active\nb,\nc,Active\n", encoding="utf-8")


def test_build_scraper_health_snapshot(monkeypatch, tmp_path) -> None:
    _configure_datasets(monkeypatch, tmp_path)

    snapshot = scraper_health.build_scraper_health_snapshot(
        job_name="daily", job_status="failure", error_message="boom"
    )

    assert snapshot["job_name"] == "daily"
    assert snapshot["job_status"] == "failure"
    assert snapshot["error_message"] == "boom"
    assert snapshot["dataset_metrics"]["links"]["count"] == 1
    assert snapshot["dataset_metrics"]["links"]["status"] == "healthy"
    # Missing dataset files are reported as failures and listed as stale.
    assert snapshot["dataset_metrics"]["sold"]["status"] == "failure"
    assert "sold" in snapshot["stale_datasets"]
    assert snapshot["active_status_mix"] == {"Active": 2, "Unknown": 1}
    assert snapshot["stage_metrics"]["links_scraped"]["count"] == 1
    assert snapshot["stage_metrics"]["vehicles_excluded"]["status"] == "stale"
    assert snapshot["top_failure_reasons"] == [{"reason_code": "NO_VIN", "count": 3}]


def test_build_scraper_health_snapshot_without_active_status_column(monkeypatch, tmp_path) -> None:
    _configure_datasets(monkeypatch, tmp_path)
    Path(scraper_health.DATASET_CONFIG["active"]["path"]).write_text("url\na\n", encoding="utf-8")

    assert scraper_health.build_scraper_health_snapshot()["active_status_mix"] == {}


def test_write_and_load_scraper_health_report(monkeypatch, tmp_path) -> None:
    _configure_datasets(monkeypatch, tmp_path)
    report_dir = tmp_path / "health"

    snapshot = scraper_health.write_scraper_health_report(report_dir=report_dir, job_name="daily")

    json_path = snapshot["paths"]["json"]
    csv_path = snapshot["paths"]["failure_reasons_csv"]
    assert json.loads(json_path.read_text(encoding="utf-8"))["job_name"] == "daily"
    assert list(pd.read_csv(csv_path)["reason_code"]) == ["NO_VIN"]
    assert scraper_health.load_scraper_health_report(json_path)["job_name"] == "daily"


def test_load_scraper_health_report_missing_or_invalid(tmp_path) -> None:
    assert scraper_health.load_scraper_health_report(tmp_path / "missing.json") is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert scraper_health.load_scraper_health_report(broken) is None
