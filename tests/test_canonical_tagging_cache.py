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
