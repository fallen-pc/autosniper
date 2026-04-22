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
