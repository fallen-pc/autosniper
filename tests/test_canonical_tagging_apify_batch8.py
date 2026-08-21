"""Regression coverage for the exact Grays lane published in batch 8."""

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_apify_batch8_sp25_bl_sedan_matches_without_absorbing_adjacent_lanes():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Mazda",
        "model": "3",
        "variant": "SP25 BL",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2011",
        "price": "8500",
        "url": "https://example.test/mazda-3-sp25-bl-sedan-auto",
    }
    expected = "mazda_3_sp25_petrol_auto_sedan_bl"
    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected, "[OK]")
    for change in (
        {"body_type": "Hatchback"},
        {"transmission": "Manual"},
        {"fuel_type": "Diesel"},
        {"variant": "Maxx Sport BL"},
        {"variant": "SP25 BK", "year": "2008"},
    ):
        assert assign_canonical_tag({**row, **change}, require_price=True)[0] != expected
