from __future__ import annotations

import pandas as pd

from shared import exclusions
from shared.schema import PIPELINE_EXCLUSION_SCHEMA


def _patch_dataset_path(monkeypatch, tmp_path):
    target = tmp_path / "scrapers" / "pipeline_exclusions.csv"
    monkeypatch.setattr(exclusions, "dataset_path", lambda name: tmp_path / "scrapers" / name)
    return target


def test_append_pipeline_exclusions_writes_schema_columns(monkeypatch, tmp_path) -> None:
    target = _patch_dataset_path(monkeypatch, tmp_path)

    exclusions.append_pipeline_exclusions(
        [{"url": "https://example.com/a", "reason_code": "NO_PRICE", "timestamp": "2026-01-01T00:00:00+00:00"}],
        stage="normalize",
        run_id="run-1",
    )

    df = pd.read_csv(target)
    assert list(df.columns) == PIPELINE_EXCLUSION_SCHEMA
    row = df.iloc[0]
    assert row["url"] == "https://example.com/a"
    assert row["reason_code"] == "NO_PRICE"
    assert row["stage"] == "normalize"
    assert row["run_id"] == "run-1"


def test_append_pipeline_exclusions_appends_without_repeating_header(monkeypatch, tmp_path) -> None:
    target = _patch_dataset_path(monkeypatch, tmp_path)

    exclusions.append_pipeline_exclusions([{"url": "https://example.com/a"}], stage="one")
    exclusions.append_pipeline_exclusions([{"url": "https://example.com/b"}], stage="two")

    df = pd.read_csv(target)
    assert list(df["url"]) == ["https://example.com/a", "https://example.com/b"]
    assert list(df["stage"]) == ["one", "two"]


def test_append_pipeline_exclusions_defaults_stage_and_timestamp(monkeypatch, tmp_path) -> None:
    target = _patch_dataset_path(monkeypatch, tmp_path)

    exclusions.append_pipeline_exclusions([{"url": "https://example.com/a"}], stage="   ")

    row = pd.read_csv(target).iloc[0]
    assert row["stage"] == "unspecified"
    assert str(row["timestamp"]).startswith("20")


def test_append_pipeline_exclusions_serializes_structured_details(monkeypatch, tmp_path) -> None:
    target = _patch_dataset_path(monkeypatch, tmp_path)

    exclusions.append_pipeline_exclusions(
        [
            {"url": "https://example.com/a", "details": {"price": None}},
            {"url": "https://example.com/b", "field_snapshot": ["odometer"]},
            {"url": "https://example.com/c", "field_snapshot_json": '{"vin": ""}'},
            {"url": "https://example.com/d"},
        ],
        stage="validate",
    )

    df = pd.read_csv(target).fillna("")
    assert df.loc[0, "details"] == '{"price": null}'
    assert df.loc[1, "details"] == '["odometer"]'
    assert df.loc[2, "details"] == '{"vin": ""}'
    assert df.loc[3, "details"] == ""


def test_append_pipeline_exclusions_skips_blank_urls_and_empty_input(monkeypatch, tmp_path) -> None:
    target = _patch_dataset_path(monkeypatch, tmp_path)

    exclusions.append_pipeline_exclusions([], stage="validate")
    assert not target.exists()

    exclusions.append_pipeline_exclusions([{"url": "  "}, {"reason_code": "NO_URL"}], stage="validate")
    assert not target.exists()
