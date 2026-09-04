from __future__ import annotations

import pandas as pd

from scripts import pipeline_stages


def test_audit_and_lock_schemas_migrates_identity_fields_across_materialized_views(
    monkeypatch, tmp_path
) -> None:
    paths = {
        "RAW_PATH": tmp_path / "raw_vehicle_data.csv",
        "NORMAL_PATH": tmp_path / "normalised_data.csv",
        "STATIC_PATH": tmp_path / "vehicle_static_details.csv",
        "MATCHED_PATH": tmp_path / "matched_canonical_details.csv",
        "UNMATCHED_PATH": tmp_path / "unmatched_canonical_details.csv",
        "ACTIVE_PATH": tmp_path / "active_vehicle_details.csv",
        "STATE_PATH": tmp_path / "vehicle_state.csv",
    }
    for name, path in paths.items():
        monkeypatch.setattr(pipeline_stages, name, path)
        pd.DataFrame([{"url": "https://example.test/rav4"}]).to_csv(path, index=False)

    reports = pipeline_stages.audit_and_lock_schemas()

    for dataset in (
        "raw_vehicle_data.csv",
        "normalised_data.csv",
        "vehicle_static_details.csv",
        "matched_canonical_details.csv",
        "unmatched_canonical_details.csv",
        "active_vehicle_details.csv",
    ):
        assert reports[dataset]["changed"] is True
        columns = pd.read_csv(tmp_path / dataset).columns.tolist()
        assert "series" in columns
        assert "drivetrain" in columns
