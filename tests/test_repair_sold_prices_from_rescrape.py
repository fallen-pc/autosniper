from __future__ import annotations

import pandas as pd

from scripts.repair_sold_prices_from_rescrape import build_repair_preview


def test_build_repair_preview_updates_mismatched_price_and_dynamic_fields() -> None:
    source = pd.DataFrame(
        [
            {
                "url": "https://example.com/a",
                "year": 2018,
                "make": "TOYOTA",
                "model": "Camry",
                "variant": "Ascent",
                "bids": 1,
                "price": 209,
                "date_sold": "2026-02-12",
                "price_numeric": 209,
                "price_text": "209",
                "bids_numeric": 1,
                "canonical_tag": "keep_me",
            }
        ]
    )
    rebuilt = pd.DataFrame(
        [
            {
                "url": "https://example.com/a",
                "year": 2018,
                "make": "TOYOTA",
                "model": "Camry",
                "variant": "Ascent",
                "bids": 119,
                "price": "$10,500",
                "date_sold": "17 February 2026",
            }
        ]
    )

    repaired, report = build_repair_preview(source, rebuilt)

    assert len(report) == 1
    assert report.iloc[0]["old_price"] == 209
    assert report.iloc[0]["new_price"] == "$10,500"
    assert repaired.iloc[0]["price"] == "$10,500"
    assert repaired.iloc[0]["date_sold"] == "17 February 2026"
    assert repaired.iloc[0]["bids"] == 119
    assert repaired.iloc[0]["price_numeric"] == 10500
    assert repaired.iloc[0]["price_text"] == "$10,500"
    assert repaired.iloc[0]["bids_numeric"] == 119
    assert repaired.iloc[0]["canonical_tag"] == "keep_me"


def test_build_repair_preview_leaves_matching_rows_unchanged() -> None:
    source = pd.DataFrame([{"url": "https://example.com/a", "price": 5000, "date_sold": "2026-01-01"}])
    rebuilt = pd.DataFrame([{"url": "https://example.com/a", "price": "$5,000", "date_sold": "01 January 2026"}])

    repaired, report = build_repair_preview(source, rebuilt)

    assert report.empty
    assert repaired.iloc[0]["date_sold"] == "2026-01-01"


def test_build_repair_preview_ignores_rebuilt_rows_without_price() -> None:
    source = pd.DataFrame([{"url": "https://example.com/a", "price": 5000, "date_sold": "2026-01-01"}])
    rebuilt = pd.DataFrame([{"url": "https://example.com/a", "price": "", "date_sold": "01 January 2026"}])

    repaired, report = build_repair_preview(source, rebuilt)

    assert report.empty
    assert repaired.iloc[0]["price"] == 5000
