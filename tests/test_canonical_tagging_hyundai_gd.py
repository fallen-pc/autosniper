from __future__ import annotations

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_assign_canonical_tag_accepts_hyundai_gd_2012_active_into_early_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Active Auto F",
        "series": "gd",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2012",
        "price": "14800",
        "url": "https://www.example.com/hyundai/i30/active-2012",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "hyundai_i30_active_petrol_auto_hatch_gd"
    assert canonical_reason == "[OK]"


def test_assign_canonical_tag_accepts_hyundai_gd_elite_into_mainstream_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Elite Auto F MY14",
        "series": "gd",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2013",
        "price": "13200",
        "url": "https://www.example.com/hyundai/i30/elite",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "hyundai_i30_active_petrol_auto_hatch_gd"
    assert canonical_reason == "[OK]"


def test_assign_canonical_tag_rejects_hyundai_gd_active_x_from_early_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Hyundai",
        "model": "i30",
        "variant": "Active X Auto F MY16",
        "series": "gd",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2015",
        "price": "14500",
        "url": "https://www.example.com/hyundai/i30/active-x",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "UNCLASSIFIED"
    assert canonical_reason in {"[DISALLOWED_VARIANT]", "[OUT_OF_SCOPE_YEAR]"}
