from __future__ import annotations

import pandas as pd

import scripts.active_monitor as active_monitor


def test_mark_dropped_coverage_urls_writes_not_covered(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(active_monitor, "upsert_manual_result_row", lambda row: captured.append(dict(row)))

    all_active_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "canonical_tag": "demo_tag",
                "canonical_reason": "[matched]",
                "price": "$5,000",
                "bids": "3",
                "time_remaining_or_date_sold": "2h 15m",
            }
        ]
    )
    covered_active_df = pd.DataFrame(columns=all_active_df.columns)

    count = active_monitor._mark_dropped_coverage_urls(
        all_active_df,
        covered_active_df,
        {"https://example.com/lot/1"},
    )

    assert count == 1
    assert len(captured) == 1
    row = captured[0]
    assert row["computed_verdict"] == "Not Covered"
    assert row["analysis_context"] == "active"
    assert row["no_edge"] is True
    assert "no longer curve-covered" in str(row["edge_note"]).lower()


def test_mark_dropped_coverage_urls_ignores_non_targets(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(active_monitor, "upsert_manual_result_row", lambda row: captured.append(dict(row)))

    all_active_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "canonical_tag": "demo_tag",
                "canonical_reason": "[matched]",
            }
        ]
    )
    covered_active_df = pd.DataFrame(columns=all_active_df.columns)

    count = active_monitor._mark_dropped_coverage_urls(
        all_active_df,
        covered_active_df,
        {"https://example.com/lot/other"},
    )

    assert count == 0
    assert captured == []


def test_load_ai_analysis_active_df_uses_prepared_scope(monkeypatch) -> None:
    expected_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/ai-viable",
                "curve_coverage": True,
            }
        ]
    )

    monkeypatch.setattr(
        active_monitor,
        "_prepare_active_scope",
        lambda: (expected_df, pd.DataFrame(), pd.DataFrame()),
    )

    result = active_monitor.load_ai_analysis_active_df()

    assert result is expected_df


def test_prepare_active_scope_keeps_sold_rows_after_curve_tag_resolution(monkeypatch) -> None:
    detailed_tag = "hyundai_i30_active_petrol_auto_hatch_gd"
    curve_tag = "hyundai_i30_gd_hatch_auto_petrol"
    url = "https://example.com/lot/i30"

    active_restricted = pd.DataFrame(
        [
            {
                "url": url,
                "year": 2014,
                "odometer_reading": 125_000,
                "price": "$2,000",
                "status": "Active",
            }
        ]
    )
    live_active = pd.DataFrame(
        [
            {
                "url": url,
                "price": "$2,100",
                "status": "Active",
                "location": "vic",
            }
        ]
    )
    group_map = pd.DataFrame(
        [
            {
                "url": url,
                "source": "active",
                "canonical_tag": detailed_tag,
                "reason_code": "[OK]",
            },
            {
                "url": "https://example.com/lot/sold-i30",
                "source": "sold",
                "canonical_tag": detailed_tag,
                "reason_code": "[OK]",
            },
        ]
    )
    sold = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/sold-i30",
                "year": 2014,
                "odometer_reading": 130_000,
                "price": "$6,100",
            }
        ]
    )
    curves = pd.DataFrame(
        [
            {"canonical_tag": curve_tag, "anchor_year": 2014, "km_bucket": 100_000, "price_mid": 12_000},
            {"canonical_tag": curve_tag, "anchor_year": 2014, "km_bucket": 150_000, "price_mid": 11_000},
        ]
    )

    def fake_load_csv(path):
        path_text = str(path)
        if path_text.endswith("active_vehicle_details_restricted.csv"):
            return active_restricted.copy()
        if path_text.endswith("active_vehicle_details.csv"):
            return live_active.copy()
        if path_text.endswith("restricted_group_map.csv"):
            return group_map.copy()
        if path_text.endswith("sold_cars_restricted.csv"):
            return sold.copy()
        return pd.DataFrame()

    monkeypatch.setattr(active_monitor, "_load_csv", fake_load_csv)
    monkeypatch.setattr(active_monitor, "load_curves", lambda: curves.copy())

    active_df, sold_df, _ = active_monitor._prepare_active_scope()

    assert len(active_df) == 1
    assert len(sold_df) == 1
    assert sold_df.iloc[0]["curve_tag"] == curve_tag


def test_diff_price_changed_listing_urls_ignores_timer_changes() -> None:
    before_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "price": "$10,000",
                "time_remaining_or_date_sold": "2h 10m",
            }
        ]
    )
    after_df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/1",
                "price": "$10,000",
                "time_remaining_or_date_sold": "1h 10m",
            }
        ]
    )

    assert active_monitor.diff_price_changed_listing_urls(before_df, after_df) == set()


def test_diff_price_changed_listing_urls_detects_price_increase() -> None:
    before_df = pd.DataFrame([{"url": "https://example.com/lot/1", "price": "$10,000"}])
    after_df = pd.DataFrame([{"url": "https://example.com/lot/1", "price": "$10,500"}])

    assert active_monitor.diff_price_changed_listing_urls(before_df, after_df) == {
        "https://example.com/lot/1"
    }
