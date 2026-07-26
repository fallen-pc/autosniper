from pathlib import Path

import pandas as pd

from scripts import build_restricted_datasets
from shared import curves


def test_persist_canonical_assignments_updates_tags_without_changing_rows(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "sold_cars.csv"
    source = pd.DataFrame(
        [
            {
                "url": "https://example.test/one",
                "year": 2012,
                "canonical_tag": "UNCLASSIFIED",
                "canonical_reason": "[OUT_OF_SCOPE]",
            },
            {
                "url": "https://example.test/two",
                "year": 2015,
                "canonical_tag": "keep_existing",
                "canonical_reason": "[OK]",
            },
            {
                "url": "https://example.test/one",
                "year": 2012,
                "canonical_tag": "UNCLASSIFIED",
                "canonical_reason": "[OUT_OF_SCOPE]",
            },
        ]
    )
    tagged = pd.DataFrame(
        [
            {
                "url": "https://example.test/one",
                "canonical_tag": "new_supported_tag",
                "canonical_reason": "[OK]",
            }
        ]
    )

    writes: list[pd.DataFrame] = []

    def capture_write(df: pd.DataFrame, path: Path, *, index: bool) -> None:
        assert path == output_path
        assert index is False
        writes.append(df.copy())

    monkeypatch.setattr(
        build_restricted_datasets,
        "write_dataframe_csv_atomic",
        capture_write,
    )

    changed = build_restricted_datasets._persist_canonical_assignments(
        source,
        tagged,
        output_path,
    )

    assert changed == 2
    assert len(writes) == 1
    persisted = writes[0]
    assert len(persisted) == len(source)
    assert persisted.loc[0, "canonical_tag"] == "new_supported_tag"
    assert persisted.loc[0, "canonical_reason"] == "[OK]"
    assert persisted.loc[1, "canonical_tag"] == "keep_existing"
    assert persisted.loc[2, "canonical_tag"] == "new_supported_tag"


def test_persist_canonical_assignments_does_not_rewrite_unchanged_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "sold_cars.csv"
    source = pd.DataFrame(
        [
            {
                "url": "https://example.test/one",
                "canonical_tag": "supported_tag",
                "canonical_reason": "[OK]",
            }
        ]
    )

    monkeypatch.setattr(
        build_restricted_datasets,
        "write_dataframe_csv_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected write")),
    )

    changed = build_restricted_datasets._persist_canonical_assignments(
        source,
        source.copy(),
        output_path,
    )

    assert changed == 0


def test_governed_curve_save_immediately_rebuilds_restricted_datasets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    curve_path = tmp_path / "curves.csv"
    curve_frame = pd.DataFrame(
        [
            {
                "canonical_tag": "demo_curve",
                "anchor_year": 2020,
                "km_bucket": 100000,
                "price_low": 10000,
                "price_mid": 11000,
                "price_high": 12000,
            }
        ],
        columns=list(curves.CURVE_COLUMNS),
    )
    rebuilds: list[bool] = []

    monkeypatch.setattr(curves, "dataset_path", lambda _name: curve_path)
    monkeypatch.setattr(curves, "append_audit_snapshot", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(curves, "snapshot_curve_version", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        build_restricted_datasets,
        "build_restricted_datasets",
        lambda: rebuilds.append(True),
    )

    curves.save_curves(curve_frame)

    assert curve_path.exists()
    assert rebuilds == [True]
