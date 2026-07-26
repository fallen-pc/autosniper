from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from scripts import update_master
from shared.validators import R, ValidatorConfig, validate_sold_cars_df, validate_sold_row


def _sold_row(date_sold: str) -> dict[str, object]:
    return {
        "url": "https://example.com/lot/1",
        "year": 2016,
        "make": "Toyota",
        "model": "Camry",
        "variant": "Altise",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "odometer_reading": 120000,
        "price": 6000,
        "bids": 12,
        "date_sold": date_sold,
    }


def test_validate_sold_cars_preserves_iso_date_order() -> None:
    cleaned, stats = validate_sold_cars_df(pd.DataFrame([_sold_row("2026-02-07")]))

    assert stats["rows_dropped"] == 0
    assert cleaned.iloc[0]["date_sold"] == "2026-02-07"


def test_validate_sold_cars_parses_named_australian_date() -> None:
    cleaned, stats = validate_sold_cars_df(
        pd.DataFrame([_sold_row("02 July 2026 20:00 AEST")])
    )

    assert stats["rows_dropped"] == 0
    assert cleaned.iloc[0]["date_sold"] == "2026-07-02"


def test_update_master_parse_date_preserves_iso_date_order() -> None:
    assert update_master._parse_date("2026-02-07") == "2026-02-07"
    assert update_master._parse_date("02 July 2026 20:00 AEST") == "2026-07-02"


def test_validate_sold_cars_rejects_date_more_than_one_day_ahead() -> None:
    future_date = (date.today() + timedelta(days=2)).isoformat()

    cleaned, stats = validate_sold_cars_df(pd.DataFrame([_sold_row(future_date)]))

    assert cleaned.empty
    assert stats["rows_dropped"] == 1


def test_validate_sold_row_reports_future_date_reason() -> None:
    future_date = (date.today() + timedelta(days=2)).isoformat()
    config = ValidatorConfig(make_whitelist={"TOYOTA"})

    valid, reason, _ = validate_sold_row(_sold_row(future_date), config)

    assert valid is False
    assert reason == R.FUTURE_DATE_SOLD
