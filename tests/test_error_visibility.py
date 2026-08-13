from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest

import scripts.update_master as update_master
import shared.csv_utils as csv_utils
import shared.scraper_health as scraper_health
import shared.telegram_alerts as telegram_alerts

MALFORMED_CSV = 'url,value\n"unterminated,1\n'


def _write_malformed(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MALFORMED_CSV, encoding="utf-8")
    return path


def test_read_csv_or_empty_logs_unreadable_file(tmp_path, caplog):
    path = _write_malformed(tmp_path / "broken.csv")

    with caplog.at_level(logging.WARNING, logger="shared.csv_utils"):
        df = csv_utils.read_csv_or_empty(path)

    assert df.empty
    assert "Unreadable CSV" in caplog.text
    assert "broken.csv" in caplog.text


def test_count_csv_records_logs_unreadable_file(tmp_path, caplog, monkeypatch):
    path = tmp_path / "counts.csv"
    path.write_text("url\na\n", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr(Path, "open", _boom)

    with caplog.at_level(logging.WARNING, logger="shared.csv_utils"):
        assert csv_utils.count_csv_records(path) is None

    assert "Could not count records" in caplog.text


def test_load_alert_log_logs_unreadable_file(tmp_path, caplog, monkeypatch):
    path = _write_malformed(tmp_path / "telegram_alert_log.csv")
    monkeypatch.setattr(telegram_alerts, "ALERT_LOG_PATH", path)

    with caplog.at_level(logging.WARNING, logger="shared.telegram_alerts"):
        df = telegram_alerts._load_alert_log()

    assert list(df.columns) == list(telegram_alerts.ALERT_LOG_COLUMNS)
    assert "duplicate alerts may be re-sent" in caplog.text


def test_scraper_health_load_csv_logs_unreadable_file(tmp_path, caplog):
    path = _write_malformed(tmp_path / "health.csv")

    with caplog.at_level(logging.WARNING, logger="shared.scraper_health"):
        df = scraper_health._load_csv(path)

    assert df.empty
    assert "could not read" in caplog.text


def test_load_state_table_logs_unreadable_state_file(tmp_path, caplog, monkeypatch):
    path = _write_malformed(tmp_path / "vehicle_state.csv")
    monkeypatch.setattr(update_master, "STATE_FILE", path)

    with caplog.at_level(logging.ERROR, logger="scripts.update_master"):
        state_df = update_master._load_state_table()

    assert isinstance(state_df, pd.DataFrame)
    assert "Unreadable listing state" in caplog.text


def test_update_master_propagates_restricted_build_failure(tmp_path, monkeypatch):
    def _tmp_dataset_path(name: str) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    for attribute in (
        "SOLD_FILE",
        "REFERRED_FILE",
        "ACTIVE_FILE",
        "STATIC_FILE",
        "STATE_FILE",
        "SOLD_DISCARD_LOG",
        "NORMALIZED_FILE",
    ):
        monkeypatch.setattr(update_master, attribute, _tmp_dataset_path(attribute.lower() + ".csv"))
    monkeypatch.setattr(update_master, "dataset_path", _tmp_dataset_path)
    monkeypatch.setattr(update_master, "_load_dataframe", lambda *_a, **_k: pd.DataFrame())
    monkeypatch.setattr(update_master, "append_pipeline_exclusions", lambda *_a, **_k: None)
    monkeypatch.setattr(
        update_master,
        "_load_state_table",
        lambda: update_master.ensure_state_schema(
            pd.DataFrame([{"url": "https://example.com/lot/1", "state": "active"}])
        ),
    )

    def _boom() -> None:
        raise ValueError("restricted build exploded")

    monkeypatch.setattr(update_master, "build_restricted_datasets", _boom)

    with pytest.raises(RuntimeError, match="Restricted dataset build failed"):
        update_master.update_master_database()
