from __future__ import annotations

import pandas as pd
import pytest

from shared import ops_utils
from shared.canonical_tagging import UNCLASSIFIED
from shared.ops_utils import (
    CurveMeta,
    apply_global_filters,
    build_issue_index,
    confidence_bucket,
    explode_issues,
    format_issue_label,
    has_curve,
    issue_hint,
    parse_currency,
    parse_percent,
    parse_time_remaining_hours,
    time_bucket,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), (float("nan"), True), ("", True), ("   ", True), ("nan", True), ("None", True), ("VIC", False), (0, False)],
)
def test_is_blank(value, expected) -> None:
    assert ops_utils._is_blank(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (float("nan"), None), (5, 5.0), ("1,250", 1250.0), ("", None), ("abc", None)],
)
def test_to_float(value, expected) -> None:
    assert ops_utils._to_float(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (float("nan"), None), (12.5, 12.5), ("12.5%", 12.5), (" ", None), ("high", None)],
)
def test_parse_percent(value, expected) -> None:
    assert parse_percent(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), (float("nan"), None), (1200, 1200.0), (1200.5, 1200.5), ("", None), ("  ", None)],
)
def test_parse_currency_numeric_inputs(value, expected) -> None:
    assert parse_currency(value) == expected


def test_parse_currency_parses_formatted_strings() -> None:
    assert parse_currency("$1,200") == 1200.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (float("nan"), None),
        ("", None),
        ("Sold", None),
        ("auction ended", None),
        ("closed", None),
        ("2d 3h 30m", 51.5),
        ("3h", 3.0),
        ("45m", 0.75),
        ("01:30", 1.5),
        ("0h", None),
    ],
)
def test_parse_time_remaining_hours(value, expected) -> None:
    assert parse_time_remaining_hours(value) == expected


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(None, "Unknown"), (1.0, "<24h"), (23.9, "<24h"), (24.0, "1-2d"), (47.9, "1-2d"), (48.0, "2-3d"), (72.0, "3+d")],
)
def test_time_bucket(hours, expected) -> None:
    assert time_bucket(hours) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("bad", "Unknown"), (None, "Unknown"), (0.9, "High"), (0.75, "High"), (0.6, "Medium"), (0.59, "Low")],
)
def test_confidence_bucket(value, expected) -> None:
    assert confidence_bucket(value) == expected


def test_issue_label_and_hint_fall_back_to_code() -> None:
    assert format_issue_label("NO_URL") == "Missing URL"
    assert issue_hint("NO_URL") == "Listing has no URL."
    assert format_issue_label("MYSTERY") == "MYSTERY"
    assert issue_hint("MYSTERY") == ""


def test_has_curve() -> None:
    meta = {"toyota_hilux": CurveMeta(canonical_tag="toyota_hilux", last_updated=None, anchor_years=[2018])}

    assert has_curve("toyota_hilux", meta) is True
    assert has_curve("ford_ranger", meta) is False
    assert has_curve("", meta) is False


def test_build_issue_index_empty_input() -> None:
    result = build_issue_index(pd.DataFrame())

    assert result.empty
    assert list(result.columns) == ["url", "severity", "issue_codes", "issue_count"]


def test_build_issue_index_flags_expected_codes() -> None:
    static_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/clean",
                "year": 2018,
                "make": "Toyota",
                "model": "Hilux",
                "variant": "SR5",
                "vin": "JT1234567890",
                "odometer_reading": "120000",
                "canonical_tag": "toyota_hilux",
                "canonical_reason": "exact match",
                "general_condition": "minor scratches",
            },
            {
                "url": "https://example.com/messy",
                "year": "",
                "make": "",
                "model": "",
                "variant": "",
                "vin": "SHORT",
                "odometer_reading": "0",
                "canonical_tag": UNCLASSIFIED,
                "canonical_reason": "ambiguous variant",
                "general_condition": "",
            },
        ]
    )
    active_df = pd.DataFrame([{"url": "https://example.com/messy", "status": "Sold"}])
    valuations_df = pd.DataFrame([{"url": "https://example.com/messy", "confidence": 0.4}])
    curve_meta = {"toyota_hilux": CurveMeta(canonical_tag="toyota_hilux", last_updated=None, anchor_years=[2018])}

    index = build_issue_index(static_df, active_df, valuations_df, curve_meta).set_index("url")

    assert index.loc["https://example.com/clean", "issue_count"] == 0
    assert index.loc["https://example.com/clean", "severity"] == "green"

    messy = index.loc["https://example.com/messy"]
    assert set(messy["issue_codes"]) == {
        "BAD_PARSE",
        "MISSING_VARIANT",
        "MISSING_VIN",
        "MISSING_ODOM",
        "NO_TAG",
        "TAG_AMBIGUOUS",
        "COND_NOTES_EMPTY",
        "NOT_ACTIVE",
        "LOW_CONFIDENCE",
    }
    assert messy["severity"] == "red"
    assert messy["issue_summary"].startswith("BAD_PARSE")


def test_build_issue_index_flags_missing_curve_for_tagged_listing() -> None:
    static_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/a",
                "year": 2018,
                "make": "Toyota",
                "model": "Hilux",
                "variant": "SR5",
                "vin": "JT1234567890",
                "odometer_reading": "120000",
                "canonical_tag": "toyota_hilux",
                "canonical_reason": "exact match",
                "general_condition": "clean",
            }
        ]
    )

    index = build_issue_index(static_df, curve_meta={})

    assert index.loc[0, "issue_codes"] == ["NO_CURVE"]
    assert index.loc[0, "severity"] == "yellow"


def test_explode_issues() -> None:
    assert explode_issues(pd.DataFrame()).empty

    issue_df = pd.DataFrame(
        [
            {"url": "a", "severity": "red", "issue_codes": ["NO_TAG", "MISSING_VIN"], "issue_count": 2},
            {"url": "b", "severity": "green", "issue_codes": [], "issue_count": 0},
        ]
    )

    exploded = explode_issues(issue_df)

    assert list(exploded["issue_code"]) == ["NO_TAG", "MISSING_VIN"]
    assert list(exploded["url"]) == ["a", "a"]


def test_apply_global_filters_narrows_rows() -> None:
    df = pd.DataFrame(
        [
            {"make": "Toyota", "model": "Hilux", "status": "Active", "verdict": "BUY",
             "confidence_bucket": "High", "time_bucket": "<24h", "has_curve": True},
            {"make": "Ford", "model": "Ranger", "status": "Sold", "verdict": "PASS",
             "confidence_bucket": "Low", "time_bucket": "3+d", "has_curve": False},
        ]
    )

    assert len(apply_global_filters(df)) == 2
    assert list(apply_global_filters(df, make_filter=["Toyota"])["model"]) == ["Hilux"]
    assert list(apply_global_filters(df, model_filter=["Ranger"])["make"]) == ["Ford"]
    assert list(apply_global_filters(df, status_filter=["Active"])["make"]) == ["Toyota"]
    assert list(apply_global_filters(df, verdict_filter=["PASS"])["make"]) == ["Ford"]
    assert list(apply_global_filters(df, confidence_filter=["High"])["make"]) == ["Toyota"]
    assert list(apply_global_filters(df, time_bucket_filter=["3+d"])["make"]) == ["Ford"]
    assert list(apply_global_filters(df, has_curve_filter="Yes")["make"]) == ["Toyota"]
    assert list(apply_global_filters(df, has_curve_filter="No")["make"]) == ["Ford"]


def test_append_helpers_write_quality_csvs(monkeypatch, tmp_path) -> None:
    notes = tmp_path / "quality" / "listing_notes.csv"
    flags = tmp_path / "quality" / "listing_flags.csv"
    queue = tmp_path / "quality" / "curve_backlog.csv"
    monkeypatch.setattr(ops_utils, "NOTES_FILE", notes)
    monkeypatch.setattr(ops_utils, "FLAGS_FILE", flags)
    monkeypatch.setattr(ops_utils, "CURVE_QUEUE_FILE", queue)

    ops_utils.append_note("https://example.com/a", "check odometer", author="ops")
    ops_utils.append_note("https://example.com/b", "second note")
    ops_utils.append_flag("https://example.com/a", "REVIEW", reason="odo mismatch")
    ops_utils.append_curve_queue("https://example.com/a", "toyota_hilux")

    notes_df = pd.read_csv(notes)
    assert list(notes_df["url"]) == ["https://example.com/a", "https://example.com/b"]
    assert notes_df.loc[0, "author"] == "ops"
    assert pd.isna(notes_df.loc[1, "author"])

    assert pd.read_csv(flags).loc[0, "reason"] == "odo mismatch"
    assert pd.read_csv(queue).loc[0, "canonical_tag"] == "toyota_hilux"

    assert list(ops_utils.load_notes_df()["url"]) == ["https://example.com/a", "https://example.com/b"]
    assert not ops_utils.load_flags_df().empty
    assert not ops_utils.load_curve_queue_df().empty


def test_spec_helpers_are_stubs() -> None:
    assert ops_utils.load_spec_data() == {}
    assert ops_utils.list_missing_curve_anchors({}, pd.DataFrame()).empty
