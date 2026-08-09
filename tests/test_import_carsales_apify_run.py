from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.import_carsales_apify_run import merge_output, normalize_items


def test_normalize_items_flattens_carsales_apify_fields():
    items = [
        {
            "runId": "run1",
            "adId": "SSE-AD-1",
            "canonicalUrl": "https://example.test/car",
            "title": "2010 Holden Commodore Omega VE Auto MY10",
            "make": "Holden",
            "model": "Commodore",
            "year": 2010,
            "variant": "Omega VE Auto MY10",
            "price": 8500,
            "marketIndicator": "Fair price",
            "scrapedAt": "2026-06-19T03:23:13.687Z",
            "specs": {
                "bodyStyle": "Sedan",
                "transmission": "Automatic",
                "fuelType": "Petrol - Unleaded Ulp",
                "odometer": 137000,
                "badge": "omega",
                "all": {
                    "Series": "VE",
                    "Badge": "Omega",
                    "Model Year": "MY10",
                    "Engine": "6 cylinders, Petrol Aspirated, 3.0L",
                },
            },
            "seller": {"type": "Private"},
            "location": {"state": "VIC", "region": "Melbourne", "suburb": "Sunbury"},
            "meta": {"priceAssessment": "FAIR PRICE"},
        }
    ]

    normalized = normalize_items(items, run_id="run1", dataset_id="dataset1")

    assert len(normalized) == 1
    row = normalized.iloc[0]
    assert row["source"] == "carsales_apify"
    assert row["run_id"] == "run1"
    assert row["dataset_id"] == "dataset1"
    assert row["badge"] == "Omega"
    assert row["series"] == "VE"
    assert row["model_year"] == "MY10"
    assert row["price"] == 8500
    assert row["odometer"] == 137000
    assert row["seller_type"] == "Private"
    assert row["engine"] == "6 cylinders, Petrol Aspirated, 3.0L"


def test_merge_output_keeps_latest_duplicate_by_ad_and_url(tmp_path: Path):
    output_path = tmp_path / "carsales_apify_listings.csv"
    pd.DataFrame(
        [
            {
                "run_id": "old",
                "dataset_id": "old_dataset",
                "scraped_at": "2026-06-18T00:00:00Z",
                "source": "carsales_apify",
                "ad_id": "SSE-AD-1",
                "url": "https://example.test/car",
                "title": "Old",
                "make": "Holden",
                "model": "Commodore",
                "year": 2010,
                "badge": "Omega",
                "series": "VE",
                "model_year": "MY10",
                "variant": "Omega VE Auto MY10",
                "price": 8000,
                "odometer": 137000,
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "engine": "3.0L",
                "seller_type": "Private",
                "state": "VIC",
                "region": "Melbourne",
                "suburb": "Sunbury",
                "market_indicator": "",
                "price_assessment": "",
            }
        ]
    ).to_csv(output_path, index=False)
    imported = pd.DataFrame(
        [
            {
                "run_id": "new",
                "dataset_id": "new_dataset",
                "scraped_at": "2026-06-19T00:00:00Z",
                "source": "carsales_apify",
                "ad_id": "SSE-AD-1",
                "url": "https://example.test/car",
                "title": "New",
                "make": "Holden",
                "model": "Commodore",
                "year": 2010,
                "badge": "Omega",
                "series": "VE",
                "model_year": "MY10",
                "variant": "Omega VE Auto MY10",
                "price": 8500,
                "odometer": 137000,
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "engine": "3.0L",
                "seller_type": "Private",
                "state": "VIC",
                "region": "Melbourne",
                "suburb": "Sunbury",
                "market_indicator": "",
                "price_assessment": "",
            }
        ]
    )

    merged = merge_output(output_path, imported)

    assert len(merged) == 1
    assert merged.iloc[0]["run_id"] == "new"
    assert int(merged.iloc[0]["price"]) == 8500
