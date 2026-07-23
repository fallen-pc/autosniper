from __future__ import annotations

import csv
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd


LOCK_TIMEOUT_SECONDS = 15.0
LOCK_STALE_SECONDS = 300.0
LOCK_POLL_SECONDS = 0.1
REPLACE_ATTEMPTS = 5
REPLACE_RETRY_SECONDS = 0.5


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


def _lock_path(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.lock")


@contextmanager
def _csv_write_lock(destination: Path):
    """Serialize read-modify-write operations across local processes."""
    lock_path = _lock_path(destination)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        except FileExistsError:
            try:
                age_seconds = time.time() - lock_path.stat().st_mtime
                if age_seconds > LOCK_STALE_SECONDS:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for CSV write lock: {destination}") from None
            time.sleep(LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _replace_with_retry(temp_path: Path, destination: Path) -> None:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(temp_path, destination)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_RETRY_SECONDS)


def _write_dataframe_csv_atomic_unlocked(
    df: pd.DataFrame,
    destination: Path,
    **to_csv_kwargs: object,
) -> None:
    temp_path = _temp_path(destination)
    try:
        df.to_csv(temp_path, **to_csv_kwargs)
        _replace_with_retry(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_dataframe_csv_atomic(
    df: pd.DataFrame,
    path: Path | str,
    **to_csv_kwargs: object,
) -> None:
    destination = _as_path(path)
    with _csv_write_lock(destination):
        _write_dataframe_csv_atomic_unlocked(df, destination, **to_csv_kwargs)


def append_dataframe_csv_atomic(
    df: pd.DataFrame,
    path: Path | str,
    *,
    index: bool = False,
) -> None:
    if df.empty:
        return
    destination = _as_path(path)
    with _csv_write_lock(destination):
        if destination.exists():
            try:
                existing = pd.read_csv(destination, low_memory=False)
            except (pd.errors.EmptyDataError, ValueError):
                existing = pd.DataFrame()
            combined = pd.concat([existing, df], ignore_index=True, sort=False)
        else:
            combined = df.copy()
        _write_dataframe_csv_atomic_unlocked(combined, destination, index=index)


def write_dict_rows_csv_atomic(
    path: Path | str,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    destination = _as_path(path)
    pending_rows = list(rows)
    columns = list(fieldnames)
    with _csv_write_lock(destination):
        temp_path = _temp_path(destination)
        try:
            with temp_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for row in pending_rows:
                    writer.writerow({column: row.get(column, "") for column in columns})
            _replace_with_retry(temp_path, destination)
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
    columns = list(fieldnames)
    with _csv_write_lock(destination):
        temp_path = _temp_path(destination)
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
            _replace_with_retry(temp_path, destination)
        finally:
            if temp_path.exists():
                temp_path.unlink()
