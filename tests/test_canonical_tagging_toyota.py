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
