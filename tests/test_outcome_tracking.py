from __future__ import annotations

import pandas as pd

from ops import outcome_tracking


def test_load_predicted_rows_handles_missing_verdict_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(outcome_tracking, "VERDICTS_SOURCE", tmp_path / "missing_verdicts.csv")
    monkeypatch.setattr(
        outcome_tracking,
        "load_cached_results",
        lambda: pd.DataFrame(
            [
                {
                    "url": "https://example.com/lot/1",
                    "year": 2020,
                    "make": "Toyota",
                    "model": "Corolla",
                    "variant": "Ascent",
                    "analysis_timestamp": "2026-04-18T00:00:00Z",
                    "carsales_price_estimate": "$20,000 - $22,000",
                    "expected_auction_profit": "$900",
                    "expected_profit": "$1,500",
                    "score_out_of_10": 8.5,
                    "recommended_max_bid": "$15,000",
                }
            ]
        ),
    )

    predicted = outcome_tracking._load_predicted_rows()

    assert predicted["url"].tolist() == ["https://example.com/lot/1"]
    assert predicted["predicted_verdict"].tolist() == ["Gold"]
    assert predicted["predicted_resale_price"].tolist() == [21000.0]
    assert predicted["predicted_profit"].tolist() == [900.0]


def test_metrics_ignore_purchase_history_without_logged_actuals(monkeypatch, tmp_path) -> None:
    scoring_path = tmp_path / "scored_listings.csv"
    enriched_path = tmp_path / "scored_listings_enriched.csv"
    weekly_path = tmp_path / "model_accuracy_weekly.csv"
    tier_path = tmp_path / "model_accuracy_by_tier.csv"
    monkeypatch.setattr(outcome_tracking, "SCORING_PATH", scoring_path)
    monkeypatch.setattr(outcome_tracking, "ENRICHED_PATH", enriched_path)
    monkeypatch.setattr(outcome_tracking, "WEEKLY_METRICS_PATH", weekly_path)
    monkeypatch.setattr(outcome_tracking, "TIER_METRICS_PATH", tier_path)
    monkeypatch.setattr(outcome_tracking, "VERDICTS_SOURCE", tmp_path / "missing_verdicts.csv")

    monkeypatch.setattr(
        outcome_tracking,
        "load_cached_results",
        lambda: pd.DataFrame(
            [
                {
                    "url": "https://example.com/purchased-only",
                    "year": 2020,
                    "make": "Toyota",
                    "model": "Corolla",
                    "variant": "Ascent",
                    "analysis_timestamp": "2026-07-01T00:00:00Z",
                    "carsales_price_estimate": "$20,000",
                    "expected_auction_profit": "$1,000",
                    "score_out_of_10": 8.0,
                    "recommended_max_bid": "$15,000",
                },
                {
                    "url": "https://example.com/logged-outcome",
                    "year": 2021,
                    "make": "Mazda",
                    "model": "3",
                    "variant": "Touring",
                    "analysis_timestamp": "2026-07-01T00:00:00Z",
                    "carsales_price_estimate": "$25,000",
                    "expected_auction_profit": "$2,000",
                    "score_out_of_10": 8.5,
                    "recommended_max_bid": "$18,000",
                },
            ]
        ),
    )
    monkeypatch.setattr(
        outcome_tracking,
        "load_historical_sales",
        lambda: pd.DataFrame(
            [
                {
                    "url": "https://example.com/purchased-only",
                    "year": 2020,
                    "make": "Toyota",
                    "model": "Corolla",
                    "variant": "Ascent",
                    "final_price_numeric": 15000,
                    "date_sold": "2026-07-02",
                },
                {
                    "url": "https://example.com/logged-outcome",
                    "year": 2021,
                    "make": "Mazda",
                    "model": "3",
                    "variant": "Touring",
                    "final_price_numeric": 18000,
                    "date_sold": "2026-07-02",
                },
            ]
        ),
    )
    pd.DataFrame(
        [
            {
                "url": "https://example.com/purchased-only",
                "settled_date": "2026-07-02",
            },
            {
                "url": "https://example.com/logged-outcome",
                "actual_sale_price": 27000,
                "actual_fees_total": 400,
                "reconditioning_cost": 600,
                "settled_date": "2026-07-09",
            },
        ]
    ).to_csv(scoring_path, index=False)

    result = outcome_tracking.compute_outcome_metrics()

    scored = result.scored.set_index("url")
    purchase_only = scored.loc["https://example.com/purchased-only"]
    logged = scored.loc["https://example.com/logged-outcome"]

    assert purchase_only["purchase_price"] == 15000
    assert purchase_only["purchase_date"] == "2026-07-02"
    assert pd.isna(purchase_only["settled_date"])
    assert pd.isna(purchase_only["hit"])

    assert logged["actual_profit"] == 8000
    assert logged["hit"] is True
    assert outcome_tracking.logged_outcome_mask(result.scored).sum() == 1
    assert len(result.weekly_metrics) == 1
    assert result.weekly_metrics["accuracy"].tolist() == [1.0]
