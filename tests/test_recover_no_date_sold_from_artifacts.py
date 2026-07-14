from __future__ import annotations

import pandas as pd

from scripts.recover_no_date_sold_from_artifacts import recover_no_date_sold


def _sold_row(url: str, *, date_sold: object = "2025-07-01") -> dict[str, object]:
    return {
        "url": url,
        "year": 2012,
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Ascent",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "odometer_reading": 120000,
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
        "price": "$5,000",
        "date_sold": date_sold,
    }


def test_recover_no_date_sold_promotes_validator_clean_row(tmp_path) -> None:
    source_path = tmp_path / "sold_cars.csv"
    source_path.write_text(
        "url,date_sold\nhttps://example.test/no-date,15 October 2025\n",
        encoding="utf-8",
    )
    strict = pd.DataFrame([_sold_row("https://example.test/strict")])
    ledger = pd.DataFrame(
        [
            {
                **_sold_row("https://example.test/strict"),
                "ledger_source": "current_strict_sold",
                "strict_sold_ready": True,
                "strict_exclusion_reason": "",
            },
            {
                **_sold_row("https://example.test/no-date", date_sold=""),
                "ledger_source": "historical_sold",
                "strict_sold_ready": False,
                "strict_exclusion_reason": "[NO_DATE_SOLD]",
            },
        ]
    )

    updated, report, unresolved = recover_no_date_sold(
        strict_sold=strict,
        ledger=ledger,
        source_paths=[source_path],
    )

    recovered = updated[updated["url"] == "https://example.test/no-date"].iloc[0]
    assert len(updated) == 2
    assert recovered["date_sold"] == "2025-10-15"
    assert bool(report.iloc[0]["promoted_to_strict"]) is True
    assert unresolved.empty
