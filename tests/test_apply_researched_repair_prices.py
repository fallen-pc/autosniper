from __future__ import annotations

import pandas as pd

from scripts.apply_researched_repair_prices import RESEARCHED_ROWS
from shared.repair_pricing_schedule import PRICING_COLUMNS, validate_pricing_schedule


def test_every_researched_row_passes_schedule_validation() -> None:
    # The schedule validator rejects rows with no evidence_source ("do not invent
    # class multipliers"). This is the regression test for that: if a future edit
    # drops a citation or breaks the low<=default<=high ordering, this fails loudly
    # instead of silently corrupting money-logic data on save.
    df = pd.DataFrame(RESEARCHED_ROWS, columns=PRICING_COLUMNS)

    assert validate_pricing_schedule(df) == []


def test_every_researched_row_has_a_real_url_cited() -> None:
    for row in RESEARCHED_ROWS:
        assert "https://" in row["notes"], row["canonical_defect"]


def test_every_researched_row_is_marked_low_confidence_not_a_firm_quote() -> None:
    # These are published price-guide figures, not a supplier quote for this vehicle -
    # must never be indistinguishable from a real "repair_quote" row in the schedule.
    for row in RESEARCHED_ROWS:
        assert row["confidence"] == "low"
        assert row["pricing_method"] == "internal_default"


def test_no_two_researched_rows_target_the_same_cell() -> None:
    keys = [(row["canonical_defect"], row["vehicle_class"]) for row in RESEARCHED_ROWS]
    assert len(keys) == len(set(keys))
