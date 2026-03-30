from __future__ import annotations

from pathlib import Path

import pandas as pd

import shared.curve_groups_v2 as curve_groups_v2
from shared.ops_utils import build_curve_meta


def test_build_curve_meta_exposes_v2_match_tags_when_base_curve_exists(monkeypatch, tmp_path: Path):
    groups_path = tmp_path / "curve_groups_v2.csv"
    groups_path.write_text(
        "match_tag,base_curve_tag,group_status,reason\n"
        "mazda_3_neo_petrol_auto_hatch_bl,mazda_3_bl_hatch_auto_petrol,active,merge\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(curve_groups_v2, "CURVE_GROUPS_V2_PATH", groups_path)
    curve_groups_v2.load_curve_groups_v2.cache_clear()

    curves_df = pd.DataFrame(
        [
            {"canonical_tag": "mazda_3_bl_hatch_auto_petrol", "anchor_year": 2010, "km_bucket": 100000, "price_low": 9000, "price_mid": 10000, "price_high": 11000},
            {"canonical_tag": "mazda_3_bl_hatch_auto_petrol", "anchor_year": 2012, "km_bucket": 100000, "price_low": 11000, "price_mid": 12000, "price_high": 13000},
        ]
    )

    meta = build_curve_meta(curves_df)

    assert "mazda_3_neo_petrol_auto_hatch_bl" in meta
    assert meta["mazda_3_neo_petrol_auto_hatch_bl"].curve_source_tag == "mazda_3_bl_hatch_auto_petrol"
    curve_groups_v2.load_curve_groups_v2.cache_clear()
