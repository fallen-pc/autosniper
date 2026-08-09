from __future__ import annotations

import pandas as pd

from ops import outcome_tracking
from scripts.log_outcome import log_outcome


def _patch_sources(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(outcome_tracking, "SCORING_PATH", tmp_path / "scored_listings.csv")
    monkeypatch.setattr(outcome_tracking, "ENRICHED_PATH", tmp_path / "scored_listings_enriched.csv")
    monkeypatch.setattr(outcome_tracking, "WEEKLY_METRICS_PATH", tmp_path / "weekly.csv")
    monkeypatch.setattr(outcome_tracking, "TIER_METRICS_PATH", tmp_path / "tier.csv")
    monkeypatch.setattr(outcome_tracking, "VERDICTS_SOURCE", tmp_path / "missing_verdicts.csv")
    monkeypatch.setattr(
        outcome_tracking,
        "load_cached_results",
        lambda: pd.DataFrame(
            [
                {
                    "url": "https://example.com/lot/1",
                    "year": 2018,
                    "make": "Toyota",
                    "model": "Corolla",
                    "variant": "Ascent",
                    "analysis_timestamp": "2026-07-01T00:00:00Z",
                    "carsales_price_estimate": "$20,000 - $22,000",
                    "expected_auction_profit": "$2,000",
                    "expected_profit": "$2,500",
                    "score_out_of_10": 8.0,
                    "recommended_max_bid": "$14,000",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        outcome_tracking,
        "load_historical_sales",
        lambda: pd.DataFrame(
            [
                {
                    "url": "https://example.com/lot/1",
                    "year": 2018,
                    "make": "Toyota",
                    "model": "Corolla",
                    "variant": "Ascent",
                    "final_price_numeric": 13_000,
                    "date_sold": "2026-07-01",
                }
            ]
        ),
    )


def test_log_outcome_fills_actuals_and_computes_profit(monkeypatch, tmp_path) -> None:
    _patch_sources(monkeypatch, tmp_path)

    row = log_outcome(
        "https://example.com/lot/1",
        sale_price=19_000,
        fees=600,
        recond=400,
    )

    # actual_profit = 19000 - (13000 purchase + 600 fees + 400 recond)
    assert float(row["actual_profit"]) == 5_000.0
    assert bool(row["hit"]) is True  # predicted profitable, actually profitable

    metrics = pd.read_csv(tmp_path / "weekly.csv")
    assert len(metrics) == 1
    assert float(metrics["accuracy"].iloc[0]) == 1.0


def test_log_outcome_unknown_url_exits(monkeypatch, tmp_path) -> None:
    _patch_sources(monkeypatch, tmp_path)

    try:
        log_outcome("https://example.com/lot/none", sale_price=10_000)
    except SystemExit as exc:
        assert "not found" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected SystemExit for unknown url")
