"""Bounded latest-snapshot audit helpers for restricted datasets."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from scripts.atomic_csv import write_dataframe_csv_atomic

def append_audit_snapshot(df: pd.DataFrame, target_path: Path) -> Path | None:
    """Write the latest full snapshot without extending legacy append-only audits."""
    if df is None or df.empty:
        return None
    audit_dir = target_path.parent / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{target_path.stem}_audit_latest.csv"
    snapshot = df.copy()
    snapshot["audit_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_dataframe_csv_atomic(snapshot, audit_path, index=False)
    return audit_path
