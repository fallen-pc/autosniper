from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd


def _as_path(path: Path | str) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _temp_path(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.stem}_",
        suffix=f"{destination.suffix or '.csv'}.tmp",
        dir=destination.parent,
    )
    os.close(fd)
    return Path(temp_name)


def write_dataframe_csv_atomic(
    df: pd.DataFrame,
    path: Path | str,
    **to_csv_kwargs: object,
) -> None:
    destination = _as_path(path)
    temp_path = _temp_path(destination)
    try:
        df.to_csv(temp_path, **to_csv_kwargs)
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def append_dataframe_csv_atomic(
    df: pd.DataFrame,
    path: Path | str,
    *,
    index: bool = False,
) -> None:
    if df.empty:
        return
    destination = _as_path(path)
    if destination.exists():
        try:
            existing = pd.read_csv(destination, low_memory=False)
        except (pd.errors.EmptyDataError, ValueError):
            existing = pd.DataFrame()
        combined = pd.concat([existing, df], ignore_index=True, sort=False)
    else:
        combined = df.copy()
    write_dataframe_csv_atomic(combined, destination, index=index)


def write_dict_rows_csv_atomic(
    path: Path | str,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    destination = _as_path(path)
    temp_path = _temp_path(destination)
    columns = list(fieldnames)
    try:
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in columns})
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def append_dict_rows_csv_atomic(
    path: Path | str,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    pending_rows = list(rows)
    if not pending_rows:
        return

    destination = _as_path(path)
    temp_path = _temp_path(destination)
    columns = list(fieldnames)
    try:
        with temp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            if destination.exists():
                with destination.open("r", newline="", encoding="utf-8") as source:
                    reader = csv.DictReader(source)
                    for existing_row in reader:
                        writer.writerow({column: existing_row.get(column, "") for column in columns})
            for row in pending_rows:
                writer.writerow({column: row.get(column, "") for column in columns})
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()
