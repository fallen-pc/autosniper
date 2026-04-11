from __future__ import annotations

from pathlib import Path

import pandas as pd

from shared.curve_seed_rows import build_legacy_curve_seed_rows, summarize_legacy_curve_conflicts
from shared.curve_groups_v2 import (
    get_anchor_override_years,
    get_supported_curve_row,
    list_supported_base_curve_tags,
    load_curve_anchor_overrides_v2,
    load_curve_groups_v2,
    load_supported_curve_universe_v1,
    resolve_base_curve_tag,
    tags_for_base_curve,
)


def test_resolve_base_curve_tag_uses_group_mapping(tmp_path: Path):
    groups_path = tmp_path / "curve_groups_v2.csv"
    groups_path.write_text(
        "match_tag,base_curve_tag,group_status,reason\n"
        "mazda_3_maxx_petrol_auto_hatch_bl,mazda_3_bl_hatch_auto_petrol,active,merge\n",
        encoding="utf-8",
    )

    groups_df = load_curve_groups_v2(groups_path)

    assert resolve_base_curve_tag("mazda_3_maxx_petrol_auto_hatch_bl", groups_df) == "mazda_3_bl_hatch_auto_petrol"
    assert resolve_base_curve_tag("unknown_tag", groups_df) == "unknown_tag"


def test_tags_for_base_curve_returns_all_source_tags(tmp_path: Path):
    groups_path = tmp_path / "curve_groups_v2.csv"
    groups_path.write_text(
        "match_tag,base_curve_tag,group_status,reason\n"
        "mazda_3_neo_petrol_auto_hatch_bl,mazda_3_bl_hatch_auto_petrol,active,merge\n"
        "mazda_3_maxx_petrol_auto_hatch_bl,mazda_3_bl_hatch_auto_petrol,active,merge\n",
        encoding="utf-8",
    )

    groups_df = load_curve_groups_v2(groups_path)

    assert tags_for_base_curve("mazda_3_bl_hatch_auto_petrol", groups_df) == [
        "mazda_3_maxx_petrol_auto_hatch_bl",
        "mazda_3_neo_petrol_auto_hatch_bl",
    ]


def test_list_supported_base_curve_tags_filters_by_status(tmp_path: Path):
    universe_path = tmp_path / "supported_curve_universe_v1.csv"
    universe_path.write_text(
        "base_curve_tag,make,model,body,fuel,transmission,series,status,priority,notes\n"
        "toyota_corolla_zre152r_sedan_auto_petrol,toyota,corolla,sedan,petrol,auto,zre152r,live_now,1,ok\n"
        "toyota_camry_asv70r_sedan_auto_petrol,toyota,camry,sedan,petrol,auto,asv70r,hold,2,hold\n",
        encoding="utf-8",
    )

    supported_df = load_supported_curve_universe_v1(universe_path)

    assert list_supported_base_curve_tags(statuses=["live_now"], supported_df=supported_df) == [
        "toyota_corolla_zre152r_sedan_auto_petrol"
    ]
    assert list_supported_base_curve_tags(supported_df=supported_df) == [
        "toyota_corolla_zre152r_sedan_auto_petrol",
        "toyota_camry_asv70r_sedan_auto_petrol",
    ]


def test_get_supported_curve_row_returns_metadata(tmp_path: Path):
    universe_path = tmp_path / "supported_curve_universe_v1.csv"
    universe_path.write_text(
        "base_curve_tag,make,model,body,fuel,transmission,series,status,priority,notes\n"
        "hyundai_i30_gd_hatch_auto_petrol,hyundai,i30,hatch,petrol,auto,gd,live_now,1,Core i30 GD Active hatch\n",
        encoding="utf-8",
    )

    supported_df = load_supported_curve_universe_v1(universe_path)
    row = get_supported_curve_row("hyundai_i30_gd_hatch_auto_petrol", supported_df)

    assert row["make"] == "hyundai"
    assert row["model"] == "i30"
    assert row["status"] == "live_now"


def test_get_anchor_override_years_returns_configured_years(tmp_path: Path):
    overrides_path = tmp_path / "curve_anchor_overrides_v2.csv"
    overrides_path.write_text(
        "base_curve_tag,anchor_years,notes\n"
        "hyundai_i30_gd_hatch_auto_petrol,2012|2014|2016,active rebuild\n",
        encoding="utf-8",
    )

    overrides_df = load_curve_anchor_overrides_v2(overrides_path)

    assert get_anchor_override_years("hyundai_i30_gd_hatch_auto_petrol", overrides_df) == [2012, 2014, 2016]
    assert get_anchor_override_years("unknown_tag", overrides_df) == []


def test_get_anchor_override_years_returns_pd_active_years(tmp_path: Path):
    overrides_path = tmp_path / "curve_anchor_overrides_v2.csv"
    overrides_path.write_text(
        "base_curve_tag,anchor_years,notes\n"
        "hyundai_i30_pd_hatch_auto_petrol,2017|2019|2022,pd active rebuild\n",
        encoding="utf-8",
    )

    overrides_df = load_curve_anchor_overrides_v2(overrides_path)

    assert get_anchor_override_years("hyundai_i30_pd_hatch_auto_petrol", overrides_df) == [2017, 2019, 2022]


def test_build_legacy_curve_seed_rows_blocks_conflicting_legacy_rows():
    curves_df = pd.DataFrame(
        [
            {
                "canonical_tag": "toyota_corolla_ascent_petrol_auto_hatch_zre18x",
                "anchor_year": 2018,
                "km_bucket": 30000,
                "price_low": 21000,
                "price_mid": 22500,
                "price_high": 24000,
            },
            {
                "canonical_tag": "toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x",
                "anchor_year": 2018,
                "km_bucket": 30000,
                "price_low": 21900,
                "price_mid": 23400,
                "price_high": 24900,
            },
            {
                "canonical_tag": "toyota_corolla_ascent_petrol_auto_hatch_zre18x",
                "anchor_year": 2017,
                "km_bucket": 30000,
                "price_low": 19000,
                "price_mid": 20500,
                "price_high": 22000,
            },
        ]
    )

    seed_rows, conflict_rows = build_legacy_curve_seed_rows(
        base_curve_tag="toyota_corolla_zre182r_hatch_auto_petrol",
        curves_df=curves_df,
        member_tags=[
            "toyota_corolla_ascent_petrol_auto_hatch_zre18x",
            "toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x",
        ],
    )

    assert seed_rows.empty
    assert len(conflict_rows) == 2
    assert conflict_rows["source_tag"].tolist() == [
        "toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x",
        "toyota_corolla_ascent_petrol_auto_hatch_zre18x",
    ]

    summary_df = summarize_legacy_curve_conflicts(conflict_rows)
    assert len(summary_df) == 1
    assert summary_df.iloc[0]["anchor_year"] == 2018
    assert summary_df.iloc[0]["km_bucket"] == 30000
    assert summary_df.iloc[0]["lowest_mid_source_tag"] == "toyota_corolla_ascent_petrol_auto_hatch_zre18x"
    assert summary_df.iloc[0]["highest_mid_source_tag"] == "toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x"
    assert summary_df.iloc[0]["mid_gap"] == 900


def test_build_legacy_curve_seed_rows_allows_identical_duplicate_rows():
    curves_df = pd.DataFrame(
        [
            {
                "canonical_tag": "toyota_corolla_ascent_petrol_auto_hatch_zre18x",
                "anchor_year": 2018,
                "km_bucket": 30000,
                "price_low": 21000,
                "price_mid": 22500,
                "price_high": 24000,
            },
            {
                "canonical_tag": "toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x",
                "anchor_year": 2018,
                "km_bucket": 30000,
                "price_low": 21000,
                "price_mid": 22500,
                "price_high": 24000,
            },
        ]
    )

    seed_rows, conflict_rows = build_legacy_curve_seed_rows(
        base_curve_tag="toyota_corolla_zre182r_hatch_auto_petrol",
        curves_df=curves_df,
        member_tags=[
            "toyota_corolla_ascent_petrol_auto_hatch_zre18x",
            "toyota_corolla_ascent-sport_petrol_auto_hatch_zre18x",
        ],
    )

    assert conflict_rows.empty
    assert len(seed_rows) == 1
    assert seed_rows.iloc[0]["canonical_tag"] == "toyota_corolla_zre182r_hatch_auto_petrol"
