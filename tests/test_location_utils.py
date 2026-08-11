from __future__ import annotations

import pytest

from shared.location_utils import extract_state


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("Laverton North VIC", "VIC"),
        ("altona qld 3018", "QLD"),
        ("Sydney, NSW", "NSW"),
        ("Adelaide, south australia", "SOUTH AUSTRALIA"),
        ("Yard 3, Brisbane", "BRISBANE"),
        ("Melbourne", "MELBOURNE"),
        (12345, "12345"),
    ],
)
def test_extract_state(value, expected) -> None:
    assert extract_state(value) == expected


def test_extract_state_prefers_first_matching_abbreviation_in_declaration_order() -> None:
    # STATE_ABBREVIATIONS is scanned in order, so ACT wins over VIC here.
    assert extract_state("VIC ACT depot") == "ACT"
