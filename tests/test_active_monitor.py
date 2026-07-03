from __future__ import annotations

from pathlib import Path

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
                "year": "2014",
                "make": "Toyota",
                "model": "Kluger",
                "variant": "KX-S GSU40R",
                "location": "Melbourne VIC",
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
    assert row["verdict"] == "Not Covered"
    assert row["action_label"] == "Review"
    assert row["bid_status"] == "Not covered"
    assert row["hard_max_safety"] == "No coverage"
    assert row["analysis_context"] == "active"
    assert row["no_edge"] is True
    assert row["year"] == "2014"
    assert row["make"] == "Toyota"
    assert row["model"] == "Kluger"
    assert row["variant"] == "KX-S GSU40R"
    assert row["location"] == "Melbourne VIC"
    assert row["current_bid"] == "$5,000"
    assert row["current_bid_numeric"] == 5000.0
    assert row["valuation_input_hash"]
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


def test_revalue_active_listings_marks_missing_out_of_range_rows(monkeypatch) -> None:
    target_url = "https://example.com/lot/high-km-kluger"
    all_active_df = pd.DataFrame(
        [
            {
                "url": target_url,
                "canonical_tag": "toyota_kluger_kx-s_petrol_auto_suv_gsu40r",
                "canonical_reason": "[OK]",
                "year": "2008",
                "make": "Toyota",
                "model": "Kluger",
                "variant": "KX-S GSU40R",
                "location": "Sydney NSW",
                "price": "$309",
                "bids": "4",
                "time_remaining_or_date_sold": "5d 2h",
            }
        ]
    )
    covered_active_df = pd.DataFrame(columns=all_active_df.columns)
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(active_monitor, "_prepare_all_active_rows", lambda: all_active_df.copy())
    monkeypatch.setattr(
        active_monitor,
        "_prepare_active_scope",
        lambda: (covered_active_df.copy(), pd.DataFrame(), pd.DataFrame()),
    )
    monkeypatch.setattr(active_monitor, "_prune_inactive_cached_valuations", lambda df: 0)
    monkeypatch.setattr(
        active_monitor,
        "load_cached_results",
        lambda: pd.DataFrame(columns=active_monitor.REQUIRED_COLUMNS),
    )
    monkeypatch.setattr(active_monitor, "upsert_manual_result_row", lambda row: captured.append(dict(row)))

    summary = active_monitor.revalue_active_listings(stale_minutes=60)

    assert summary["evaluated"] == 1
    assert summary["dropped_coverage"] == 1
    assert captured[0]["url"] == target_url
    assert captured[0]["computed_verdict"] == "Not Covered"
    assert captured[0]["action_label"] == "Review"
    assert captured[0]["bid_status"] == "Not covered"
    assert captured[0]["analysis_context"] == "active"
    assert captured[0]["year"] == "2008"
    assert captured[0]["make"] == "Toyota"
    assert captured[0]["model"] == "Kluger"
    assert captured[0]["variant"] == "KX-S GSU40R"
    assert captured[0]["location"] == "Sydney NSW"
    assert captured[0]["valuation_input_hash"]


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


def test_prune_inactive_cached_valuations_removes_stale_active_rows(monkeypatch, tmp_path: Path) -> None:
    cache_path = tmp_path / "ai_listing_valuations.csv"
    cached = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/stale",
                "analysis_context": "active",
                "action_label": "Buy",
                "computed_verdict": "Conditional Flip",
            },
            {
                "url": "https://example.com/lot/current",
                "analysis_context": "active",
                "action_label": "Watch",
                "computed_verdict": "Conditional Flip",
            },
            {
                "url": "https://example.com/lot/old-static",
                "analysis_context": "static",
                "action_label": "Buy",
                "computed_verdict": "Conditional Flip",
            },
        ]
    )
    cached.to_csv(cache_path, index=False)

    monkeypatch.setattr(active_monitor, "AI_RESULTS_PATH", cache_path)
    monkeypatch.setattr(active_monitor, "load_cached_results", lambda: pd.read_csv(cache_path))

    count = active_monitor._prune_inactive_cached_valuations(
        pd.DataFrame({"url": ["https://example.com/lot/current"]})
    )

    assert count == 1
    result = pd.read_csv(cache_path)
    assert "https://example.com/lot/stale" not in set(result["url"])
    assert "https://example.com/lot/current" in set(result["url"])
    assert "https://example.com/lot/old-static" in set(result["url"])


def test_exclude_shortlist_ineligible_rows_drops_completed_wovr_and_no_price() -> None:
    df = pd.DataFrame(
        [
            {
                "url": "https://example.com/lot/good",
                "variant": "Ascent",
                "status": "Active",
                "price": "$5,000",
            },
            {
                "url": "https://example.com/lot/referred",
                "variant": "Ascent",
                "status": "Referred",
                "price": "$5,000",
            },
            {
                "url": "https://example.com/lot/wovr",
                "variant": "Maxx Sport (WOVR - repairable)",
                "status": "Active",
                "price": "$1,500",
            },
            {
                "url": "https://example.com/lot/no-price",
                "variant": "Ascent",
                "status": "Active",
                "price": None,
            },
        ]
    )

    result = active_monitor._exclude_shortlist_ineligible_rows(df)

    assert result["url"].tolist() == ["https://example.com/lot/good"]


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
