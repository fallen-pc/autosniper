"""Regression coverage for Grays curve-worklist identity normalization."""

import pandas as pd

from scripts.grays_curve_target_worklist import (
    _clean,
    _key,
    _looks_previously_assessed,
)


def test_clean_normalizes_case_and_no_reserve_marker():
    assert _clean(" Sedan ") == "sedan"
    assert _clean("SX FD ** NO RESERVE **") == "sx fd"


def test_key_normalizes_compact_alphanumeric_badges():
    assert _key("Volkswagen Tiguan 147TSI 5N") == _key(
        "Volkswagen Tiguan 147 TSI 5 N"
    )
    assert _key("Subaru XV 2.0i G4X") == _key("Subaru XV 2 0 i G 4 X")


def test_compact_rejection_badge_marks_lane_previously_assessed():
    row = pd.Series(
        {
            "make": "volkswagen",
            "model": "tiguan",
            "variant": "147 tsi 5n",
            "body_type": "wagon",
            "fuel_type": "petrol",
            "transmission": "automatic",
        }
    )
    signatures = {_key("Volkswagen Tiguan 147TSI 5N automatic petrol SUV")}
    assert _looks_previously_assessed(row, signatures)
