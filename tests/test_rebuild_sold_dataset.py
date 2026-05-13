from __future__ import annotations

import pandas as pd

from scripts.rebuild_sold_dataset import has_verified_sold_date, select_rebuild_source_rows


def test_select_rebuild_source_rows_can_work_backwards_in_chunks() -> None:
    source = pd.DataFrame({"url": [f"https://example.com/{idx}" for idx in range(1, 6)]})

    selected = select_rebuild_source_rows(source, newest_first=True, offset=1, limit=2)

    assert selected["url"].tolist() == [
        "https://example.com/4",
        "https://example.com/3",
    ]


def test_select_rebuild_source_rows_defaults_to_existing_order() -> None:
    source = pd.DataFrame({"url": [f"https://example.com/{idx}" for idx in range(1, 6)]})

    selected = select_rebuild_source_rows(source, offset=1, limit=2)

    assert selected["url"].tolist() == [
        "https://example.com/2",
        "https://example.com/3",
    ]


def test_has_verified_sold_date_rejects_live_closing_time() -> None:
    assert has_verified_sold_date({"date_sold": "Closes: (06 May 20:00 AEST)"}) is False


def test_has_verified_sold_date_accepts_sold_date() -> None:
    assert has_verified_sold_date({"date_sold": "17 February 2026"}) is True
