from __future__ import annotations

import warnings

import pandas as pd

from shared.csv_utils import read_csv_or_empty, read_csv_stable


def test_read_csv_stable_suppresses_mixed_type_dtype_warning(tmp_path):
    csv_path = tmp_path / "mixed.csv"
    csv_path.write_text(
        "url,value\n"
        "a,1\n"
        "b,text\n",
        encoding="utf-8",
    )

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        df = read_csv_stable(csv_path)

    assert list(df["value"]) == ["1", "text"]
    assert not any(issubclass(item.category, pd.errors.DtypeWarning) for item in captured)


def test_read_csv_or_empty_returns_empty_for_missing_file(tmp_path):
    df = read_csv_or_empty(tmp_path / "missing.csv")
    assert df.empty
