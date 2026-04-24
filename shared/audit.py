"""Append-only audit helpers for restricted datasets."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def _existing_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        return next(reader, [])


def append_audit_snapshot(df: pd.DataFrame, target_path: Path) -> Path | None:
    if df is None or df.empty:
        return None
    audit_dir = target_path.parent / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{target_path.stem}_audit.csv"
    snapshot = df.copy()
    snapshot["audit_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    expected_columns = snapshot.columns.tolist()
    if audit_path.exists():
        try:
            current_header = _existing_header(audit_path)
        except Exception:
            current_header = []
        if current_header == expected_columns:
            snapshot.to_csv(audit_path, mode="a", header=False, index=False)
        else:
            snapshot.to_csv(audit_path, index=False)
    else:
        snapshot.to_csv(audit_path, index=False)
    return audit_path
