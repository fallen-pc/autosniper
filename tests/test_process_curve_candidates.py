from __future__ import annotations

import sys

import pandas as pd
import pytest

from scripts.process_curve_candidates import (
    LEGACY_AI_CURVE_BUILD_DISABLED_MESSAGE,
    REQUIRED_KM_BUCKETS,
    build_autotrader_seed_url,
    derive_anchor_years,
    load_autotrader_market,
    main,
    update_autotrader_queue_status,
    validate_curve_response,
)


def _curve_rows(curve_tag: str, anchor_years: list[int], base_price: int) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for year_index, anchor_year in enumerate(anchor_years):
        year_offset = year_index * 1500
        for km_index, km_bucket in enumerate(REQUIRED_KM_BUCKETS):
            price_mid = base_price + year_offset - (km_index * 1200)
            rows.append(
                {
                    "canonical_tag": curve_tag,
                    "anchor_year": anchor_year,
                    "km_bucket": km_bucket,
                    "price_low": price_mid - 1200,
                    "price_mid": price_mid,
                    "price_high": price_mid + 1200,
                }
            )
    return rows


def test_derive_anchor_years_prefers_existing_curve_layout():
    assert derive_anchor_years(year_min=2014, year_max=2018, existing_anchor_years=[2015, 2017, 2019]) == [2015, 2017, 2019]


def test_derive_anchor_years_spreads_new_curve_years():
    assert derive_anchor_years(year_min=2013, year_max=2018) == [2013, 2016, 2018]
    assert derive_anchor_years(year_min=2010, year_max=2018) == [2010, 2013, 2015, 2018]


def test_build_autotrader_seed_url_uses_make_and_model():
    url = build_autotrader_seed_url("toyota_corolla_ascent_petrol_auto_sedan_zre172r", state="vic", city="melbourne")
    assert url == "https://www.autotrader.com.au/for-sale/used/toyota/corolla/vic/melbourne"


def test_legacy_ai_curve_build_cli_is_disabled(tmp_path, monkeypatch):
    queue_path = tmp_path / "curve_candidates.csv"
    pd.DataFrame(
        [
            {
                "curve_tag": "toyota_corolla_ascent_petrol_auto_hatch_zre152r",
                "recommended_action": "build_curve",
                "ready_for_curve": True,
                "year_min": 2009,
                "year_max": 2013,
            }
        ]
    ).to_csv(queue_path, index=False)

    monkeypatch.setattr(sys, "argv", ["process_curve_candidates.py", "--queue", str(queue_path)])

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert LEGACY_AI_CURVE_BUILD_DISABLED_MESSAGE in str(excinfo.value)


def test_validate_curve_response_accepts_valid_curve():
    curve_tag = "hyundai_i30_active_petrol_auto_hatch_gd"
    anchor_years = [2013, 2015, 2016]
    payload = {"rows": _curve_rows(curve_tag, anchor_years, 14000)}

    proposed, errors, shift_pct = validate_curve_response(
        curve_tag=curve_tag,
        payload=payload,
        anchor_years=anchor_years,
        existing_rows=pd.DataFrame(),
        max_mid_shift_pct=0.15,
    )

    assert proposed is not None
    assert errors == []
    assert shift_pct == 0.0
    assert len(proposed) == len(anchor_years) * len(REQUIRED_KM_BUCKETS)


def test_validate_curve_response_rejects_large_refresh_drift():
    curve_tag = "toyota_corolla_ascent_petrol_auto_sedan_zre152r"
    anchor_years = [2009, 2011, 2013]
    payload = {"rows": _curve_rows(curve_tag, anchor_years, 20000)}
    existing_rows = pd.DataFrame(_curve_rows(curve_tag, anchor_years, 12000))

    proposed, errors, shift_pct = validate_curve_response(
        curve_tag=curve_tag,
        payload=payload,
        anchor_years=anchor_years,
        existing_rows=existing_rows,
        max_mid_shift_pct=0.15,
    )

    assert proposed is None
    assert errors
    assert shift_pct > 0.15


def test_validate_curve_response_repairs_small_missing_grid_gap():
    curve_tag = "hyundai_i30_active_petrol_auto_hatch_gd"
    anchor_years = [2013, 2015, 2016]
    rows = _curve_rows(curve_tag, anchor_years, 14000)
    rows = [
        row
        for row in rows
        if not (row["anchor_year"] == 2015 and row["km_bucket"] == 200000)
    ]
    payload = {"rows": rows}

    proposed, errors, shift_pct = validate_curve_response(
        curve_tag=curve_tag,
        payload=payload,
        anchor_years=anchor_years,
        existing_rows=pd.DataFrame(),
        max_mid_shift_pct=0.15,
    )

    assert proposed is not None
    assert errors == []
    assert shift_pct == 0.0
    repaired = proposed[(proposed["anchor_year"] == 2015) & (proposed["km_bucket"] == 200000)]
    assert len(repaired) == 1


def test_update_autotrader_queue_status_marks_rows_completed(tmp_path):
    queue_path = tmp_path / "autotrader_scrape_queue.csv"
    pd.DataFrame(
        [
            {
                "timestamp": "2026-03-20T00:00:00Z",
                "curve_tag": "hyundai_i30_active_petrol_auto_hatch_gd",
                "seed_url": "https://www.autotrader.com.au/for-sale/used/hyundai/i30/vic/melbourne",
                "state": "vic",
                "city": "melbourne",
                "status": "queued",
                "curve_build_action": "refresh_curve",
                "curve_confidence": 1.0,
                "notes": "Valid JSON",
            }
        ]
    ).to_csv(queue_path, index=False)

    update_autotrader_queue_status(
        queue_path,
        seed_urls=["https://www.autotrader.com.au/for-sale/used/hyundai/i30/vic/melbourne"],
        status="completed",
        result_note="scrape ok",
    )

    updated = pd.read_csv(queue_path)
    row = updated.iloc[0]
    assert row["status"] == "completed"
    assert row["last_result"] == "scrape ok"
    assert isinstance(row["last_run_at"], str) and row["last_run_at"]
    assert isinstance(row["completed_at"], str) and row["completed_at"]


def test_load_autotrader_market_keeps_latest_live_row_per_url(tmp_path):
    source_path = tmp_path / "autotrader.csv"
    recent_sold = (pd.Timestamp.utcnow() - pd.Timedelta(days=10)).isoformat()
    stale_sold = (pd.Timestamp.utcnow() - pd.Timedelta(days=120)).isoformat()
    pd.DataFrame(
        [
            {
                "url": "car/1",
                "scrape_date": recent_sold,
                "status": None,
                "canonical_tag": "tag_a",
                "price": 15000,
                "last_price": 14500,
                "odometer": 100000,
                "year": 2016,
            },
            {
                "url": "car/1",
                "scrape_date": None,
                "status": "sold",
                "canonical_tag": "tag_a",
                "price": 14500,
                "last_price": 14500,
                "odometer": 100000,
                "year": 2016,
                "sold_date": recent_sold,
            },
            {
                "url": "car/2",
                "scrape_date": recent_sold,
                "status": None,
                "canonical_tag": "tag_b",
                "price": 18000,
                "odometer": 80000,
                "year": 2018,
            },
            {
                "url": "car/2",
                "scrape_date": (pd.Timestamp.utcnow() - pd.Timedelta(days=20)).isoformat(),
                "status": None,
                "canonical_tag": "tag_b",
                "price": 17500,
                "odometer": 81000,
                "year": 2018,
            },
            {
                "url": "car/3",
                "scrape_date": None,
                "status": "sold",
                "canonical_tag": "tag_c",
                "price": 12000,
                "odometer": 140000,
                "year": 2012,
                "sold_date": stale_sold,
            },
        ]
    ).to_csv(source_path, index=False)

    loaded = load_autotrader_market(source_path)

    loaded = loaded.sort_values("url").reset_index(drop=True)
    assert loaded["url"].tolist() == ["car/1", "car/2"]
    assert loaded["price_numeric"].tolist() == [15000, 18000]
    assert loaded["odometer_numeric"].tolist() == [100000, 80000]
    assert loaded["year_numeric"].tolist() == [2016, 2018]


def test_load_autotrader_market_builds_recent_snapshot_from_listing_state(tmp_path):
    source_path = tmp_path / "autotrader_recent_market_tagged.csv"
    state_path = tmp_path / "listing_state.csv"
    recent_active = (pd.Timestamp.utcnow() - pd.Timedelta(days=5)).isoformat()
    recent_sold = (pd.Timestamp.utcnow() - pd.Timedelta(days=12)).isoformat()
    stale_sold = (pd.Timestamp.utcnow() - pd.Timedelta(days=120)).isoformat()
    pd.DataFrame(
        [
            {
                "url": "car/1",
                "status": "active",
                "first_seen": recent_active,
                "last_seen": recent_active,
                "last_price": 15990,
                "last_price_date": recent_active,
                "sold_date": "",
                "year": 2010,
                "make": "Mazda",
                "model": "3",
                "variant": "Neo",
                "body_type": "Hatchback",
                "odometer": 191000,
                "transmission": "Automatic",
                "rego": "",
                "fuel_type": "Unleaded",
                "location": "VIC",
            },
            {
                "url": "car/2",
                "status": "sold",
                "first_seen": recent_active,
                "last_seen": recent_active,
                "last_price": 13990,
                "last_price_date": recent_active,
                "sold_date": recent_sold,
                "year": 2011,
                "make": "Mazda",
                "model": "3",
                "variant": "Neo",
                "body_type": "Hatchback",
                "odometer": 200000,
                "transmission": "Automatic",
                "rego": "",
                "fuel_type": "Unleaded",
                "location": "VIC",
            },
            {
                "url": "car/3",
                "status": "sold",
                "first_seen": stale_sold,
                "last_seen": stale_sold,
                "last_price": 11990,
                "last_price_date": stale_sold,
                "sold_date": stale_sold,
                "year": 2009,
                "make": "Mazda",
                "model": "3",
                "variant": "Neo",
                "body_type": "Hatchback",
                "odometer": 210000,
                "transmission": "Automatic",
                "rego": "",
                "fuel_type": "Unleaded",
                "location": "VIC",
            },
        ]
    ).to_csv(state_path, index=False)

    loaded = load_autotrader_market(source_path)

    assert source_path.exists()
    assert loaded["url"].tolist() == ["car/1", "car/2"]
    assert loaded["price_numeric"].tolist() == [15990, 13990]
    assert loaded["year_numeric"].tolist() == [2010, 2011]
