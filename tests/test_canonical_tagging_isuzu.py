from __future__ import annotations

import pytest

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


@pytest.mark.parametrize(
    ("variant", "expected_tag"),
    [
        ("LS-M Auto 4x4 MY18", "isuzu_mux_lsm_diesel_auto_suv_mux"),
        ("LS-U Auto 4x4 MY18", "isuzu_mux_lsu_diesel_auto_suv_mux"),
        ("LS-T Auto 4x4 MY18", "isuzu_mux_lst_diesel_auto_suv_mux"),
    ],
)
def test_isuzu_mux_trim_lanes_map_to_expected_tags(variant, expected_tag):
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Isuzu",
        "model": "MU-X",
        "variant": variant,
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2018",
        "price": "30000",
        "url": f"https://www.example.com/2018-isuzu-mu-x-{variant.lower().replace(' ', '-')}",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


def test_isuzu_mux_lsu_does_not_fall_into_lst_curve():
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Isuzu",
        "model": "Mux",
        "variant": "LS-U Auto 4x4 MY20",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2020",
        "price": "36000",
        "url": "https://www.example.com/2020-isuzu-mu-x-ls-u-auto-4x4",
    }

    tag, reason = assign_canonical_tag(row, require_price=True)

    assert tag == "isuzu_mux_lsu_diesel_auto_suv_mux"
    assert tag != "isuzu_mux_lst_diesel_auto_suv_mux"
    assert reason == "[OK]"


def test_isuzu_mux_rejects_manual_from_auto_lanes():
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Isuzu",
        "model": "MU-X",
        "variant": "LS-U Manual 4x4 MY18",
        "body_type": "SUV",
        "transmission": "Manual",
        "fuel_type": "Diesel",
        "year": "2018",
        "price": "30000",
        "url": "https://www.example.com/2018-isuzu-mu-x-ls-u-manual",
    }

    tag, reason = assign_canonical_tag(row, require_price=True)

    assert tag == "UNCLASSIFIED"
    assert reason == "[OUT_OF_SCOPE]"


@pytest.mark.parametrize(
    ("variant", "expected_tag"),
    [
        ("LS-U Auto 4x4 MY14", "isuzu_mux_lsu_diesel_auto_suv_mux"),
        ("LS-T Auto 4x4 MY14", "isuzu_mux_lst_diesel_auto_suv_mux"),
    ],
)
def test_isuzu_mux_first_generation_2014_rows_map_to_existing_lanes(variant, expected_tag):
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Isuzu",
        "model": "MU-X",
        "variant": variant,
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2014",
        "price": "26000",
        "url": f"https://www.example.com/2014-isuzu-mu-x-{variant.lower().replace(' ', '-')}",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


def test_isuzu_mux_2021_newer_generation_maps_to_generation_two_curve():
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Isuzu",
        "model": "MU-X",
        "variant": "LS-T Auto 4x4 MY21",
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2021",
        "price": "42000",
        "url": "https://www.example.com/2021-isuzu-mu-x-ls-t-auto-4x4-my21",
    }

    tag, reason = assign_canonical_tag(row, require_price=True)

    assert tag == "isuzu_mux_lst_diesel_auto_suv_mux-gen2"
    assert reason == "[OK]"
