"""Regression coverage for Grays curve-worklist identity normalization."""

from scripts.grays_curve_target_worklist import _clean


def test_clean_normalizes_case_and_no_reserve_marker():
    assert _clean(" Sedan ") == "sedan"
    assert _clean("SX FD ** NO RESERVE **") == "sx fd"
