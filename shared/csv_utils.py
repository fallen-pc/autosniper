"""Stable CSV loading helpers for dashboard/runtime code."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd


def count_csv_records(path: Path | str) -> int | None:
    """Count logical CSV records, including rows with quoted embedded newlines."""
    file_path = Path(path)
    if not file_path.exists():
        return None
    try:
        with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)
    except (OSError, csv.Error):
        return None


def read_csv_stable(path: Path | str, **kwargs: Any) -> pd.DataFrame:
    """Read CSVs with deterministic mixed-type handling."""
    options = dict(kwargs)
    options.setdefault("low_memory", False)
    return pd.read_csv(path, **options)


def read_csv_or_empty(path: Path | str, **kwargs: Any) -> pd.DataFrame:
    """Return an empty frame when the CSV is missing or unreadable as tabular data."""
    file_path = Path(path)
    if not file_path.exists():
        return pd.DataFrame()
    try:
        return read_csv_stable(file_path, **kwargs)
    except (FileNotFoundError, ValueError, pd.errors.EmptyDataError):
        return pd.DataFrame()
