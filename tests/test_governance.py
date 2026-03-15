from __future__ import annotations

import pandas as pd

import shared.curves as curves
import shared.governance as gov
from shared.governance import DatasetContract


def test_validate_dataset_contracts_flags_schema_mismatch(monkeypatch, tmp_path):
    sample_path = tmp_path / "sample.csv"
    pd.DataFrame(columns=["a", "c"]).to_csv(sample_path, index=False)

    monkeypatch.setattr(
        gov,
        "DATASET_CONTRACTS",
        (DatasetContract("sample.csv", ("a", "b")),),
    )
    monkeypatch.setattr(
        gov,
        "dataset_path",
        lambda name: sample_path if name == "sample.csv" else tmp_path / name,
    )

    errors = gov.validate_dataset_contracts()

    assert len(errors) == 1
    assert "schema mismatch" in errors[0]
    assert "missing=['b']" in errors[0]


def test_validate_curve_table_rejects_upward_drift():
    curves_df = pd.DataFrame(
        [
            {
                "canonical_tag": "demo_tag",
                "anchor_year": 2020,
                "km_bucket": 50000,
                "price_low": 18000,
                "price_mid": 20000,
                "price_high": 22000,
            },
            {
                "canonical_tag": "demo_tag",
                "anchor_year": 2020,
                "km_bucket": 100000,
                "price_low": 18500,
                "price_mid": 20500,
                "price_high": 22500,
            },
        ]
    )

    errors = gov.validate_curve_table(curves_df)

    assert any("Curve drift detected" in error for error in errors)


def test_build_curve_monotonicity_report_tracks_year_reversals_as_warnings():
    curves_df = pd.DataFrame(
        [
            {
                "canonical_tag": "demo_tag",
                "anchor_year": 2020,
                "km_bucket": 50000,
                "price_low": 18000,
                "price_mid": 20000,
                "price_high": 22000,
            },
            {
                "canonical_tag": "demo_tag",
                "anchor_year": 2021,
                "km_bucket": 50000,
                "price_low": 17500,
                "price_mid": 19500,
                "price_high": 21500,
            },
        ]
    )

    report_df = gov.build_curve_monotonicity_report(curves_df)
    errors = gov.validate_curve_table(curves_df)

    assert len(errors) == 0
    assert not report_df.empty
    assert set(report_df["severity"]) == {"warning"}
    assert set(report_df["issue_type"]) == {"year_reversal"}


def test_build_curve_coverage_report_marks_missing_tags():
    static_df = pd.DataFrame(
        [
            {"canonical_tag": "tag_a"},
            {"canonical_tag": "tag_b"},
            {"canonical_tag": "UNCLASSIFIED"},
        ]
    )
    group_map_df = pd.DataFrame(
        [
            {"canonical_tag": "tag_b", "source": "active"},
            {"canonical_tag": "tag_c", "source": "sold"},
        ]
    )
    curves_df = pd.DataFrame(
        [
            {
                "canonical_tag": "tag_a",
                "anchor_year": 2022,
                "km_bucket": 50000,
                "price_low": 10000,
                "price_mid": 11000,
                "price_high": 12000,
            }
        ]
    )

    coverage_df = gov.build_curve_coverage_report(static_df, group_map_df, curves_df)

    tag_a = coverage_df.loc[coverage_df["canonical_tag"] == "tag_a"].iloc[0]
    tag_b = coverage_df.loc[coverage_df["canonical_tag"] == "tag_b"].iloc[0]
    tag_c = coverage_df.loc[coverage_df["canonical_tag"] == "tag_c"].iloc[0]

    assert bool(tag_a["has_curve"]) is True
    assert bool(tag_b["has_curve"]) is False
    assert int(tag_b["observed_rows"]) == 2
    assert int(tag_c["group_map_rows"]) == 1


def test_classify_dataset_deltas_respects_allowlist():
    report = gov.classify_dataset_deltas(
        [
            "CSV_data/restricted/curves.csv",
            "CSV_data/scrapers/sold_cars.csv",
            "README.md",
        ],
        allowed_patterns=["CSV_data/restricted/*"],
    )

    assert report["tracked"] == [
        "CSV_data/restricted/curves.csv",
        "CSV_data/scrapers/sold_cars.csv",
    ]
    assert report["allowed"] == ["CSV_data/restricted/curves.csv"]
    assert report["unexpected"] == ["CSV_data/scrapers/sold_cars.csv"]


def test_build_curve_coverage_report_marks_alias_tags_as_covered(monkeypatch, tmp_path):
    alias_path = tmp_path / "curve_aliases.csv"
    alias_path.write_text(
        "canonical_tag,base_curve\n"
        "tag_alias,tag_base\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(curves, "CURVE_ALIASES_PATH", alias_path)
    curves.load_curve_aliases.cache_clear()

    static_df = pd.DataFrame([{"canonical_tag": "tag_alias"}])
    group_map_df = pd.DataFrame()
    curves_df = pd.DataFrame(
        [
            {
                "canonical_tag": "tag_base",
                "anchor_year": 2022,
                "km_bucket": 50000,
                "price_low": 10000,
                "price_mid": 11000,
                "price_high": 12000,
            }
        ]
    )

    coverage_df = gov.build_curve_coverage_report(static_df, group_map_df, curves_df)
    tag_alias = coverage_df.loc[coverage_df["canonical_tag"] == "tag_alias"].iloc[0]

    assert bool(tag_alias["has_curve"]) is True
    assert int(tag_alias["curve_rows"]) == 1
    curves.load_curve_aliases.cache_clear()
