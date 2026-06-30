from __future__ import annotations

import pytest

from shared.canonical_tagging import _load_curve_year_band, assign_canonical_tag


@pytest.mark.parametrize(
    ("row", "expected_tag"),
    [
        (
            {
                "make": "Toyota",
                "model": "Camry",
                "variant": "Altise ACV40R",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2008",
                "price": "8500",
                "url": "https://www.example.com/2008-toyota-camry-altise-acv40r-auto-sedan",
            },
            "toyota_camry_altise_petrol_auto_sedan_acv40r",
        ),
        (
            {
                "make": "Toyota",
                "model": "Corolla",
                "variant": "Ascent ZRE152R",
                "body_type": "Hatch",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2009",
                "price": "9000",
                "url": "https://www.example.com/2009-toyota-corolla-ascent-zre152r-auto-hatch",
            },
            "toyota_corolla_ascent_petrol_auto_hatch_zre152r",
        ),
        (
            {
                "make": "Hyundai",
                "model": "Accent",
                "variant": "Sport RB6",
                "body_type": "Hatch",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2018",
                "price": "13000",
                "url": "https://www.example.com/2018-hyundai-accent-sport-rb6-auto-hatch",
            },
            "hyundai_accent_sport_petrol_auto_hatch_rb",
        ),
        (
            {
                "make": "Ford",
                "model": "Territory",
                "variant": "Titanium SZ",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "year": "2013",
                "price": "11000",
                "url": "https://www.example.com/2013-ford-territory-titanium-sz-diesel-auto-suv",
            },
            "ford_territory_titanium_diesel_auto_suv_sz",
        ),
        (
            {
                "make": "Mitsubishi",
                "model": "Pajero",
                "variant": "GLX NX",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "year": "2018",
                "price": "30000",
                "url": "https://www.example.com/2018-mitsubishi-pajero-glx-nx-diesel-auto-suv",
            },
            "mitsubishi_pajero_glx_diesel_auto_suv_nx",
        ),
        (
            {
                "make": "Mazda",
                "model": "CX5",
                "variant": "Maxx Sport KE Series 2",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2015",
                "price": "14500",
                "url": "https://www.example.com/2015-mazda-cx5-maxx-sport-ke-series-2-auto-petrol",
            },
            "mazda_cx5_maxx-sport_petrol_auto_wagon_ke",
        ),
        (
            {
                "make": "Mazda",
                "model": "CX-5",
                "variant": "Grand Touring KE",
                "body_type": "Wagon",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "year": "2014",
                "price": "15000",
                "url": "https://www.example.com/2014-mazda-cx-5-grand-touring-ke-auto-diesel-wagon",
            },
            "mazda_cx5_grand-touring_diesel_auto_wagon_ke",
        ),
    ],
)
def test_carsales_batch_lanes_map_to_expected_tags(row, expected_tag):
    _load_curve_year_band.cache_clear()

    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


@pytest.mark.parametrize(
    "row",
    [
        {
            "make": "Toyota",
            "model": "Yaris",
            "variant": "Ascent NCP130R",
            "body_type": "Hatch",
            "transmission": "Manual",
            "fuel_type": "Petrol",
            "year": "2016",
            "price": "11000",
            "url": "https://www.example.com/2016-toyota-yaris-ascent-ncp130r-manual-hatch",
        },
        {
            "make": "Mitsubishi",
            "model": "Triton",
            "variant": "GLX-R MN",
            "body_type": "Dual Cab",
            "transmission": "Automatic",
            "fuel_type": "Diesel",
            "year": "2013",
            "price": "14000",
            "url": "https://www.example.com/2013-mitsubishi-triton-glx-r-mn-auto-dual-cab",
        },
        {
            "make": "Hyundai",
            "model": "iLoad",
            "variant": "TQ manual turbo diesel van",
            "body_type": "Van",
            "transmission": "Manual",
            "fuel_type": "Diesel",
            "year": "2012",
            "price": "12000",
            "url": "https://www.example.com/2012-hyundai-iload-tq-manual-diesel-van",
        },
    ],
)
def test_carsales_batch_manual_and_glxr_lanes_are_supported(row):
    _load_curve_year_band.cache_clear()

    tag, reason = assign_canonical_tag(row, require_price=True)

    assert tag != "UNCLASSIFIED"
    assert reason == "[OK]"


@pytest.mark.parametrize(
    "row",
    [
        {
            "make": "Mitsubishi",
            "model": "Pajero",
            "variant": "GLS NX",
            "body_type": "SUV",
            "transmission": "Automatic",
            "fuel_type": "Diesel",
            "year": "2018",
            "price": "32000",
            "url": "https://www.example.com/2018-mitsubishi-pajero-gls-nx-auto-diesel",
        },
        {
            "make": "Mitsubishi",
            "model": "Pajero",
            "variant": "Exceed NX",
            "body_type": "SUV",
            "transmission": "Automatic",
            "fuel_type": "Diesel",
            "year": "2018",
            "price": "34000",
            "url": "https://www.example.com/2018-mitsubishi-pajero-exceed-nx-auto-diesel",
        },
    ],
)
def test_pajero_nx_trim_lanes_do_not_fall_into_glx(row):
    _load_curve_year_band.cache_clear()

    tag, reason = assign_canonical_tag(row, require_price=True)

    assert tag != "mitsubishi_pajero_glx_diesel_auto_suv_nx"
    assert tag != "UNCLASSIFIED"
    assert reason == "[OK]"


@pytest.mark.parametrize("variant", ["Grande ACV40R", "Sportivo ACV40R"])
def test_camry_acv40r_altise_does_not_absorb_other_trims(variant):
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Toyota",
        "model": "Camry",
        "variant": variant,
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2008",
        "price": "9000",
        "url": f"https://www.example.com/2008-toyota-camry-{variant.lower().replace(' ', '-')}-auto-sedan",
    }

    tag, reason = assign_canonical_tag(row, require_price=True)

    assert tag == "UNCLASSIFIED"
    assert reason == "[DISALLOWED_VARIANT]"
