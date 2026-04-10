from __future__ import annotations

import pandas as pd

import shared.canonical_tagging as ct


def test_curve_year_band_is_cached(monkeypatch, tmp_path):
    curves_path = tmp_path / "curves.csv"
    pd.DataFrame(
        [
            {"canonical_tag": "toyota_camry_ascent_petrol_auto_sedan_asv70r", "anchor_year": 2018},
            {"canonical_tag": "toyota_camry_ascent_petrol_auto_sedan_asv70r", "anchor_year": 2022},
        ]
    ).to_csv(curves_path, index=False)

    monkeypatch.setattr(
        ct,
        "dataset_path",
        lambda name: curves_path if name == "curves.csv" else tmp_path / name,
    )
    ct._load_curve_year_band.cache_clear()

    read_count = {"curves": 0}
    original_read_csv = ct.pd.read_csv

    def _counting_read_csv(*args, **kwargs):
        if args and str(args[0]) == str(curves_path):
            read_count["curves"] += 1
        return original_read_csv(*args, **kwargs)

    monkeypatch.setattr(ct.pd, "read_csv", _counting_read_csv)

    variant = ct.AllowedVariant(
        canonical_tag="toyota_camry_ascent_petrol_auto_sedan_asv70r",
        make="toyota",
        model="camry",
        body="sedan",
        fuel="petrol",
        transmission="auto",
        badge="ascent",
        series="asv70r",
        badge_aliases=("ascent",),
        body_aliases=("sedan",),
        excluded_keywords=(),
    )

    assert ct._year_in_any_band([variant], 2020) is True
    assert ct._year_in_any_band([variant], 2021) is True
    assert ct._disambiguate_by_year([variant], 2020) == variant
    assert read_count["curves"] == 1


def test_load_allowed_variants_preserves_explicit_canonical_tag(tmp_path):
    allowed_path = tmp_path / "allowed_variants.csv"
    allowed_path.write_text(
        "canonical_tag,make,model,body,fuel,transmission,badge,series,allowed_badge_aliases,allowed_body_aliases,excluded_keywords\n"
        "mazda_3_maxx-sport_petrol_auto_hatch_bl,mazda,3,hatch,petrol,auto,maxx sport,bl10f1,maxx sport|maxx-sport,hatch|hatchback,manual\n",
        encoding="utf-8",
    )

    variants = ct.load_allowed_variants(allowed_path)

    assert len(variants) == 1
    assert variants[0].canonical_tag == "mazda_3_maxx-sport_petrol_auto_hatch_bl"


def test_assign_canonical_tag_accepts_toyota_corolla_ascent_zre182r_early_series_match():
    ct._load_curve_year_band.cache_clear()
    row = {
        "url": "https://www.grays.com/lot/0001-21061929/motor-vehicles-motor-cycles/2013-toyota-corolla-ascent-zre182r-cvt-hatchback",
        "make": "Toyota",
        "model": "Corolla",
        "variant": "ascent zre182r",
        "body_type": "hatchback",
        "transmission": "cvt",
        "fuel_type": "petrol",
        "year": "2013",
        "price": "6000",
    }

    canonical_tag, canonical_reason, _drivetrain = ct.assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "toyota_corolla_ascent_petrol_auto_hatch_zre18x"
    assert canonical_reason == "[OK]"


def test_assign_canonical_tag_accepts_toyota_corolla_ascent_sport_zre182r_early_series_match():
    ct._load_curve_year_band.cache_clear()
    row = {
        "url": "https://www.grays.com/lot/0001-21050204/motor-vehicles-motor-cycles/2012-toyota-corolla-ascent-sport-zre182r-cvt-hatchback",
        "make": "Toyota",
        "model": "Corolla",
        "variant": "ascent sport zre182r",
        "body_type": "hatchback",
        "transmission": "cvt",
        "fuel_type": "petrol",
        "year": "2012",
        "price": "7000",
    }

    canonical_tag, canonical_reason, _drivetrain = ct.assign_canonical_tag(row, require_price=True)

    assert canonical_tag == "toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x"
    assert canonical_reason == "[OK]"
