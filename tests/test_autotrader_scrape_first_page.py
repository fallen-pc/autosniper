from __future__ import annotations

import math

import pandas as pd

from autotrader_isolated.scrape_first_page import _to_int_or_blank


def test_to_int_or_blank_handles_missing_numeric_values() -> None:
    assert _to_int_or_blank(None) == ""
    assert _to_int_or_blank(float("nan")) == ""
    assert _to_int_or_blank(pd.NA) == ""
    assert _to_int_or_blank(math.nan) == ""


def test_to_int_or_blank_preserves_numeric_strings() -> None:
    assert _to_int_or_blank("$12,345") == 12345
    assert _to_int_or_blank(12345.0) == 12345
