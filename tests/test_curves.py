import unittest

import pandas as pd

import shared.curves as curves
import shared.curve_groups_v2 as curve_groups_v2
from shared.curves import interpolate_base_by_year, interpolate_price_by_km


STANDARD_KM_BUCKETS = {30000, 60000, 100000, 150000, 200000}
ALLOWED_EXTENSION_KM_BUCKETS = {225000, 300000}


def _assert_saved_base_curve_only(curves_df, base_tag, matcher_tag, expected_anchor_years):
    base_rows = curves_df[curves_df["canonical_tag"].astype(str) == base_tag]
    matcher_rows = curves_df[curves_df["canonical_tag"].astype(str) == matcher_tag]

    assert not base_rows.empty
    assert base_rows["anchor_year"].nunique() == expected_anchor_years
    _assert_standard_grid_with_known_extensions(base_rows)
    assert matcher_rows.empty


def _assert_standard_grid_with_known_extensions(curve_rows):
    allowed_buckets = STANDARD_KM_BUCKETS | ALLOWED_EXTENSION_KM_BUCKETS

    for anchor_year, year_rows in curve_rows.groupby("anchor_year"):
        buckets = set(year_rows["km_bucket"].astype(int).tolist())
        assert STANDARD_KM_BUCKETS <= buckets, int(anchor_year)
        assert buckets <= allowed_buckets, (int(anchor_year), sorted(buckets - allowed_buckets))


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

    def test_km_within_curve_coverage_allows_small_high_km_overage(self) -> None:
        self.assertTrue(curves.km_within_curve_coverage(309209, 30000, 300000))
        self.assertFalse(curves.km_within_curve_coverage(325000, 30000, 300000))


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


def test_saved_curves_do_not_duplicate_v2_matcher_rows_when_base_exists():
    curves_df = curves.load_curves()
    groups_df = curve_groups_v2.load_curve_groups_v2()
    saved_tags = set(curves_df["canonical_tag"].astype(str))

    duplicates = []
    for _, row in groups_df.iterrows():
        match_tag = str(row.get("match_tag", "")).strip()
        base_tag = str(row.get("base_curve_tag", "")).strip()
        if match_tag and base_tag and match_tag != base_tag and base_tag in saved_tags and match_tag in saved_tags:
            duplicates.append(f"{match_tag} -> {base_tag}")

    assert duplicates == []


def test_live_supported_curves_have_complete_standard_grid():
    curves_df = curves.load_curves()
    supported_df = curve_groups_v2.load_supported_curve_universe_v1()
    live_base_tags = set(
        supported_df.loc[
            supported_df["status"].astype(str) == "live_now",
            "base_curve_tag",
        ].astype(str)
    )
    saved_tags = set(curves_df["canonical_tag"].astype(str))

    assert live_base_tags <= saved_tags
    assert saved_tags <= set(supported_df["base_curve_tag"].astype(str))

    for curve_tag in sorted(live_base_tags):
        curve_rows = curves_df[curves_df["canonical_tag"].astype(str) == curve_tag]
        _assert_standard_grid_with_known_extensions(curve_rows)


def test_saved_curve_price_bands_are_ordered_and_decline_with_km():
    curves_df = curves.load_curves()

    assert (curves_df["price_low"] <= curves_df["price_mid"]).all()
    assert (curves_df["price_mid"] <= curves_df["price_high"]).all()

    for (curve_tag, anchor_year), year_rows in curves_df.sort_values("km_bucket").groupby(
        ["canonical_tag", "anchor_year"]
    ):
        mids = year_rows["price_mid"].astype(float).tolist()
        assert all(left >= right for left, right in zip(mids, mids[1:])), (
            curve_tag,
            int(anchor_year),
            mids,
        )


def test_mzea12r_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "toyota_corolla_mzea12r_hatch_auto_petrol",
        "toyota_corolla_ascent-sport_petrol_auto_hatch_mzea12r",
        expected_anchor_years=3,
    )


def test_cx5_ke_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "mazda_cx5_maxx-sport_ke_wagon_auto_diesel",
        "mazda_cx5_maxx-sport_diesel_auto_wagon_ke",
        expected_anchor_years=3,
    )


def test_ix35_se_lm_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "hyundai_ix35_se_lm_wagon_auto_petrol",
        "hyundai_ix35_se_petrol_auto_wagon_lm",
        expected_anchor_years=3,
    )


def test_ix35_elite_lm_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "hyundai_ix35_elite_lm_wagon_auto_petrol",
        "hyundai_ix35_elite_petrol_auto_wagon_lm",
        expected_anchor_years=3,
    )


def test_getz_sx_tb_auto_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "hyundai_getz_sx_tb_hatch_auto_petrol",
        "hyundai_getz_sx_petrol_auto_hatch_tb",
        expected_anchor_years=3,
    )


def test_getz_sx_tb_manual_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "hyundai_getz_sx_tb_hatch_manual_petrol",
        "hyundai_getz_sx_petrol_manual_hatch_tb",
        expected_anchor_years=3,
    )


def test_axvh71r_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "toyota_camry_axvh71r_sedan_auto_hybrid",
        "toyota_camry_ascent_hybrid_auto_sedan_axvh71r",
        expected_anchor_years=4,
    )


def test_camry_ascent_sport_axvh71r_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "toyota_camry_ascent-sport_axvh71r_sedan_auto_hybrid",
        "toyota_camry_ascent-sport_hybrid_auto_sedan_axvh71r",
        expected_anchor_years=3,
    )


def test_camry_asv70r_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "toyota_camry_asv70r_sedan_auto_petrol",
        "toyota_camry_ascent_petrol_auto_sedan_asv70r",
        expected_anchor_years=3,
    )


def test_camry_asv50r_saved_curve_resolves_through_v2_base_tag():
    curves_df = curves.load_curves()

    _assert_saved_base_curve_only(
        curves_df,
        "toyota_camry_asv50r_sedan_auto_petrol",
        "toyota_camry_altise_petrol_auto_sedan_asv50r",
        expected_anchor_years=3,
    )
