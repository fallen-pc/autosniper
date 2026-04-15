from __future__ import annotations

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


def test_assign_canonical_tag_rejects_corolla_conquest_from_ascent_curve():
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Conquest ZRE152R",
        "body_type": "sedan",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2008",
        "price": "3509",
        "url": "https://www.example.com/2008-toyota-corolla-conquest-zre152r-automatic-sedan",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "UNCLASSIFIED"
    assert canonical_reason == "[DISALLOWED_VARIANT]"


def test_corolla_hybrid_hatch_year_bands_map_to_expected_series():
    _load_curve_year_band.cache_clear()

    zwe211r_row = {
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Ascent Sport Hybrid",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Hybrid",
        "year": "2019",
        "price": "24490",
        "url": "https://www.example.com/2019-toyota-corolla-ascent-sport-hybrid-auto-hatchback",
    }
    zwe219r_row = {
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Ascent Sport Hybrid",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Hybrid",
        "year": "2023",
        "price": "31990",
        "url": "https://www.example.com/2023-toyota-corolla-ascent-sport-hybrid-auto-hatchback",
    }
    sx_row = {
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Sx Hybrid",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Hybrid",
        "year": "2024",
        "price": "36990",
        "url": "https://www.example.com/2024-toyota-corolla-sx-hybrid-auto-hatchback",
    }

    assert assign_canonical_tag(zwe211r_row, require_price=True)[0:2] == (
        "toyota_corolla_ascent-sport_hybrid_auto_hatch_zwe211r",
        "[OK]",
    )
    assert assign_canonical_tag(zwe219r_row, require_price=True)[0:2] == (
        "toyota_corolla_ascent-sport_hybrid_auto_hatch_zwe219r",
        "[OK]",
    )
    assert assign_canonical_tag(sx_row, require_price=True)[0:2] == (
        "UNCLASSIFIED",
        "[DISALLOWED_VARIANT]",
    )


def test_camry_ascent_sport_hybrid_axvh71r_maps_to_expected_lane():
    _load_curve_year_band.cache_clear()

    sport_row = {
        "make": "Toyota",
        "model": "Camry",
        "variant": "Ascent Sport Hybrid AXVH71R",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Hybrid",
        "year": "2019",
        "price": "27990",
        "url": "https://www.example.com/2019-toyota-camry-ascent-sport-hybrid-axvh71r-cvt-sedan",
    }
    wrong_series_row = {
        "make": "Toyota",
        "model": "Camry",
        "variant": "Ascent Sport Hybrid AXVH70R",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Hybrid",
        "year": "2021",
        "price": "30990",
        "url": "https://www.example.com/2021-toyota-camry-ascent-sport-hybrid-axvh70r-cvt-sedan",
    }

    assert assign_canonical_tag(sport_row, require_price=True)[0:2] == (
        "toyota_camry_ascent-sport_hybrid_auto_sedan_axvh71r",
        "[OK]",
    )
    assert assign_canonical_tag(wrong_series_row, require_price=True)[0:2] == (
        "UNCLASSIFIED",
        "[DISALLOWED_VARIANT]",
    )
