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


def test_calais_v_vf_v6_auto_maps_without_absorbing_v8():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Calais",
        "badge": "V",
        "series": "VF",
        "variant": "V VF Auto MY14",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "17500",
        "url": "https://example.test/calais-v-vf",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_calais_v_petrol_auto_sedan_vf",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "variant": "V VF V8 Auto"},
        require_price=True,
    )[0] == "UNCLASSIFIED"


def test_cruze_cd_jg_auto_petrol_sedan_maps_without_absorbing_adjacent_lanes():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Cruze",
        "variant": "CD JG",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2010",
        "price": "5000",
        "url": "https://example.test/cruze-cd-jg",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_cruze_cd_petrol_auto_sedan_jg",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "CDX JG"},
        {**base_row, "variant": "CD JH Series II", "year": "2012"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "body_type": "Hatchback"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "holden_cruze_cd_petrol_auto_sedan_jg"
        )


def test_barina_tk_auto_petrol_sedan_maps_without_absorbing_tm_or_hatch():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Barina",
        "variant": "TK",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2010",
        "price": "5000",
        "url": "https://example.test/barina-tk",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_barina_tk_petrol_auto_sedan",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "CD TM", "year": "2013"},
        {**base_row, "body_type": "Hatchback"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "holden_barina_tk_petrol_auto_sedan"
        )


def test_cruze_sri_v_jh_series_ii_auto_sedan_stays_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Cruze",
        "variant": "SRi-V JH Series II",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2012",
        "price": "5700",
        "url": "https://example.test/cruze-sri-v-jh-series-ii",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_cruze_sri-v_petrol_auto_sedan_jh-series-ii",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "SRi JH Series II"},
        {**base_row, "variant": "CDX JH Series II"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "body_type": "Hatchback"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "holden_cruze_sri-v_petrol_auto_sedan_jh-series-ii"
        )


def test_cruze_sri_jh_series_ii_auto_sedan_does_not_absorb_sri_v():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Cruze",
        "variant": "SRi JH Series II",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "5800",
        "url": "https://example.test/cruze-sri-jh-series-ii",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_cruze_sri_petrol_auto_sedan_jh-series-ii",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "variant": "SRi-V JH Series II"},
        require_price=True,
    )[0] == "holden_cruze_sri-v_petrol_auto_sedan_jh-series-ii"


def test_pulsar_st_b17_auto_sedan_stays_generation_and_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Nissan",
        "model": "Pulsar",
        "variant": "ST B17 Series 2 Auto",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2015",
        "price": "8000",
        "url": "https://example.test/pulsar-st-b17",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "nissan_pulsar_st_petrol_auto_sedan_b17",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ST-L B17 Auto"},
        {**base_row, "variant": "Ti B17 Auto"},
        {**base_row, "variant": "ST C12 Auto", "body_type": "Hatchback"},
        {**base_row, "variant": "ST N16 Auto", "year": "2005"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "nissan_pulsar_st_petrol_auto_sedan_b17"
        )


def test_q7_three_litre_tdi_quattro_stays_engine_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Audi",
        "model": "Q7",
        "variant": "3.0 TDI quattro",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2012",
        "price": "15000",
        "url": "https://example.test/audi-q7-three-litre-tdi",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "audi_q7_3.0-tdi-quattro_diesel_auto_suv",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "4.2 TDI quattro"},
        {**base_row, "variant": "50 TDI quattro", "year": "2019"},
        {**base_row, "variant": "3.0 TFSI quattro", "fuel_type": "Petrol"},
        {**base_row, "variant": "3.0 TDI Sport quattro"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "audi_q7_3.0-tdi-quattro_diesel_auto_suv"
        )


def test_x5_xdrive30d_e70_stays_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "BMW",
        "model": "X5",
        "variant": "xDrive 30d E70 LCI",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2012",
        "price": "13000",
        "url": "https://example.test/bmw-x5-xdrive30d-e70",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "bmw_x5_xdrive30d_diesel_auto_suv_e70",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "3.0d E70"},
        {**base_row, "variant": "xDrive30d F15", "year": "2015"},
        {**base_row, "variant": "xDrive40d E70"},
        {**base_row, "variant": "M50d E70"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "bmw_x5_xdrive30d_diesel_auto_suv_e70"
        )


def test_pathfinder_st_r52_stays_trim_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Nissan",
        "model": "Pathfinder",
        "variant": "ST R52",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2016",
        "price": "12000",
        "url": "https://example.test/pathfinder-st-r52",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "nissan_pathfinder_st_petrol_auto_suv_r52",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ST-L R52"},
        {**base_row, "variant": "Ti R52"},
        {**base_row, "variant": "ST R51", "year": "2012"},
        {**base_row, "variant": "ST R53", "year": "2022"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "nissan_pathfinder_st_petrol_auto_suv_r52"
        )


def test_tucson_active_x_tl_stays_trim_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Hyundai",
        "model": "Tucson",
        "variant": "Active X TL",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2017",
        "price": "17000",
        "url": "https://example.test/tucson-active-x-tl",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "hyundai_tucson_active-x_petrol_auto_suv_tl",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Active FWD TL"},
        {**base_row, "variant": "Elite TL"},
        {**base_row, "variant": "Highlander AWD TL"},
        {**base_row, "variant": "Active X NX4", "year": "2022"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "hyundai_tucson_active-x_petrol_auto_suv_tl"
        )


@pytest.mark.parametrize(
    ("variant", "expected_tag"),
    [
        ("LS TJ", "holden_trax_ls_petrol_auto_suv_tj"),
        ("LTZ TJ", "holden_trax_ltz_petrol_auto_suv_tj"),
    ],
)
def test_trax_tj_ls_and_ltz_remain_separate(variant, expected_tag):
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Trax",
        "variant": variant,
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2017",
        "price": "11000",
        "url": "https://example.test/trax-tj",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        expected_tag,
        "[OK]",
    )


def test_trax_tj_curves_exclude_other_editions():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Trax",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2017",
        "price": "11000",
        "url": "https://example.test/trax-other",
    }
    for variant in ["LT TJ", "Black TJ", "Active Special Edition TJ"]:
        assert assign_canonical_tag(
            {**base_row, "variant": variant},
            require_price=True,
        )[0] not in {
            "holden_trax_ls_petrol_auto_suv_tj",
            "holden_trax_ltz_petrol_auto_suv_tj",
        }


@pytest.mark.parametrize(
    ("variant", "expected_tag"),
    [
        ("Cherokee Laredo (4x4) WK", "jeep_grand_cherokee-laredo_diesel_auto_suv_wk"),
        ("Cherokee Limited WK", "jeep_grand_cherokee-limited_diesel_auto_suv_wk"),
    ],
)
def test_grand_cherokee_wk_diesel_trims_remain_separate(variant, expected_tag):
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Jeep",
        "model": "Grand",
        "variant": variant,
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2013",
        "price": "12000",
        "url": "https://example.test/jeep-grand-cherokee-wk",
    }

    assert assign_canonical_tag(row, require_price=True)[0:2] == (
        expected_tag,
        "[OK]",
    )


def test_grand_cherokee_wk_diesel_curves_exclude_other_generations_and_trims():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Jeep",
        "model": "Grand",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2013",
        "price": "12000",
        "url": "https://example.test/jeep-grand-other",
    }
    for variant in [
        "Cherokee Overland WK",
        "Cherokee Summit WK",
        "Cherokee Laredo WH",
        "Cherokee Limited WG",
    ]:
        assert assign_canonical_tag(
            {**base_row, "variant": variant},
            require_price=True,
        )[0] not in {
            "jeep_grand_cherokee-laredo_diesel_auto_suv_wk",
            "jeep_grand_cherokee-limited_diesel_auto_suv_wk",
        }


def test_navara_st_r_d22_manual_diesel_dual_cab_stays_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Nissan",
        "model": "Navara",
        "variant": "ST-R (4x4) D22 Dual",
        "body_type": "Dual Cab",
        "transmission": "Manual",
        "fuel_type": "Diesel",
        "year": "2011",
        "price": "12000",
        "url": "https://example.test/navara-st-r-d22",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "nissan_navara_st-r_diesel_manual_ute_d22",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ST-X D40 Dual"},
        {**base_row, "variant": "ST-R D23 Dual"},
        {**base_row, "transmission": "Automatic"},
        {**base_row, "fuel_type": "Petrol"},
        {**base_row, "variant": "ST-R D22 Single Cab", "body_type": "Cab Chassis"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "nissan_navara_st-r_diesel_manual_ute_d22"
        )


def test_mazda_cx9_luxury_tb_petrol_auto_wagon_stays_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mazda",
        "model": "CX-9",
        "variant": "Luxury AWD",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2011",
        "price": "9000",
        "url": "https://example.test/mazda-cx9-luxury-tb",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "mazda_cx-9_luxury_petrol_auto_wagon_tb",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Grand Touring AWD"},
        {**base_row, "variant": "Classic FWD"},
        {**base_row, "variant": "Azami AWD TC", "year": "2018"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "mazda_cx-9_luxury_petrol_auto_wagon_tb"
        )


def test_audi_q5_2_tfsi_quattro_8r_stays_engine_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Audi",
        "model": "Q5",
        "variant": "2.0 TFSI quattro 8R",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2012",
        "price": "12000",
        "url": "https://example.test/audi-q5-2-tfsi-8r",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "audi_q5_2.0-tfsi-quattro_petrol_auto_suv_8r",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "2.0 TDI quattro 8R", "fuel_type": "Diesel"},
        {**base_row, "variant": "3.0 TFSI quattro 8R"},
        {**base_row, "variant": "45 TFSI quattro 80A", "year": "2019"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "audi_q5_2.0-tfsi-quattro_petrol_auto_suv_8r"
        )


def test_nissan_murano_ti_z51_stays_trim_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Nissan",
        "model": "Murano",
        "variant": "Ti Z51 Series 3",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2012",
        "price": "9000",
        "url": "https://example.test/nissan-murano-ti-z51",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "nissan_murano_ti_petrol_auto_wagon_z51",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ST Z51 Series 3"},
        {**base_row, "variant": "Ti-L Z50", "year": "2007"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "nissan_murano_ti_petrol_auto_wagon_z51"
        )


def test_cruze_cd_jh_series_ii_auto_petrol_hatch_stays_body_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Cruze",
        "variant": "CD JH Series II",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2012",
        "price": "5000",
        "url": "https://example.test/cruze-cd-jh-hatch",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_cruze_cd_petrol_auto_hatch_jh-series-ii",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "body_type": "Sedan"},
        {**base_row, "variant": "CDX JH Series II"},
        {**base_row, "variant": "SRi JH Series II"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "holden_cruze_cd_petrol_auto_hatch_jh-series-ii"
        )


def test_mazda_cx7_luxury_er_stays_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mazda",
        "model": "CX-7",
        "variant": "Luxury (4x4)",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2008",
        "price": "6000",
        "url": "https://example.test/mazda-cx7-luxury-er",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "mazda_cx-7_luxury_petrol_auto_wagon_er",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Luxury Sports (4x4)", "year": "2011"},
        {**base_row, "variant": "Classic"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "mazda_cx-7_luxury_petrol_auto_wagon_er"
        )


def test_audi_q5_2_tdi_quattro_8r_stays_engine_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Audi",
        "model": "Q5",
        "variant": "2.0 TDI quattro 8R",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2011",
        "price": "11000",
        "url": "https://example.test/audi-q5-2-tdi-8r",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "audi_q5_2.0-tdi-quattro_diesel_auto_suv_8r",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "3.0 TDI quattro 8R"},
        {**base_row, "variant": "40 TDI quattro 80A", "year": "2019"},
        {**base_row, "variant": "2.0 TFSI quattro 8R", "fuel_type": "Petrol"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "audi_q5_2.0-tdi-quattro_diesel_auto_suv_8r"
        )


def test_hyundai_i20_active_pb_auto_petrol_hatch_stays_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Hyundai",
        "model": "i20",
        "variant": "Active PB",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "9000",
        "url": "https://example.test/hyundai-i20-active-pb",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "hyundai_i20_active_petrol_auto_hatch_pb",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Elite PB"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "hyundai_i20_active_petrol_auto_hatch_pb"
        )


def test_tiguan_125tsi_5n_auto_petrol_stays_engine_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Volkswagen",
        "model": "Tiguan",
        "variant": "125 TSI 5N",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2010",
        "price": "9000",
        "url": "https://example.test/tiguan-125tsi-5n",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "volkswagen_tiguan_125-tsi_petrol_auto_wagon_5n",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "132 TSI 5N"},
        {**base_row, "variant": "147 TSI 5N"},
        {**base_row, "variant": "125 TDI 5N", "fuel_type": "Diesel"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "volkswagen_tiguan_125-tsi_petrol_auto_wagon_5n"
        )


def test_xtrail_st_l_t32_auto_petrol_stays_trim_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Nissan",
        "model": "X-Trail",
        "variant": "ST-L FWD T32",
        "body_type": "Wagon",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2015",
        "price": "15000",
        "url": "https://example.test/xtrail-st-l-t32",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "nissan_xtrail_st-l_petrol_auto_suv_t32",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ST T32"},
        {**base_row, "variant": "Ti T32"},
        {**base_row, "variant": "ST-L T31", "year": "2012"},
        {**base_row, "variant": "ST-L T33", "year": "2022"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "nissan_xtrail_st-l_petrol_auto_suv_t32"
        )


def test_audi_a4_2_tfsi_quattro_b8_stays_drivetrain_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Audi",
        "model": "A4",
        "variant": "2.0 TFSI quattro B8",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "13000",
        "url": "https://example.test/audi-a4-2-tfsi-quattro-b8",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "audi_a4_2.0-tfsi-quattro_petrol_auto_sedan_b8",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "2.0 TFSI B8"},
        {**base_row, "variant": "1.8 TFSI B8"},
        {**base_row, "variant": "2.0 TFSI quattro B9", "year": "2017"},
        {**base_row, "body_type": "Wagon", "variant": "2.0 TFSI quattro Avant B8"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "audi_a4_2.0-tfsi-quattro_petrol_auto_sedan_b8"
        )


def test_bmw_x3_xdrive20d_f25_stays_engine_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "BMW",
        "model": "X3",
        "variant": "xDrive 20d F25",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2014",
        "price": "15000",
        "url": "https://example.test/bmw-x3-xdrive20d-f25",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "bmw_x3_xdrive-20d_diesel_auto_wagon_f25",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "xDrive 30d F25"},
        {**base_row, "variant": "xDrive 20d E83", "year": "2009"},
        {**base_row, "variant": "xDrive 20d G01", "year": "2019"},
        {**base_row, "fuel_type": "Petrol"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "bmw_x3_xdrive-20d_diesel_auto_wagon_f25"
        )


def test_nissan_pulsar_st_c12_auto_petrol_stays_body_and_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Nissan",
        "model": "Pulsar",
        "variant": "ST C12",
        "body_type": "Hatchback",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2015",
        "price": "10000",
        "url": "https://example.test/pulsar-st-c12",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "nissan_pulsar_st_petrol_auto_hatch_c12",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ST-L C12"},
        {**base_row, "variant": "SSS C12"},
        {**base_row, "variant": "ST B17", "body_type": "Sedan"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "nissan_pulsar_st_petrol_auto_hatch_c12"
        )


def test_hyundai_elantra_active_md_stays_series_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Hyundai",
        "model": "Elantra",
        "variant": "Active MD",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "10000",
        "url": "https://example.test/elantra-active-md",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "hyundai_elantra_active_petrol_auto_sedan_md",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Active MD3", "year": "2015"},
        {**base_row, "variant": "Active AD", "year": "2017"},
        {**base_row, "variant": "Elite MD"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "hyundai_elantra_active_petrol_auto_sedan_md"
        )


def test_touareg_v6_tdi_7p_stays_engine_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Volkswagen",
        "model": "Touareg",
        "variant": "V6 TDI 7P",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2014",
        "price": "18000",
        "url": "https://example.test/touareg-v6-tdi-7p",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "volkswagen_touareg_v6-tdi_diesel_auto_wagon_7p",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "V8 TDI 7P"},
        {**base_row, "variant": "150 TDI 7P"},
        {**base_row, "variant": "V6 TDI 7L", "year": "2009"},
        {**base_row, "variant": "190 TDI CR", "year": "2020"},
        {**base_row, "fuel_type": "Petrol"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "volkswagen_touareg_v6-tdi_diesel_auto_wagon_7p"
        )


def test_pathfinder_st_l_r52_stays_trim_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Nissan",
        "model": "Pathfinder",
        "variant": "ST-L R52",
        "body_type": "Wagon",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2015",
        "price": "16000",
        "url": "https://example.test/pathfinder-st-l-r52",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "nissan_pathfinder_st-l_petrol_auto_wagon_r52",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ST R52"},
        {**base_row, "variant": "Ti R52"},
        {**base_row, "variant": "ST-L R51", "year": "2010"},
        {**base_row, "variant": "ST-L R53", "year": "2023"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "nissan_pathfinder_st-l_petrol_auto_wagon_r52"
        )


def test_ix35_active_fwd_lm_stays_drivetrain_and_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Hyundai",
        "model": "ix35",
        "variant": "Active FWD LM",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2012",
        "price": "11000",
        "url": "https://example.test/ix35-active-fwd-lm",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "hyundai_ix35_active-fwd_petrol_auto_wagon_lm",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Active AWD LM"},
        {**base_row, "variant": "Elite FWD LM"},
        {**base_row, "variant": "Highlander AWD LM"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "hyundai_ix35_active-fwd_petrol_auto_wagon_lm"
        )


def test_mercedes_ml320cdi_w164_stays_engine_and_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mercedes",
        "model": "Benz",
        "variant": "ML320CDI W164",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2008",
        "price": "10000",
        "url": "https://example.test/mercedes-ml320cdi-w164",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "mercedes_benz_ml320cdi_diesel_auto_wagon_w164",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ML320 CDI Luxury W164"},
        {**base_row, "variant": "ML320 CDI Edition 10 W164"},
        {**base_row, "variant": "ML280 CDI W164"},
        {**base_row, "variant": "ML320 CDI W163", "year": "2004"},
        {**base_row, "fuel_type": "Petrol"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "mercedes_benz_ml320cdi_diesel_auto_wagon_w164"
        )


def test_commodore_sv6_ve_auto_petrol_stays_body_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Commodore",
        "variant": "SV6 VE",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2009",
        "price": "8000",
        "url": "https://example.test/commodore-sv6-ve",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_commodore_sv6_petrol_auto_sedan_ve",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "body_type": "Wagon"},
        {**base_row, "variant": "SV6 VZ", "year": "2005"},
        {**base_row, "variant": "SV6 VF", "year": "2014"},
        {**base_row, "variant": "SS VE"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "holden_commodore_sv6_petrol_auto_sedan_ve"
        )


def test_clio_expression_x98_auto_petrol_stays_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Renault",
        "model": "Clio",
        "variant": "Expression Auto",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2015",
        "price": "8500",
        "url": "https://example.test/clio-expression-x98",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "renault_clio_expression_petrol_auto_hatch_x98",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Expression+ Auto"},
        {**base_row, "variant": "Dynamique Auto"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "body_type": "Sedan"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "renault_clio_expression_petrol_auto_hatch_x98"
        )


def test_mercedes_ml250_bluetec_w166_stays_engine_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mercedes",
        "model": "Benz",
        "variant": "ML250 BlueTEC W166",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2013",
        "price": "16000",
        "url": "https://example.test/mercedes-ml250-bluetec-w166",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "mercedes_benz_ml250-bluetec_diesel_auto_wagon_w166",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ML350 BlueTEC W166"},
        {**base_row, "variant": "ML250 CDI W164", "year": "2010"},
        {**base_row, "fuel_type": "Petrol"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "mercedes_benz_ml250-bluetec_diesel_auto_wagon_w166"
        )


def test_subaru_xv_20is_g4x_auto_petrol_stays_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Subaru",
        "model": "XV",
        "variant": "2.0i-S G4X",
        "body_type": "Hatchback",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "14000",
        "url": "https://example.test/subaru-xv-20is-g4x",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "subaru_xv_2.0i-s_petrol_auto_hatch_g4x",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "2.0i-L G4X"},
        {**base_row, "variant": "2.0i G4X"},
        {**base_row, "variant": "2.0i-S G5X", "year": "2018"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Hybrid"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "subaru_xv_2.0i-s_petrol_auto_hatch_g4x"
        )


def test_lancer_es_cj_auto_petrol_stays_sedan_and_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mitsubishi",
        "model": "Lancer",
        "variant": "ES CJ",
        "body_type": "Sedan",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2011",
        "price": "8500",
        "url": "https://example.test/lancer-es-cj",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "mitsubishi_lancer_es_petrol_auto_sedan_cj",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "ES Sport CJ"},
        {**base_row, "variant": "LX CJ"},
        {**base_row, "body_type": "Hatchback"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "variant": "ES CF", "year": "2016"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "mitsubishi_lancer_es_petrol_auto_sedan_cj"
        )


def test_tiguan_132tsi_pacific_5n_stays_badge_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Volkswagen",
        "model": "Tiguan",
        "variant": "132TSI Pacific 5N",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "10000",
        "url": "https://example.test/tiguan-132tsi-pacific-5n",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "volkswagen_tiguan_132tsi-pacific_petrol_auto_wagon_5n",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "132TSI Comfortline 5N"},
        {**base_row, "variant": "125TSI 5N"},
        {**base_row, "variant": "103TDI Pacific 5N", "fuel_type": "Diesel"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "variant": "132TSI Comfortline MK2", "year": "2018"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "volkswagen_tiguan_132tsi-pacific_petrol_auto_wagon_5n"
        )


def test_outback_25i_b5a_auto_petrol_stays_base_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Subaru",
        "model": "Outback",
        "variant": "2.5i B5A",
        "body_type": "Wagon",
        "transmission": "CVT",
        "fuel_type": "Petrol",
        "year": "2012",
        "price": "9000",
        "url": "https://example.test/outback-25i-b5a",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "subaru_outback_2.5i_petrol_auto_wagon_b5a",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "2.5i Premium B5A"},
        {**base_row, "variant": "3.6R B5A"},
        {**base_row, "variant": "2.5i B6A", "year": "2016"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "subaru_outback_2.5i_petrol_auto_wagon_b5a"
        )


def test_holden_sportwagon_omega_ve_alias_uses_existing_wagon_curve():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Sportwagon",
        "variant": "Omega VE",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2009",
        "price": "6000",
        "url": "https://example.test/holden-sportwagon-omega-ve",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_sportwagon_omega_petrol_auto_wagon_ve",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "variant": "Omega VE Series II", "year": "2012"},
        require_price=True,
    )[0:2] == (
        "holden_sportwagon_omega_petrol_auto_wagon_ve-series-ii",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "SV6 VE"},
        {**base_row, "body_type": "Sedan"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "LPG"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "holden_sportwagon_omega_petrol_auto_wagon_ve"
        )


def test_honda_civic_vti_8th_gen_stays_exact_lane_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Honda",
        "model": "Civic",
        "variant": "VTi 8th Gen",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2008",
        "price": "7000",
        "url": "https://example.test/honda-civic-vti-8th-gen",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "honda_civic_vti_petrol_auto_sedan_8th-gen",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "VTi-L 8th Gen"},
        {**base_row, "variant": "VTi 9th Gen", "year": "2013"},
        {**base_row, "body_type": "Hatchback"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Hybrid"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "honda_civic_vti_petrol_auto_sedan_8th-gen"
        )


def test_holden_sportwagon_sv6_aliases_use_existing_wagon_curves():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Holden",
        "model": "Sportwagon",
        "variant": "SV6 VE",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2010",
        "price": "7000",
        "url": "https://example.test/holden-sportwagon-sv6",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "holden_sportwagon_sv6_petrol_auto_wagon_ve",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "variant": "SV6 VE Series II", "year": "2012"},
        require_price=True,
    )[0:2] == (
        "holden_sportwagon_sv6_petrol_auto_wagon_ve-series-ii",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "variant": "SV6 VF", "year": "2015"},
        require_price=True,
    )[0:2] == (
        "holden_sportwagon_sv6_petrol_auto_wagon_vf",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Omega VE"},
        {**base_row, "body_type": "Sedan"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "LPG"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "holden_sportwagon_sv6_petrol_auto_wagon_ve"
        )


def test_ford_focus_ambiente_lw_mkii_stays_hatch_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Ford",
        "model": "Focus",
        "variant": "Ambiente LW II",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "6500",
        "url": "https://example.test/focus-ambiente-lw-mkii",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "ford_focus_ambiente_petrol_auto_hatch_lw-mkii",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Trend LW II"},
        {**base_row, "body_type": "Sedan"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "variant": "Ambiente LZ", "year": "2016"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "ford_focus_ambiente_petrol_auto_hatch_lw-mkii"
        )


def test_audi_q5_30_tdi_8r_stays_engine_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Audi",
        "model": "Q5",
        "variant": "3.0 TDI quattro 8R",
        "body_type": "SUV",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2013",
        "price": "12000",
        "url": "https://example.test/audi-q5-30-tdi-8r",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "audi_q5_3.0-tdi-quattro_diesel_auto_suv_8r",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "2.0 TDI quattro 8R"},
        {**base_row, "variant": "2.0 TFSI quattro 8R", "fuel_type": "Petrol"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "variant": "50 TDI quattro FY", "year": "2019"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "audi_q5_3.0-tdi-quattro_diesel_auto_suv_8r"
        )


def test_tiguan_103tdi_5n_stays_base_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Volkswagen",
        "model": "Tiguan",
        "variant": "103 TDI 5N",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2011",
        "price": "7000",
        "url": "https://example.test/tiguan-103tdi-5n",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "volkswagen_tiguan_103tdi_diesel_auto_wagon_5n",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "103TDI Pacific 5N"},
        {**base_row, "variant": "125TSI 5N", "fuel_type": "Petrol"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "variant": "110TDI MK2", "year": "2018"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "volkswagen_tiguan_103tdi_diesel_auto_wagon_5n"
        )


def test_bmw_320i_executive_e90_accepts_both_grays_model_encodings():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "BMW",
        "model": "3",
        "variant": "20i Executive E90",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2009",
        "price": "8000",
        "url": "https://example.test/bmw-320i-executive-e90",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "bmw_3_20i-executive_petrol_auto_sedan_e90",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "model": "320i", "variant": "320i Exec. E90"},
        require_price=True,
    )[0:2] == (
        "bmw_320i_executive_petrol_auto_sedan_e90",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "variant": "Series 320i Exec. E90", "year": "2010"},
        require_price=True,
    )[0:2] == (
        "bmw_3_series-320i-exec_petrol_auto_sedan_e90",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "20d Executive E90", "fuel_type": "Diesel"},
        {**base_row, "variant": "20i Executive F30", "year": "2013"},
        {**base_row, "body_type": "Coupe"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "bmw_3_20i-executive_petrol_auto_sedan_e90"
        )


def test_bmw_320i_executive_e90_final_year_is_covered_but_f30_year_is_not():
    _load_curve_year_band.cache_clear()
    base = {
        "make": "BMW",
        "model": "3",
        "variant": "Series 320i Exec. E90",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "price": "5000",
        "url": "https://example.test/bmw-e90-final-year",
    }
    assert assign_canonical_tag(
        {**base, "year": "2011"}, require_price=True
    )[0:2] == (
        "bmw_3_series-320i-exec_petrol_auto_sedan_e90",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base, "year": "2012"}, require_price=True
    )[0] == "UNCLASSIFIED"


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("Classic", "mazda_cx-7_classic_petrol_auto_wagon_er-series-2"),
        ("Luxury Sports (4X4)", "mazda_cx-7_luxury-sports_petrol_auto_wagon_er-series-2"),
    ],
)
def test_mazda_cx7_er_series_2_lanes_are_trim_specific(variant, expected):
    _load_curve_year_band.cache_clear()
    row = {
        "make": "Mazda", "model": "CX-7", "variant": variant,
        "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Petrol",
        "year": "2010", "price": "10000", "url": "https://example.test/cx7-er2",
    }
    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected, "[OK]")
    assert assign_canonical_tag({**row, "transmission": "Manual"}, require_price=True)[0] == "UNCLASSIFIED"


def test_jeep_grand_cherokee_laredo_wk_requires_explicit_4x4():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Jeep",
        "model": "Grand",
        "variant": "Cherokee Laredo (4x4) WK",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "12000",
        "url": "https://example.test/jeep-grand-cherokee-laredo-wk-4x4",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "jeep_grand_cherokee-laredo-4x4_petrol_auto_wagon_wk",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Cherokee Laredo WK"},
        {**base_row, "variant": "Cherokee Laredo (4x2) WK"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "variant": "Cherokee Limited (4x4) WK"},
        {**base_row, "variant": "Cherokee Laredo (4x4) WH", "year": "2008"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "jeep_grand_cherokee-laredo-4x4_petrol_auto_wagon_wk"
        )


def test_mazda_cx9_grand_touring_tb_stays_trim_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mazda",
        "model": "CX-9",
        "variant": "Grand Touring",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "12000",
        "url": "https://example.test/mazda-cx9-grand-touring-tb",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "mazda_cx-9_grand-touring_petrol_auto_wagon_tb",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Luxury"},
        {**base_row, "variant": "Classic"},
        {**base_row, "variant": "Grand Touring TC", "year": "2018"},
        {**base_row, "transmission": "Manual"},
        {**base_row, "fuel_type": "Diesel"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "mazda_cx-9_grand-touring_petrol_auto_wagon_tb"
        )


def test_hyundai_i20_active_pb_stays_manual_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Hyundai",
        "model": "i20",
        "variant": "Active PB",
        "body_type": "Hatchback",
        "transmission": "Manual",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "7000",
        "url": "https://example.test/hyundai-i20-active-pb",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "hyundai_i20_active_petrol_manual_hatch_pb",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "transmission": "Automatic"},
        {**base_row, "variant": "Elite PB"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "variant": "Active BC3", "year": "2021"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "hyundai_i20_active_petrol_manual_hatch_pb"
        )


def test_dodge_journey_sxt_curve_is_later_engine_year_band_only():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Dodge",
        "model": "Journey",
        "variant": "SXT",
        "body_type": "People Mover",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "7000",
        "url": "https://example.test/dodge-journey-sxt",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "dodge_journey_sxt_petrol_auto_people-mover",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "year": "2010"}, require_price=True
    )[0:2] == ("UNCLASSIFIED", "[OUT_OF_SCOPE_YEAR]")
    for changed_row in [
        {**base_row, "variant": "R/T"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "dodge_journey_sxt_petrol_auto_people-mover"
        )


def test_dodge_journey_rt_curve_is_later_engine_year_band_only():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Dodge",
        "model": "Journey",
        "variant": "R/T",
        "body_type": "People Mover",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2014",
        "price": "9000",
        "url": "https://example.test/dodge-journey-rt",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "dodge_journey_rt_petrol_auto_people-mover",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "year": "2010"}, require_price=True
    )[0:2] == ("UNCLASSIFIED", "[OUT_OF_SCOPE_YEAR]")
    for changed_row in [
        {**base_row, "variant": "SXT"},
        {**base_row, "fuel_type": "Diesel"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "dodge_journey_rt_petrol_auto_people-mover"
        )


def test_mercedes_c250_be_avantgarde_w204_stays_powertrain_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Mercedes",
        "model": "Benz",
        "variant": "C250 BE Avantgarde W204",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2010",
        "price": "12000",
        "url": "https://example.test/mercedes-c250-be-avantgarde-w204",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "mercedes_benz_c250-be-avantgarde_petrol_auto_sedan_w204",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "C250 CDI Avantgarde W204", "fuel_type": "Diesel"},
        {**base_row, "variant": "C200 BE Avantgarde W204"},
        {**base_row, "body_type": "Wagon"},
        {**base_row, "variant": "C250 Avantgarde W205", "year": "2015"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "mercedes_benz_c250-be-avantgarde_petrol_auto_sedan_w204"
        )


def test_bmw_118i_f20_curve_excludes_later_engine_years():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "BMW",
        "model": "1",
        "variant": "Series 118i F20",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "12000",
        "url": "https://example.test/bmw-118i-f20",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "bmw_1_series-118i_petrol_auto_hatch_f20",
        "[OK]",
    )
    assert assign_canonical_tag(
        {**base_row, "year": "2015"}, require_price=True
    )[0:2] == ("UNCLASSIFIED", "[OUT_OF_SCOPE_YEAR]")
    for changed_row in [
        {**base_row, "variant": "Series 118d F20", "fuel_type": "Diesel"},
        {**base_row, "variant": "Series 116i F20"},
        {**base_row, "body_type": "Coupe"},
        {**base_row, "variant": "Series 118i F40", "year": "2021"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "bmw_1_series-118i_petrol_auto_hatch_f20"
        )


def test_evoque_td4_150_se_9_stays_output_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Land",
        "model": "Rover",
        "variant": "Range Rover Evoque TD4 150 SE 9",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Diesel",
        "year": "2016",
        "price": "19000",
        "url": "https://example.test/evoque-td4-150-se-9",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "land_rover_range-rover-evoque-td4-150-se_diesel_auto_wagon_9",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "Range Rover Evoque TD4 150 Pure 9"},
        {**base_row, "variant": "Range Rover Evoque SD4 Dynamic 9"},
        {**base_row, "fuel_type": "Petrol"},
        {**base_row, "variant": "Range Rover Evoque D150 SE L551", "year": "2020"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "land_rover_range-rover-evoque-td4-150-se_diesel_auto_wagon_9"
        )


def test_bmw_118i_e87_grays_wording_stays_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "BMW",
        "model": "1",
        "variant": "18i E87",
        "body_type": "Hatchback",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2008",
        "price": "7000",
        "url": "https://example.test/bmw-118i-e87",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "bmw_1_18i_petrol_auto_hatch_e87",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "18d E87", "fuel_type": "Diesel"},
        {**base_row, "variant": "20i E87"},
        {**base_row, "body_type": "Coupe"},
        {**base_row, "variant": "Series 118i F20", "year": "2013"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "bmw_1_18i_petrol_auto_hatch_e87"
        )


def test_audi_q3_20_tfsi_quattro_8u_stays_engine_and_generation_specific():
    _load_curve_year_band.cache_clear()
    base_row = {
        "make": "Audi",
        "model": "Q3",
        "variant": "2.0 TFSI quattro 8U",
        "body_type": "Wagon",
        "transmission": "Automatic",
        "fuel_type": "Petrol",
        "year": "2013",
        "price": "12000",
        "url": "https://example.test/audi-q3-20-tfsi-quattro-8u",
    }

    assert assign_canonical_tag(base_row, require_price=True)[0:2] == (
        "audi_q3_2.0-tfsi-quattro_petrol_auto_wagon_8u",
        "[OK]",
    )
    for changed_row in [
        {**base_row, "variant": "1.4 TFSI 8U"},
        {**base_row, "variant": "2.0 TDI quattro 8U", "fuel_type": "Diesel"},
        {**base_row, "variant": "RS Q3 8U"},
        {**base_row, "variant": "40 TFSI quattro 8Y", "year": "2021"},
        {**base_row, "transmission": "Manual"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] != (
            "audi_q3_2.0-tfsi-quattro_petrol_auto_wagon_8u"
        )


def test_honda_accord_euro_luxury_7th_gen_handles_both_grays_encodings():
    _load_curve_year_band.cache_clear()
    accord_euro_row = {
        "make": "Honda",
        "model": "Accord Euro",
        "variant": "Luxury",
        "body_type": "Sedan",
        "transmission": "Automatic",
        "fuel_type": "Premium",
        "year": "2006",
        "price": "7000",
        "url": "https://example.test/honda-accord-euro-luxury",
    }
    accord_row = {
        **accord_euro_row,
        "model": "Accord",
        "variant": "EURO LUXURY",
    }

    assert assign_canonical_tag(accord_euro_row, require_price=True)[0:2] == (
        "honda_accord-euro_luxury_petrol_auto_sedan_7th-gen",
        "[OK]",
    )
    assert assign_canonical_tag(accord_row, require_price=True)[0:2] == (
        "honda_accord_euro-luxury_petrol_auto_sedan_7th-gen",
        "[OK]",
    )
    for changed_row in [
        {**accord_euro_row, "variant": "Luxury Navi"},
        {**accord_euro_row, "transmission": "Manual"},
        {**accord_euro_row, "year": "2011"},
        {**accord_row, "variant": "V6 Luxury"},
    ]:
        assert assign_canonical_tag(changed_row, require_price=True)[0] not in {
            "honda_accord-euro_luxury_petrol_auto_sedan_7th-gen",
            "honda_accord_euro-luxury_petrol_auto_sedan_7th-gen",
        }


@pytest.mark.parametrize(
    ("make", "model", "variant", "body", "fuel", "year", "expected_tag"),
    [
        ("Mitsubishi", "ASX", "Ls (2Wd)", "Wagon", "Unleaded", 2015, "mitsubishi_asx_ls_petrol_auto_wagon_xb"),
        ("Toyota", "Hiace", "Gdh320r", "Bus", "Diesel", 2021, "toyota_hiace_slwb-commuter_diesel_auto_bus_h300"),
    ],
)
def test_bulk_grays_demand_lanes_are_generation_specific(
    make, model, variant, body, fuel, year, expected_tag
):
    _load_curve_year_band.cache_clear()
    row = {
        "make": make,
        "model": model,
        "variant": variant,
        "body_type": body,
        "transmission": "Automatic",
        "fuel_type": fuel,
        "year": str(year),
        "price": "20000",
        "url": f"https://example.test/{make}/{model}/{variant}/{year}",
    }
    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")


@pytest.mark.parametrize(
    "row",
    [
        {"make": "Mazda", "model": "CX-3", "variant": "Maxx (Awd)", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Unleaded", "year": "2017"},
        {"make": "Toyota", "model": "Landcruiser Prado", "variant": "Gxl (4X4)", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Diesel", "year": "2015"},
        {"make": "Kia", "model": "Sorento", "variant": "Gt-Line (4X4)", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Unleaded", "year": "2018"},
        {"make": "Kia", "model": "Carnival", "variant": "S", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Diesel", "year": "2019"},
        {"make": "Hyundai", "model": "Santa Fe", "variant": "Highlander Hev (6 Seat)", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Hybrid", "year": "2022"},
        {"make": "Mitsubishi", "model": "ASX", "variant": "Es Adas (2Wd)", "body_type": "Wagon", "transmission": "Automatic", "fuel_type": "Unleaded", "year": "2021"},
    ],
)
def test_bulk_grays_demand_lanes_reject_adjacent_powertrains_and_trims(row):
    _load_curve_year_band.cache_clear()
    row = {**row, "price": "20000", "url": "https://example.test/bulk-negative"}
    new_tags = {
        "mazda_cx3_maxx_petrol_auto_wagon_dk",
        "toyota_landcruiserprado_gxl_diesel_auto_wagon_150-2.8",
        "kia_sorento_gt-line_diesel_auto_wagon_um",
        "kia_carnival_s_diesel_auto_people-mover_ka4",
        "hyundai_santafe_highlander-crdi_diesel_auto_wagon_tmfl",
        "mitsubishi_asx_es_petrol_auto_wagon_xd",
    }
    assert assign_canonical_tag(row, require_price=True)[0] not in new_tags


@pytest.mark.parametrize(
    ("make", "model", "variant", "body", "fuel", "year", "expected_tag"),
    [
        ("Mazda", "2", "Neo", "Hatchback", "Unleaded", 2011, "mazda_2_neo_petrol_auto_hatch_de"),
        ("Hyundai", "Kona", "Active (Fwd)", "Wagon", "Unleaded", 2019, "hyundai_kona_active_petrol_auto_wagon_os"),
        ("Nissan", "QASHQAI", "Ti (4X2)", "Wagon", "Unleaded", 2016, "nissan_qashqai_ti_petrol_auto_wagon_j11"),
        ("MG", "MG3", "Core", "Hatchback", "Unleaded", 2021, "mg_mg3_core_petrol_auto_hatch_szp1"),
    ],
)
def test_second_bulk_grays_demand_lanes_match_exact_generation(
    make, model, variant, body, fuel, year, expected_tag
):
    _load_curve_year_band.cache_clear()
    row = {
        "make": make,
        "model": model,
        "variant": variant,
        "body_type": body,
        "transmission": "Automatic",
        "fuel_type": fuel,
        "year": str(year),
        "price": "25000",
        "url": f"https://example.test/second-bulk/{model}/{variant}/{year}",
    }
    assert assign_canonical_tag(row, require_price=True)[0:2] == (expected_tag, "[OK]")
