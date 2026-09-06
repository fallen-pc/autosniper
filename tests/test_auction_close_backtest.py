from __future__ import annotations

import pandas as pd

from scripts.backtest_auction_close_prices import (
    CATEGORICAL_FEATURES,
    FORBIDDEN_FEATURES,
    LIVE_FEATURES,
    PRE_AUCTION_FEATURES,
    add_as_of_comps,
    apply_live_bid_floor,
    load_verified_sales,
    _parse_rolling_cutoffs,
    select_as_of_snapshots,
    train_and_predict,
)


def test_load_verified_sales_requires_state_evidence_and_matching_archive_price(tmp_path) -> None:
    state_path = tmp_path / "state.csv"
    sold_path = tmp_path / "sold.csv"
    pd.DataFrame(
        [
            {"url": "a", "state": "sold", "final_sale_price": "$1,000", "sale_price_source": "sold_for_heading"},
            {"url": "b", "state": "sold", "final_sale_price": "$2,000", "sale_price_source": ""},
            {"url": "c", "state": "sold", "final_sale_price": "$3,000", "sale_price_source": "sold_for_heading"},
        ]
    ).to_csv(state_path, index=False)
    pd.DataFrame(
        [
            {"url": "a", "price": "$1,000", "date_sold": "2026-04-01", "make": "Toyota", "model": "Yaris"},
            {"url": "b", "price": "$2,000", "date_sold": "2026-04-01", "make": "Toyota", "model": "Yaris"},
            {"url": "c", "price": "$3,100", "date_sold": "2026-04-01", "make": "Toyota", "model": "Yaris"},
        ]
    ).to_csv(sold_path, index=False)

    loaded = load_verified_sales(state_path, sold_path)

    assert loaded["url"].tolist() == ["a"]
    assert loaded["target_price"].tolist() == [1000.0]


def test_select_as_of_snapshots_uses_latest_eligible_and_rejects_post_sale() -> None:
    sales = pd.DataFrame({"url": ["a"], "sale_date": pd.to_datetime(["2026-04-10"], utc=True)})
    snapshots = pd.DataFrame(
        {
            "url": ["a", "a", "a"],
            "snapshot_ts": pd.to_datetime(
                ["2026-04-09T08:00:00Z", "2026-04-10T08:00:00Z", "2026-04-11T01:00:00Z"], utc=True
            ),
            "price_numeric": [1000, 1200, 1500],
            "bids_numeric": [1, 2, 3],
            "time_remaining_hours": [30, 26, 100],
            "auction_site": ["Grays", "Grays", "Grays"],
        }
    )

    selected = select_as_of_snapshots(sales, snapshots, horizon_hours=24)

    assert len(selected) == 1
    assert selected.iloc[0]["current_bid"] == 1200
    assert selected.iloc[0]["prediction_ts"] == pd.Timestamp("2026-04-10T08:00:00Z")


def test_add_as_of_comps_excludes_sale_day_and_future_sales() -> None:
    rows = pd.DataFrame(
        {
            "url": ["target"],
            "comp_key": ["tag:toyota_yaris"],
            "prediction_ts": pd.to_datetime(["2026-04-10T13:00:00Z"], utc=True),
        }
    )
    comps = pd.DataFrame(
        {
            "url": ["old", "same_day", "future"],
            "comp_key": ["tag:toyota_yaris"] * 3,
            "comp_price": [1000.0, 2000.0, 3000.0],
            "comp_sale_date": pd.to_datetime(["2026-04-09", "2026-04-10", "2026-04-11"], utc=True),
        }
    )

    enriched = add_as_of_comps(rows, comps)

    assert enriched.iloc[0]["comps_count"] == 1
    assert enriched.iloc[0]["comps_p50"] == 1000.0
    assert enriched.iloc[0]["latest_comp_sale_date"] == pd.Timestamp("2026-04-09T00:00:00Z")


def test_model_feature_lists_do_not_contain_outcome_or_timestamp_fields() -> None:
    assert not FORBIDDEN_FEATURES.intersection(PRE_AUCTION_FEATURES)
    assert not FORBIDDEN_FEATURES.intersection(LIVE_FEATURES)
    assert set(PRE_AUCTION_FEATURES).intersection(CATEGORICAL_FEATURES) == {
        "canonical_tag", "make", "model", "variant", "body_type", "transmission", "fuel_type", "location"
    }


def test_live_model_prediction_is_never_lower_than_known_current_bid() -> None:
    floored = apply_live_bid_floor(
        predictions=pd.Series([900.0, 1500.0, 1000.0]).to_numpy(),
        current_bids=pd.Series([1000.0, 1200.0, None]),
    )

    assert floored.tolist() == [1000.0, 1500.0, 1000.0]


def test_rolling_cutoffs_are_sorted_calendar_dates() -> None:
    cutoffs = _parse_rolling_cutoffs("2026-05-01,2026-06-01")

    assert cutoffs == [pd.Timestamp("2026-05-01", tz="UTC"), pd.Timestamp("2026-06-01", tz="UTC")]


def test_rolling_window_training_excludes_validation_period() -> None:
    rows = pd.DataFrame(
        {
            "prediction_ts": pd.date_range("2026-04-01", periods=45, freq="D", tz="UTC"),
            "target_price": list(range(1000, 5500, 100)),
            "comps_p50": list(range(950, 5450, 100)),
            "comps_count": [3] * 45,
        }
    )

    valid, info = train_and_predict(
        rows,
        feature_names=["comps_p50", "comps_count"],
        holdout_days=7,
        iterations=2,
        validation_start=pd.Timestamp("2026-05-01", tz="UTC"),
        validation_end=pd.Timestamp("2026-05-11", tz="UTC"),
    )

    assert info["rows_train"] == 30
    assert info["rows_valid"] == 10
    assert valid["prediction_ts"].min() == pd.Timestamp("2026-05-01", tz="UTC")
    assert valid["prediction_ts"].max() == pd.Timestamp("2026-05-10", tz="UTC")
