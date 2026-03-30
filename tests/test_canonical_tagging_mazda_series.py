from __future__ import annotations

from shared.canonical_tagging import assign_canonical_tag


def test_assign_canonical_tag_rejects_mazda_bm_from_bl_curve():
    row = {
        "url": "https://www.grays.com/lot/0001-21049175/motor-vehicles-motor-cycles/2013-mazda-3-neo-bm-automatic-hatchback",
        "make": "Mazda",
        "model": "3",
        "variant": "neo bm",
        "series": "",
        "body_type": "hatchback",
        "transmission": "automatic",
        "fuel_type": "petrol",
        "year": "2013",
        "price": "7120",
    }

    canonical_tag, canonical_reason, _drivetrain = assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "UNCLASSIFIED"
    assert canonical_reason in {"[DISALLOWED_VARIANT]", "[OUT_OF_SCOPE_YEAR]"}
