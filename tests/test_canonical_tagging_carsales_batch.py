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
        (
            {
                "make": "Toyota",
                "model": "Yaris",
                "variant": "YR petrol",
                "body_type": "Hatchback",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2011",
                "price": "4900",
                "url": "https://www.example.com/2011-toyota-yaris-yr-petrol",
            },
            "toyota_yaris_yr_petrol_auto_hatch_ncp90r",
        ),
        (
            {
                "make": "Ford",
                "model": "Focus",
                "variant": "Trend petrol",
                "body_type": "Hatchback",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2016",
                "price": "9000",
                "url": "https://www.example.com/2016-ford-focus-trend-petrol",
            },
            "ford_focus_trend_petrol_auto_hatch_lz",
        ),
        (
            {
                "make": "Toyota",
                "model": "Aurion",
                "variant": "AT-X GSV50R",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2015",
                "price": "17000",
                "url": "https://www.example.com/2015-toyota-aurion-at-x-gsv50r-auto-sedan",
            },
            "toyota_aurion_at-x_petrol_auto_sedan_gsv50r",
        ),
        (
            {
                "make": "Kia",
                "model": "Cerato",
                "variant": "S BD",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2021",
                "price": "18000",
                "url": "https://www.example.com/2021-kia-cerato-s-bd-auto-sedan",
            },
            "kia_cerato_s_petrol_auto_sedan_bd",
        ),
        (
            {
                "make": "Holden",
                "model": "Cruze",
                "variant": "Equipe JH Series II",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2015",
                "price": "6000",
                "url": "https://www.example.com/2015-holden-cruze-equipe-jh-series-ii-auto-sedan",
            },
            "holden_cruze_equipe_petrol_auto_sedan_jh-series-ii",
        ),
        (
            {
                "make": "Ford",
                "model": "Focus",
                "variant": "Trend LW MkII",
                "body_type": "Hatch",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2014",
                "price": "9000",
                "url": "https://www.example.com/2014-ford-focus-trend-lw-mkii-auto-hatch",
            },
            "ford_focus_trend_petrol_auto_hatch_lw-mkii",
        ),
        (
            {
                "make": "Toyota",
                "model": "Aurion",
                "variant": "Prodigy GSV40R",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2010",
                "price": "9000",
                "url": "https://www.example.com/2010-toyota-aurion-prodigy-gsv40r-auto-sedan",
            },
            "toyota_aurion_prodigy_petrol_auto_sedan_gsv40r",
        ),
        (
            {
                "make": "Hyundai",
                "model": "i30",
                "variant": "SX FD",
                "body_type": "Hatch",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2010",
                "price": "8000",
                "url": "https://www.example.com/2010-hyundai-i30-sx-fd-auto-hatch",
            },
            "hyundai_i30_sx_petrol_auto_hatch_fd",
        ),
        (
            {
                "make": "Kia",
                "model": "Cerato",
                "variant": "Sport BD",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2020",
                "price": "20000",
                "url": "https://www.example.com/2020-kia-cerato-sport-bd-auto-sedan",
            },
            "kia_cerato_sport_petrol_auto_sedan_bd",
        ),
        (
            {
                "make": "Hyundai",
                "model": "Elantra",
                "variant": "Elite AD",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2017",
                "price": "15000",
                "url": "https://www.example.com/2017-hyundai-elantra-elite-ad-auto-sedan",
            },
            "hyundai_elantra_elite_petrol_auto_sedan_ad",
        ),
        (
            {
                "make": "Ford",
                "model": "Focus",
                "variant": "Sport LW MkII",
                "body_type": "Hatch",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2014",
                "price": "9000",
                "url": "https://www.example.com/2014-ford-focus-sport-lw-mkii-auto-hatch",
            },
            "ford_focus_sport_petrol_auto_hatch_lw-mkii",
        ),
        (
            {
                "make": "Holden",
                "model": "Barina",
                "variant": "CD TM",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2014",
                "price": "7000",
                "url": "https://www.example.com/2014-holden-barina-cd-tm-auto-sedan",
            },
            "holden_barina_cd_petrol_auto_sedan_tm",
        ),
        (
            {
                "make": "Holden",
                "model": "Calais",
                "variant": "V VE",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2009",
                "price": "12000",
                "url": "https://www.example.com/2009-holden-calais-v-ve-auto-sedan",
            },
            "holden_calais_v_petrol_auto_sedan_ve",
        ),
        (
            {
                "make": "Holden",
                "model": "Calais",
                "variant": "V VE Series II",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2011",
                "price": "12500",
                "url": "https://www.example.com/2011-holden-calais-v-ve-series-ii-auto-sedan",
            },
            "holden_calais_v_petrol_auto_sedan_ve-series-ii",
        ),
        (
            {
                "make": "Toyota",
                "model": "Corolla",
                "variant": "Ascent Sport ZRE152R",
                "body_type": "Hatch",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2011",
                "price": "9500",
                "url": "https://www.example.com/2011-toyota-corolla-ascent-sport-zre152r-auto-hatch",
            },
            "toyota_corolla_ascent-sport_petrol_auto_hatch_zre152r",
        ),
        (
            {
                "make": "Hyundai",
                "model": "i30",
                "variant": "Trophy GD2",
                "body_type": "Hatch",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2014",
                "price": "9500",
                "url": "https://www.example.com/2014-hyundai-i30-trophy-gd2-auto-hatch",
            },
            "hyundai_i30_trophy_petrol_auto_hatch_gd2",
        ),
        (
            {
                "make": "Kia",
                "model": "Cerato",
                "variant": "GT BD",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2020",
                "price": "24000",
                "url": "https://www.example.com/2020-kia-cerato-gt-bd-auto-sedan",
            },
            "kia_cerato_gt_petrol_auto_sedan_bd",
        ),
        (
            {
                "make": "Holden",
                "model": "Commodore",
                "variant": "SV6 VE Series II",
                "body_type": "Wagon",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2011",
                "price": "8000",
                "url": "https://www.example.com/2011-holden-commodore-sv6-ve-series-ii-auto-wagon",
            },
            "holden_commodore_sv6_petrol_auto_wagon_ve-series-ii",
        ),
        (
            {
                "make": "Nissan",
                "model": "X-Trail",
                "variant": "ST T32",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2015",
                "price": "9000",
                "url": "https://www.example.com/2015-nissan-x-trail-st-t32-auto-petrol-suv",
            },
            "nissan_xtrail_st_petrol_auto_suv_t32",
        ),
        (
            {
                "make": "Isuzu",
                "model": "MU-X",
                "variant": "LS-U",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "year": "2022",
                "price": "41000",
                "url": "https://www.example.com/2022-isuzu-mu-x-ls-u-auto-diesel-suv",
            },
            "isuzu_mux_lsu_diesel_auto_suv_mux-gen2",
        ),
        (
            {
                "make": "Isuzu",
                "model": "MU-X",
                "variant": "LS-T",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Diesel",
                "year": "2023",
                "price": "44000",
                "url": "https://www.example.com/2023-isuzu-mu-x-ls-t-auto-diesel-suv",
            },
            "isuzu_mux_lst_diesel_auto_suv_mux-gen2",
        ),
        (
            {
                "make": "Toyota",
                "model": "Kluger",
                "variant": "Grande GSU40R",
                "body_type": "SUV",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2008",
                "price": "9000",
                "url": "https://www.example.com/2008-toyota-kluger-grande-gsu40r-auto-petrol-suv",
            },
            "toyota_kluger_grande_petrol_auto_suv_gsu40r",
        ),
        (
            {
                "make": "Mazda",
                "model": "CX-5",
                "variant": "Grand Touring KE",
                "body_type": "Wagon",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2013",
                "price": "16000",
                "url": "https://www.example.com/2013-mazda-cx-5-grand-touring-ke-auto-petrol-wagon",
            },
            "mazda_cx5_grand-touring_petrol_auto_wagon_ke",
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
            "make": "Toyota",
            "model": "Yaris",
            "variant": "YR NCP130R",
            "body_type": "Hatch",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2013",
            "price": "11000",
            "url": "https://www.example.com/2013-toyota-yaris-yr-ncp130r-auto-hatch",
        },
        {
            "make": "Ford",
            "model": "Focus",
            "variant": "Titanium LZ",
            "body_type": "Hatch",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2016",
            "price": "10000",
            "url": "https://www.example.com/2016-ford-focus-titanium-lz-auto-hatch",
        },
        {
            "make": "Toyota",
            "model": "Aurion",
            "variant": "Presara GSV50R",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2015",
            "price": "19000",
            "url": "https://www.example.com/2015-toyota-aurion-presara-gsv50r-auto-sedan",
        },
        {
            "make": "Holden",
            "model": "Cruze",
            "variant": "CD JH Series II",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2015",
            "price": "6000",
            "url": "https://www.example.com/2015-holden-cruze-cd-jh-series-ii-auto-sedan",
        },
        {
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active FD",
            "body_type": "Hatch",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2010",
            "price": "8000",
            "url": "https://www.example.com/2010-hyundai-i30-active-fd-auto-hatch",
        },
        {
            "make": "Hyundai",
            "model": "Elantra",
            "variant": "Active AD",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2017",
            "price": "14000",
            "url": "https://www.example.com/2017-hyundai-elantra-active-ad-auto-sedan",
        },
        {
            "make": "Holden",
            "model": "Barina",
            "variant": "CDX TM",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2014",
            "price": "7500",
            "url": "https://www.example.com/2014-holden-barina-cdx-tm-auto-sedan",
        },
        {
            "make": "Holden",
            "model": "Calais",
            "variant": "VE",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2009",
            "price": "9000",
            "url": "https://www.example.com/2009-holden-calais-ve-auto-sedan",
        },
        {
            "make": "Toyota",
            "model": "Corolla",
            "variant": "Ascent ZRE152R",
            "body_type": "Hatch",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2011",
            "price": "8500",
            "url": "https://www.example.com/2011-toyota-corolla-ascent-zre152r-auto-hatch",
        },
        {
            "make": "Hyundai",
            "model": "i30",
            "variant": "Active GD2",
            "body_type": "Hatch",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2014",
            "price": "9000",
            "url": "https://www.example.com/2014-hyundai-i30-active-gd2-auto-hatch",
        },
        {
            "make": "Holden",
            "model": "Commodore",
            "variant": "SV6 VE Series II",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2011",
            "price": "8500",
            "url": "https://www.example.com/2011-holden-commodore-sv6-ve-series-ii-auto-sedan",
        },
        {
            "make": "Nissan",
            "model": "X-Trail",
            "variant": "ST-L T32",
            "body_type": "SUV",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2015",
            "price": "11000",
            "url": "https://www.example.com/2015-nissan-x-trail-st-l-t32-auto-petrol-suv",
        },
        {
            "make": "Isuzu",
            "model": "MU-X",
            "variant": "LS-U",
            "body_type": "SUV",
            "transmission": "Automatic",
            "fuel_type": "Diesel",
            "year": "2018",
            "price": "30000",
            "url": "https://www.example.com/2018-isuzu-mu-x-ls-u-auto-diesel-suv",
        },
        {
            "make": "Toyota",
            "model": "Kluger",
            "variant": "KX-R GSU40R",
            "body_type": "SUV",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2008",
            "price": "8500",
            "url": "https://www.example.com/2008-toyota-kluger-kx-r-gsu40r-auto-petrol-suv",
        },
        {
            "make": "Mazda",
            "model": "CX-5",
            "variant": "Grand Touring KE",
            "body_type": "Wagon",
            "transmission": "Automatic",
            "fuel_type": "Diesel",
            "year": "2013",
            "price": "15500",
            "url": "https://www.example.com/2013-mazda-cx-5-grand-touring-ke-auto-diesel-wagon",
        },
    ],
)
def test_yaris_focus_batch_keeps_adjacent_lanes_separate(row):
    _load_curve_year_band.cache_clear()

    tag, _reason = assign_canonical_tag(row, require_price=True)

    assert tag not in {
        "toyota_yaris_yr_petrol_auto_hatch_ncp90r",
        "ford_focus_trend_petrol_auto_hatch_lz",
        "ford_focus_trend_petrol_auto_hatch_lw-mkii",
        "toyota_aurion_at-x_petrol_auto_sedan_gsv50r",
        "kia_cerato_s_petrol_auto_sedan_bd",
        "holden_cruze_equipe_petrol_auto_sedan_jh-series-ii",
        "hyundai_i30_sx_petrol_auto_hatch_fd",
        "kia_cerato_sport_petrol_auto_sedan_bd",
        "hyundai_elantra_elite_petrol_auto_sedan_ad",
        "ford_focus_sport_petrol_auto_hatch_lw-mkii",
        "holden_barina_cd_petrol_auto_sedan_tm",
        "holden_calais_v_petrol_auto_sedan_ve",
        "holden_calais_v_petrol_auto_sedan_ve-series-ii",
        "toyota_corolla_ascent-sport_petrol_auto_hatch_zre152r",
        "hyundai_i30_trophy_petrol_auto_hatch_gd2",
        "kia_cerato_gt_petrol_auto_sedan_bd",
        "holden_commodore_sv6_petrol_auto_wagon_ve-series-ii",
        "nissan_xtrail_st_petrol_auto_suv_t32",
        "isuzu_mux_lsu_diesel_auto_suv_mux-gen2",
        "isuzu_mux_lst_diesel_auto_suv_mux-gen2",
        "toyota_kluger_grande_petrol_auto_suv_gsu40r",
        "mazda_cx5_grand-touring_petrol_auto_wagon_ke",
    }


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


@pytest.mark.parametrize(
    ("row", "expected_tag"),
    [
        (
            {
                "make": "Toyota",
                "model": "Aurion",
                "variant": "AT-X GSV40R",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2008",
                "price": "9000",
                "url": "https://www.example.com/2008-toyota-aurion-at-x-gsv40r-auto-sedan",
            },
            "toyota_aurion_at-x_petrol_auto_sedan_gsv40r",
        ),
        (
            {
                "make": "Kia",
                "model": "Cerato",
                "variant": "S YD",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2014",
                "price": "11000",
                "url": "https://www.example.com/2014-kia-cerato-s-yd-auto-sedan",
            },
            "kia_cerato_s_petrol_auto_sedan_yd",
        ),
        (
            {
                "make": "Holden",
                "model": "Calais",
                "variant": "VE Petrol",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2007",
                "price": "9000",
                "url": "https://www.example.com/2007-holden-calais-ve-auto-sedan",
            },
            "holden_calais_petrol_auto_sedan_ve",
        ),
        (
            {
                "make": "Holden",
                "model": "Cruze",
                "variant": "CDX JG",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2010",
                "price": "5000",
                "url": "https://www.example.com/2010-holden-cruze-cdx-jg-auto-sedan",
            },
            "holden_cruze_cdx_petrol_auto_sedan_jg",
        ),
    ],
)
def test_new_carsales_scrape_lanes_map_to_expected_tags(row, expected_tag):
    _load_curve_year_band.cache_clear()

    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


@pytest.mark.parametrize(
    "row",
    [
        {
            "make": "Toyota",
            "model": "Aurion",
            "variant": "Sportivo SX6 GSV40R",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2010",
            "price": "12000",
            "url": "https://www.example.com/2010-toyota-aurion-sportivo-sx6-gsv40r-auto-sedan",
        },
        {
            "make": "Kia",
            "model": "Cerato",
            "variant": "Sport YD",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2017",
            "price": "16000",
            "url": "https://www.example.com/2017-kia-cerato-sport-yd-auto-sedan",
        },
        {
            "make": "Holden",
            "model": "Calais",
            "variant": "V VE",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2009",
            "price": "12000",
            "url": "https://www.example.com/2009-holden-calais-v-ve-auto-sedan",
        },
        {
            "make": "Holden",
            "model": "Cruze",
            "variant": "Equipe JH Series II",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2014",
            "price": "6500",
            "url": "https://www.example.com/2014-holden-cruze-equipe-jh-series-ii-auto-sedan",
        },
    ],
)
def test_new_carsales_scrape_lanes_do_not_absorb_excluded_trims(row):
    _load_curve_year_band.cache_clear()

    tag, _reason = assign_canonical_tag(row, require_price=True)

    assert tag not in {
        "toyota_aurion_at-x_petrol_auto_sedan_gsv40r",
        "kia_cerato_s_petrol_auto_sedan_yd",
        "holden_calais_petrol_auto_sedan_ve",
        "holden_cruze_cdx_petrol_auto_sedan_jg",
    }


@pytest.mark.parametrize(
    ("row", "expected_tag"),
    [
        (
            {
                "make": "Holden",
                "model": "Cruze",
                "variant": "CDX Petrol",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2012",
                "price": "5500",
                "url": "https://www.example.com/2012-holden-cruze-cdx-petrol-auto-sedan",
            },
            "holden_cruze_cdx_petrol_auto_sedan_jh-series-ii",
        ),
        (
            {
                "make": "Holden",
                "model": "Cruze",
                "variant": "CD Petrol",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2012",
                "price": "5200",
                "url": "https://www.example.com/2012-holden-cruze-cd-petrol-auto-sedan",
            },
            "holden_cruze_cd_petrol_auto_sedan_jh-series-ii",
        ),
        (
            {
                "make": "Hyundai",
                "model": "Elantra",
                "variant": "Active Petrol",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2015",
                "price": "12000",
                "url": "https://www.example.com/2015-hyundai-elantra-active-petrol",
            },
            "hyundai_elantra_active_petrol_auto_sedan_md3",
        ),
        (
            {
                "make": "Hyundai",
                "model": "Elantra",
                "variant": "Active Petrol",
                "body_type": "Sedan",
                "transmission": "Automatic",
                "fuel_type": "Petrol",
                "year": "2018",
                "price": "15000",
                "url": "https://www.example.com/2018-hyundai-elantra-active-petrol",
            },
            "hyundai_elantra_active_petrol_auto_sedan_ad",
        ),
    ],
)
def test_staged_batch_lanes_map_to_expected_tags(row, expected_tag):
    _load_curve_year_band.cache_clear()

    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


@pytest.mark.parametrize(
    "row",
    [
        {
            "make": "Holden",
            "model": "Cruze",
            "variant": "SRi-V Petrol",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2012",
            "price": "5700",
            "url": "https://www.example.com/2012-holden-cruze-sri-v-auto-sedan",
        },
        {
            "make": "Hyundai",
            "model": "Elantra",
            "variant": "Elite Petrol",
            "body_type": "Sedan",
            "transmission": "Automatic",
            "fuel_type": "Petrol",
            "year": "2018",
            "price": "16000",
            "url": "https://www.example.com/2018-hyundai-elantra-elite-petrol",
        },
    ],
)
def test_staged_batch_lanes_do_not_absorb_excluded_trims(row):
    _load_curve_year_band.cache_clear()

    tag, _reason = assign_canonical_tag(row, require_price=True)

    assert tag not in {
        "holden_cruze_cdx_petrol_auto_sedan_jh-series-ii",
        "holden_cruze_cd_petrol_auto_sedan_jh-series-ii",
        "hyundai_elantra_active_petrol_auto_sedan_md3",
        "hyundai_elantra_active_petrol_auto_sedan_ad",
    }
