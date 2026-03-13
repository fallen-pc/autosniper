"""Append-only audit helpers for restricted datasets."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def append_audit_snapshot(df: pd.DataFrame, target_path: Path) -> Path | None:
    if df is None or df.empty:
        return None
    audit_dir = target_path.parent / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / f"{target_path.stem}_audit.csv"
    snapshot = df.copy()
    snapshot["audit_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot.to_csv(audit_path, mode="a", header=not audit_path.exists(), index=False)
    return audit_path
