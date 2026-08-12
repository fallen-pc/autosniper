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


def test_normalize_items_accepts_actor_flat_schema():
    items = [
        {
            "runId": "run2",
            "networkId": "SSE-AD-2",
            "canonicalUrl": "https://example.test/outlander",
            "title": "2022 Mitsubishi Outlander ES ZM Auto 2WD MY23",
            "make": "mitsubishi",
            "model": "outlander",
            "year": "2022",
            "badge": "es",
            "spec": "ZM MY23 ES Wagon 5dr CVT 8sp 2WD 660kg 2.5i",
            "price": "19900",
            "odometer": "156358",
            "bodyStyle": "suv",
            "transmission": "automatic",
            "fuelType": "petrol - unleaded ulp",
            "sellerType": "private",
            "state": "nsw",
            "region": "central coast",
            "suburb": "summerland point",
            "engineSizeL": "2.5L",
            "specPairs": {
                "Model year": "MY23",
                "Engine": "4 cylinders, Petrol Aspirated, 2.5L",
            },
        }
    ]

    normalized = normalize_items(items, run_id="run2", dataset_id="dataset2")

    row = normalized.iloc[0]
    assert row["badge"] == "es"
    assert row["series"] == "ZM"
    assert row["model_year"] == "MY23"
    assert row["odometer"] == 156358
    assert row["body_type"] == "suv"
    assert row["transmission"] == "automatic"
    assert row["fuel_type"] == "petrol - unleaded ulp"
    assert row["seller_type"] == "private"
    assert row["state"] == "nsw"
    assert row["engine"] == "4 cylinders, Petrol Aspirated, 2.5L"


def test_normalize_items_accepts_abotapi_flat_schema():
    normalized = normalize_items(
        [
            {
                "listingId": "SSE-AD-PULSAR",
                "url": "https://example.test/pulsar",
                "title": "2015 Nissan Pulsar ST B17 Series 2 Auto",
                "make": "Nissan",
                "model": "Pulsar",
                "year": 2015,
                "variant": "ST B17 Series 2 Auto",
                "bodyType": "Sedan",
                "transmission": "Automatic",
                "engine": "4cyl 1.8L Petrol",
                "fuelType": "Petrol",
                "odometer": 59346,
                "price": 8721,
                "sellerType": "Private",
                "state": "NSW",
                "scrapedAt": "2026-07-27T08:21:20.264Z",
            }
        ],
        run_id="run-abotapi",
        dataset_id="dataset-abotapi",
    )

    row = normalized.iloc[0]
    assert row["ad_id"] == "SSE-AD-PULSAR"
    assert row["url"] == "https://example.test/pulsar"
    assert row["body_type"] == "Sedan"
    assert row["engine"] == "4cyl 1.8L Petrol"


def test_merge_output_does_not_collapse_rows_without_actor_identity(tmp_path: Path):
    imported = normalize_items(
        [
            {"title": "First", "make": "Nissan", "model": "Pulsar", "year": 2013},
            {"title": "Second", "make": "Nissan", "model": "Pulsar", "year": 2014},
        ]
    )

    merged = merge_output(tmp_path / "carsales.csv", imported)

    assert len(merged) == 2


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
