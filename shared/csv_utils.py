"""Stable CSV loading helpers for dashboard/runtime code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


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
