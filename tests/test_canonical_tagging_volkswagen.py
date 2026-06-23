from __future__ import annotations

import pytest

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


@pytest.mark.parametrize(
    ("variant", "fuel_type", "expected_tag"),
    [
        (
            "118TSI Comfortline VI Auto MY11",
            "Petrol - Premium ULP",
            "volkswagen_golf_comfortline_petrol_auto_hatch_vi",
        ),
        (
            "103TDI Comfortline VI Auto MY10",
            "Diesel",
            "volkswagen_golf_comfortline_diesel_auto_hatch_vi",
        ),
    ],
)
def test_volkswagen_golf_vi_comfortline_lanes_map_to_expected_tags(
    variant, fuel_type, expected_tag
):
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Volkswagen",
        "model": "Golf",
        "variant": variant,
        "series": "VI",
        "body_type": "Hatch",
        "transmission": "Automatic",
        "fuel_type": fuel_type,
        "year": "2011",
        "price": "9000",
        "url": f"https://www.example.com/2011-volkswagen-golf-{variant.lower().replace(' ', '-')}",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


@pytest.mark.parametrize(
    ("variant", "fuel_type"),
    [
        ("GTI VI Auto MY10", "Petrol - Premium ULP"),
        ("R VI Auto MY12", "Petrol - Premium ULP"),
        ("90TSI Trendline VI Auto MY11", "Petrol - Premium ULP"),
        ("118TSI Comfortline VI Manual MY11", "Petrol - Premium ULP"),
    ],
)
def test_volkswagen_golf_vi_non_comfortline_or_manual_rows_do_not_map(variant, fuel_type):
    _load_curve_year_band.cache_clear()

    row = {
        "make": "VW",
        "model": "Golf",
        "variant": variant,
        "series": "VI",
        "body_type": "Hatchback",
        "transmission": "Manual" if "Manual" in variant else "Automatic",
        "fuel_type": fuel_type,
        "year": "2011",
        "price": "9000",
        "url": f"https://www.example.com/2011-volkswagen-golf-{variant.lower().replace(' ', '-')}",
    }

    tag, reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert tag == "UNCLASSIFIED"
    assert reason in {"[DISALLOWED_VARIANT]", "[OUT_OF_SCOPE]", "[AMBIG_BADGE]"}
