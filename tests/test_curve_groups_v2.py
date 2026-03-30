from __future__ import annotations

from pathlib import Path

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
        "hyundai_i30_gd_hatch_auto_petrol,hyundai,i30,hatch,petrol,auto,gd,live_now,1,Core i30 GD hatch\n",
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
        "hyundai_i30_gd_hatch_auto_petrol,2012|2014,early rebuild\n",
        encoding="utf-8",
    )

    overrides_df = load_curve_anchor_overrides_v2(overrides_path)

    assert get_anchor_override_years("hyundai_i30_gd_hatch_auto_petrol", overrides_df) == [2012, 2014]
    assert get_anchor_override_years("unknown_tag", overrides_df) == []
