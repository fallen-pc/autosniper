from __future__ import annotations

import pandas as pd

from scripts.build_sold_cars_all_ledger import build_sold_cars_all_ledger, ledger_exclusions


def _sold_row(
    url: str,
    *,
    odometer: object = 120000,
    price: object = "$5,000",
    date_sold: object = "2025-07-01",
) -> dict[str, object]:
    return {
        "url": url,
        "year": 2012,
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Ascent",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "odometer_reading": odometer,
        "no_of_seats": 5,
        "vin": "JTDKB20U793512345",
        "rego_no": "",
        "rego_expiry": "",
        "no_of_cylinders": 4,
        "engine_capacity": 1.8,
        "exterior_colour": "White",
        "interior_colour": "Black",
        "key": "Yes",
        "spare_key": "No",
        "owners_manual": "Yes",
        "service_history": "Yes",
        "engine_turns_over": "Yes",
        "location": "VIC",
        "general_condition": "Dents or marks on body consistent with age and kilometres.",
        "bids": 12,
        "price": price,
        "date_sold": date_sold,
    }


def test_all_ledger_keeps_historical_missing_odometer_row() -> None:
    strict = pd.DataFrame([_sold_row("https://example.test/strict")])
    historical = pd.DataFrame(
        [
            _sold_row("https://example.test/strict"),
            _sold_row("https://example.test/missing-odo", odometer="Unknown (Unable to read)"),
        ]
    )

    ledger, report = build_sold_cars_all_ledger(strict_sold=strict, historical_sold=historical)

    missing = ledger[ledger["url"] == "https://example.test/missing-odo"].iloc[0]
    assert len(ledger) == 2
    assert missing["ledger_source"] == "historical_sold"
    assert bool(missing["strict_sold_ready"]) is False
    assert missing["strict_exclusion_reason"] == "missing_odometer"
    assert report.iloc[0]["ledger_only_not_strict_ready"] == 1


def test_all_ledger_marks_historical_valid_row_strict_ready() -> None:
    strict = pd.DataFrame([_sold_row("https://example.test/strict")])
    historical = pd.DataFrame(
        [
            _sold_row("https://example.test/strict"),
            _sold_row("https://example.test/valid-history", odometer=150000),
        ]
    )

    ledger, report = build_sold_cars_all_ledger(strict_sold=strict, historical_sold=historical)

    valid = ledger[ledger["url"] == "https://example.test/valid-history"].iloc[0]
    assert valid["ledger_source"] == "historical_sold"
    assert bool(valid["strict_sold_ready"]) is True
    assert valid["strict_exclusion_reason"] == ""
    assert report.iloc[0]["ledger_only_not_strict_ready"] == 0


def test_ledger_exclusions_returns_row_level_rejects() -> None:
    strict = pd.DataFrame([_sold_row("https://example.test/strict")])
    historical = pd.DataFrame(
        [
            _sold_row("https://example.test/strict"),
            _sold_row("https://example.test/no-date", date_sold=""),
        ]
    )

    ledger, _ = build_sold_cars_all_ledger(strict_sold=strict, historical_sold=historical)
    exclusions = ledger_exclusions(ledger)

    assert len(exclusions) == 1
    assert exclusions.iloc[0]["url"] == "https://example.test/no-date"
    assert exclusions.iloc[0]["strict_exclusion_reason"] == "[NO_DATE_SOLD]"
