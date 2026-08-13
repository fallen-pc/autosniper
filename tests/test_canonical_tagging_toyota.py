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

    canonical_tag, canonical_reason = assign_canonical_tag(row, require_price=True)

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


def test_camry_altise_asv50r_maps_to_expected_lane():
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Toyota",
        "model": "Camry",
        "variant": "Altise ASV50R",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "5009",
        "url": "https://www.example.com/2013-toyota-camry-altise-asv50r-automatic-sedan",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "toyota_camry_altise_petrol_auto_sedan_asv50r",
        "[OK]",
    )


def test_camry_altise_xv30_series_map_to_expected_lanes():
    _load_curve_year_band.cache_clear()

    acv_row = {
        "make": "Toyota",
        "model": "Camry",
        "variant": "Altise ACV36R",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2004",
        "price": "5500",
        "url": "https://www.example.com/2004-toyota-camry-altise-acv36r-automatic-sedan",
    }
    mcv_row = {
        **acv_row,
        "variant": "Altise MCV36R",
        "year": "2005",
        "url": "https://www.example.com/2005-toyota-camry-altise-mcv36r-automatic-sedan",
    }
    sportivo_row = {
        **acv_row,
        "variant": "Sportivo ACV36R",
        "url": "https://www.example.com/2004-toyota-camry-sportivo-acv36r-automatic-sedan",
    }

    assert assign_canonical_tag(acv_row, require_price=True)[0:2] == (
        "toyota_camry_altise_petrol_auto_sedan_acv36r",
        "[OK]",
    )
    assert assign_canonical_tag(mcv_row, require_price=True)[0:2] == (
        "toyota_camry_altise_petrol_auto_sedan_mcv36r",
        "[OK]",
    )
    assert assign_canonical_tag(sportivo_row, require_price=True)[0] == "UNCLASSIFIED"


def test_camry_atara_s_asv50r_maps_without_absorbing_sx_or_sl():
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Toyota",
        "model": "Camry",
        "variant": "Atara S ASV50R",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "14900",
        "url": "https://www.example.com/2013-toyota-camry-atara-s-asv50r-auto-sedan",
    }
    sx_row = {
        **row,
        "variant": "Atara SX ASV50R",
        "url": "https://www.example.com/2013-toyota-camry-atara-sx-asv50r-auto-sedan",
    }
    sl_row = {
        **row,
        "variant": "Atara SL ASV50R",
        "url": "https://www.example.com/2013-toyota-camry-atara-sl-asv50r-auto-sedan",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "toyota_camry_atara-s_petrol_auto_sedan_asv50r",
        "[OK]",
    )
    assert assign_canonical_tag(sx_row, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(sl_row, require_price=True)[0] == "UNCLASSIFIED"


def test_hilux_sr_gun126r_4x4_dual_cab_chassis_maps_to_expected_lane():
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Toyota",
        "model": "Hilux",
        "variant": "SR (4X4) GUN126R",
        "body_type": "Dual Cab Chassis",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2020",
        "price": "42975",
        "url": "https://www.example.com/2020-toyota-hilux-sr-4x4-gun126r-turbo-diesel-automatic-dual-cab-chassis",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "toyota_hilux_sr_diesel_auto_cab_chassis_gun126r",
        "[OK]",
    )


def test_hilux_sr_gun126r_rejects_nearby_ute_lanes():
    _load_curve_year_band.cache_clear()

    base_row = {
        "make": "Toyota",
        "model": "Hilux",
        "variant": "SR (4X4) GUN126R",
        "body_type": "Dual Cab Chassis",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2020",
        "price": "42975",
        "url": "https://www.example.com/2020-toyota-hilux-sr-4x4-gun126r-turbo-diesel-automatic-dual-cab-chassis",
    }
    rejected_rows = [
        {**base_row, "variant": "SR5 (4X4) GUN126R"},
        {**base_row, "variant": "SR Hi-Rider 4x2 GUN126R"},
        {**base_row, "body_type": "Dual Cab Pick Up", "url": "https://www.example.com/2020-toyota-hilux-sr-4x4-gun126r-auto-pick-up"},
        {**base_row, "transmission": "Manual", "url": "https://www.example.com/2020-toyota-hilux-sr-4x4-gun126r-manual-dual-cab-chassis"},
    ]

    for row in rejected_rows:
        canonical_tag, canonical_reason = assign_canonical_tag(row, require_price=True)
        assert canonical_tag == "UNCLASSIFIED"
        assert canonical_reason in {"[DISALLOWED_VARIANT]", "[OUT_OF_SCOPE]"}


def test_yaris_ascent_ncp130r_maps_to_expected_lane():
    _load_curve_year_band.cache_clear()

    row = {
        "make": "Toyota",
        "model": "Yaris",
        "variant": "Ascent NCP130R",
        "body_type": "Hatch",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2018",
        "price": "17500",
        "url": "https://www.example.com/2018-toyota-yaris-ascent-ncp130r-auto-hatch",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        "toyota_yaris_ascent_petrol_auto_hatch_ncp130r",
        "[OK]",
    )


def test_yaris_ascent_ncp130r_rejects_other_yaris_lanes():
    _load_curve_year_band.cache_clear()

    base_row = {
        "make": "Toyota",
        "model": "Yaris",
        "variant": "Ascent NCP130R",
        "body_type": "Hatch",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2018",
        "price": "17500",
        "url": "https://www.example.com/2018-toyota-yaris-ascent-ncp130r-auto-hatch",
    }
    rejected_rows = [
        ({**base_row, "variant": "YR NCP130R", "year": "2014"}, "toyota_yaris_yr_petrol_auto_hatch_ncp130r"),
        ({**base_row, "variant": "Ascent NCP130R", "transmission": "Manual"}, "toyota_yaris_ascent_petrol_manual_hatch_ncp130r"),
        ({**base_row, "variant": "SX NCP131R"}, "UNCLASSIFIED"),
        ({**base_row, "variant": "Yaris Cross Ascent"}, "UNCLASSIFIED"),
    ]

    for row, expected_tag in rejected_rows:
        canonical_tag, canonical_reason = assign_canonical_tag(row, require_price=True)
        assert canonical_tag == expected_tag
        if expected_tag == "UNCLASSIFIED":
            assert canonical_reason in {"[DISALLOWED_VARIANT]", "[OUT_OF_SCOPE]"}
        else:
            assert canonical_reason == "[OK]"


def test_corolla_ascent_sport_zre182r_manual_maps_without_absorbing_ascent_manual():
    _load_curve_year_band.cache_clear()

    sport_manual = {
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Ascent Sport ZRE182R",
        "body_type": "Hatch",
        "transmission": "Manual",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "11500",
        "url": "https://www.example.com/2014-toyota-corolla-ascent-sport-zre182r-manual-hatch",
    }
    ascent_manual = {
        **sport_manual,
        "variant": "Ascent ZRE182R",
        "url": "https://www.example.com/2014-toyota-corolla-ascent-zre182r-manual-hatch",
    }

    assert assign_canonical_tag(sport_manual, require_price=True)[0:2] == (
        "toyota_corolla_ascent-sport_petrol_manual_hatch_zre18x",
        "[OK]",
    )
    assert assign_canonical_tag(ascent_manual, require_price=True)[0] == "UNCLASSIFIED"


def test_rav4_gx_hybrid_drivetrains_map_to_separate_axah_lanes():
    _load_curve_year_band.cache_clear()

    base_row = {
        "make": "Toyota",
        "model": "RAV4",
        "badge": "GX",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Hybrid",
        "year": "2024",
        "price": "42500",
    }
    cases = [
        (
            {**base_row, "variant": "GX (2WD) Hybrid", "url": "https://www.example.com/rav4-gx-2wd"},
            "toyota_rav4_gx_hybrid_auto_suv_axah52r",
        ),
        (
            {**base_row, "variant": "GX (AWD) Hybrid", "url": "https://www.example.com/rav4-gx-awd"},
            "toyota_rav4_gx_hybrid_auto_suv_axah54r",
        ),
        (
            {**base_row, "variant": "GX eFour Hybrid", "url": "https://www.example.com/rav4-gx-efour"},
            "toyota_rav4_gx_hybrid_auto_suv_axah54r",
        ),
    ]

    for row, expected_tag in cases:
        assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


def test_rav4_gx_hybrid_does_not_absorb_gxl_or_petrol_rows():
    _load_curve_year_band.cache_clear()

    base_row = {
        "make": "Toyota",
        "model": "RAV4",
        "badge": "GX",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Hybrid",
        "year": "2024",
        "price": "42500",
        "url": "https://www.example.com/rav4",
    }
    rejected_rows = [{**base_row, "badge": "GXL", "variant": "GXL (2WD) Hybrid"}]

    for row in rejected_rows:
        assert assign_canonical_tag(row, require_price=True)[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(
        {**base_row, "fuel_type": "Petrol", "variant": "GX (2WD)"},
        require_price=True,
    )[0] == "toyota_rav4_gx_petrol_auto_suv_mxaa52r"


def test_rav4_gx_petrol_maps_by_generation_and_drivetrain():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Toyota",
        "model": "RAV4",
        "badge": "GX",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "price": "29000",
    }
    cases = [
        (
            {**base_row, "year": "2016", "variant": "GX (2WD)", "url": "https://example.test/zsa42r"},
            "toyota_rav4_gx_petrol_auto_suv_zsa42r",
        ),
        (
            {**base_row, "year": "2016", "variant": "GX (AWD)", "url": "https://example.test/asa44r"},
            "toyota_rav4_gx_petrol_auto_suv_asa44r",
        ),
        (
            {**base_row, "year": "2021", "variant": "GX (2WD)", "url": "https://example.test/mxaa52r"},
            "toyota_rav4_gx_petrol_auto_suv_mxaa52r",
        ),
    ]
    for row, expected_tag in cases:
        assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")

    rejected_rows = [
        {**base_row, "year": "2021", "variant": "GXL (2WD)", "badge": "GXL", "url": "https://example.test/gxl"},
        {**base_row, "year": "2025", "variant": "GX (AWD)", "url": "https://example.test/new-awd"},
    ]
    for row in rejected_rows:
        assert assign_canonical_tag(row, require_price=True)[0] == "UNCLASSIFIED"


def test_rav4_cv_aca33r_maps_automatic_4x4_only():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Toyota",
        "model": "RAV4",
        "badge": "CV",
        "series": "ACA33R",
        "variant": "CV Auto 4x4",
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2008",
        "price": "9500",
        "url": "https://example.test/rav4-cv-aca33r",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "toyota_rav4_cv_petrol_auto_suv_aca33r",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "transmission": "Manual", "variant": "CV Manual 4x4"},
        require_price=True,
    )[0] == "UNCLASSIFIED"
    assert assign_canonical_tag(
        {**base_row, "badge": "CVX", "variant": "CVX Auto 4x4"},
        require_price=True,
    )[0] == "UNCLASSIFIED"
