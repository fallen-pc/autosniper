"""Regression coverage for the exact Grays lanes published in Batch 9."""

import pytest

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


@pytest.mark.parametrize(
    ("row", "expected", "adjacent"),
    [
        (
            {
                "make": "BMW", "model": "X5", "variant": "sDrive 25d F15",
                "body_type": "Wagon", "transmission": "Automatic",
                "fuel_type": "Diesel", "year": "2016", "price": "19000",
                "url": "https://example.test/bmw-x5-sdrive25d-f15",
            },
            "bmw_x5_sdrive25d_diesel_auto_wagon_f15",
            ({"variant": "xDrive 30d F15"}, {"variant": "sDrive25d"}, {"fuel_type": "Petrol"}),
        ),
        (
            {
                "make": "Nissan", "model": "Micra", "variant": "ST K13",
                "body_type": "Hatchback", "transmission": "Automatic",
                "fuel_type": "Petrol", "year": "2016", "price": "4500",
                "url": "https://example.test/nissan-micra-st-k13",
            },
            "nissan_micra_st_k13_petrol_auto_hatch",
            ({"variant": "ST-L K13"}, {"variant": "ST Petrol"}, {"transmission": "Manual"}, {"variant": "K12"}),
        ),
    ],
)
def test_batch9_exact_lanes_do_not_absorb_adjacent_variants(row, expected, adjacent):
    _load_curve_year_band.cache_clear()
    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected, "[OK]")
    for change in adjacent:
        assert assign_canonical_tag({**row, **change}, require_price=True)[0] != expected
