import unittest

import pandas as pd

import shared.curves as curves
import shared.curve_groups_v2 as curve_groups_v2
from shared.curves import interpolate_base_by_year, interpolate_price_by_km


class CurveTests(unittest.TestCase):
    def test_interpolate_price_by_km(self) -> None:
        points = [(50000, 30000), (100000, 25000), (200000, 18000)]
        estimate = interpolate_price_by_km(points, 75000)
        self.assertAlmostEqual(estimate, 27500.0)

    def test_interpolate_base_by_year(self) -> None:
        df = pd.DataFrame(
            [
                {"canonical_tag": "demo", "anchor_year": 2018, "km_bucket": 100000, "price_mid": 20000},
                {"canonical_tag": "demo", "anchor_year": 2020, "km_bucket": 100000, "price_mid": 24000},
            ]
        )
        estimate = interpolate_base_by_year(df, "demo", 2019, 100000)
        self.assertAlmostEqual(estimate, 22000.0)


if __name__ == "__main__":
    unittest.main()


def test_interpolate_base_by_year_resolves_curve_alias(monkeypatch, tmp_path):
    alias_path = tmp_path / "curve_aliases.csv"
    alias_path.write_text(
        "canonical_tag,base_curve\n"
        "alias_tag,base_tag\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(curves, "CURVE_ALIASES_PATH", alias_path)
    curves.load_curve_aliases.cache_clear()

    df = pd.DataFrame(
        [
            {"canonical_tag": "base_tag", "anchor_year": 2018, "km_bucket": 100000, "price_mid": 20000},
            {"canonical_tag": "base_tag", "anchor_year": 2020, "km_bucket": 100000, "price_mid": 24000},
        ]
    )

    estimate = curves.interpolate_base_by_year(df, "alias_tag", 2019, 100000)

    assert estimate == 22000.0
    curves.load_curve_aliases.cache_clear()


def test_interpolate_base_by_year_prefers_v2_base_curve_when_saved(monkeypatch, tmp_path):
    groups_path = tmp_path / "curve_groups_v2.csv"
    groups_path.write_text(
        "match_tag,base_curve_tag,group_status,reason\n"
        "mazda_3_neo_petrol_auto_hatch_bl,mazda_3_bl_hatch_auto_petrol,active,merge\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(curve_groups_v2, "CURVE_GROUPS_V2_PATH", groups_path)
    curve_groups_v2.load_curve_groups_v2.cache_clear()

    df = pd.DataFrame(
        [
            {"canonical_tag": "mazda_3_bl_hatch_auto_petrol", "anchor_year": 2010, "km_bucket": 100000, "price_mid": 10000},
            {"canonical_tag": "mazda_3_bl_hatch_auto_petrol", "anchor_year": 2012, "km_bucket": 100000, "price_mid": 12000},
        ]
    )

    estimate = curves.interpolate_base_by_year(df, "mazda_3_neo_petrol_auto_hatch_bl", 2011, 100000)

    assert estimate == 11000.0
    curve_groups_v2.load_curve_groups_v2.cache_clear()


def test_interpolate_base_by_year_falls_back_to_legacy_curve_when_v2_base_not_saved(monkeypatch, tmp_path):
    groups_path = tmp_path / "curve_groups_v2.csv"
    groups_path.write_text(
        "match_tag,base_curve_tag,group_status,reason\n"
        "hyundai_i30_active_petrol_auto_hatch_gd,hyundai_i30_gd_hatch_auto_petrol,active,merge\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(curve_groups_v2, "CURVE_GROUPS_V2_PATH", groups_path)
    curve_groups_v2.load_curve_groups_v2.cache_clear()

    df = pd.DataFrame(
        [
            {"canonical_tag": "hyundai_i30_active_petrol_auto_hatch_gd", "anchor_year": 2013, "km_bucket": 100000, "price_mid": 9000},
            {"canonical_tag": "hyundai_i30_active_petrol_auto_hatch_gd", "anchor_year": 2015, "km_bucket": 100000, "price_mid": 11000},
        ]
    )

    estimate = curves.interpolate_base_by_year(df, "hyundai_i30_active_petrol_auto_hatch_gd", 2014, 100000)

    assert estimate == 10000.0
    curve_groups_v2.load_curve_groups_v2.cache_clear()


def test_list_curve_tags_includes_grouped_match_tags_when_base_curve_exists(monkeypatch, tmp_path):
    groups_path = tmp_path / "curve_groups_v2.csv"
    groups_path.write_text(
        "match_tag,base_curve_tag,group_status,reason\n"
        "mazda_3_neo_petrol_auto_hatch_bl,mazda_3_bl_hatch_auto_petrol,active,merge\n",
        encoding="utf-8",
    )
    alias_path = tmp_path / "curve_aliases.csv"
    alias_path.write_text("canonical_tag,base_curve\n", encoding="utf-8")

    monkeypatch.setattr(curve_groups_v2, "CURVE_GROUPS_V2_PATH", groups_path)
    monkeypatch.setattr(curves, "CURVE_ALIASES_PATH", alias_path)
    curve_groups_v2.load_curve_groups_v2.cache_clear()
    curves.load_curve_aliases.cache_clear()

    df = pd.DataFrame(
        [
            {"canonical_tag": "mazda_3_bl_hatch_auto_petrol", "anchor_year": 2010, "km_bucket": 100000, "price_mid": 10000},
        ]
    )

    tags = curves.list_curve_tags(df)

    assert "mazda_3_bl_hatch_auto_petrol" in tags
    assert "mazda_3_neo_petrol_auto_hatch_bl" in tags
    curve_groups_v2.load_curve_groups_v2.cache_clear()
    curves.load_curve_aliases.cache_clear()
