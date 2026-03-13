from __future__ import annotations

import pandas as pd

from shared.curve_versioning import snapshot_curve_version


def test_snapshot_curve_version_is_idempotent_for_same_curve_file(tmp_path):
    curves_path = tmp_path / "curves.csv"
    pd.DataFrame(
        [
            {
                "canonical_tag": "demo_tag",
                "anchor_year": 2021,
                "km_bucket": 50000,
                "price_low": 10000,
                "price_mid": 11000,
                "price_high": 12000,
            }
        ]
    ).to_csv(curves_path, index=False)

    snapshot_one = snapshot_curve_version(curves_path, source="test", change_summary="initial")
    snapshot_two = snapshot_curve_version(curves_path, source="test", change_summary="repeat")

    manifest_path = tmp_path / "versions" / "curves_manifest.csv"
    manifest_df = pd.read_csv(manifest_path)

    assert snapshot_one is not None
    assert snapshot_two == snapshot_one
    assert snapshot_one.exists()
    assert len(manifest_df) == 1
    assert manifest_df.iloc[0]["source"] == "test"
