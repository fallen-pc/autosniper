"""Append-only pipeline exclusion ledger helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Mapping

import pandas as pd

from shared.data_loader import dataset_path
from shared.schema import PIPELINE_EXCLUSION_SCHEMA


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_pipeline_exclusions(
    records: Iterable[Mapping[str, object]],
    *,
    stage: str,
    run_id: str = "",
) -> None:
    if not records:
        return
    stage_label = (stage or "").strip() or "unspecified"
    rows: list[dict[str, object]] = []
    for record in records:
        url = str(record.get("url", "") or "").strip()
        if not url:
            continue
        reason = str(record.get("reason_code", "") or "").strip()
        timestamp = record.get("timestamp") or _utc_now_iso()
        details = record.get("details")
        if details in (None, ""):
            details = record.get("field_snapshot") or record.get("field_snapshot_json") or ""
        if isinstance(details, (dict, list)):
            details = json.dumps(details, ensure_ascii=True)
        rows.append(
            {
                "url": url,
                "reason_code": reason,
                "timestamp": timestamp,
                "stage": stage_label,
                "run_id": run_id,
                "details": details or "",
            }
        )
    if not rows:
        return

    exclusions_path = dataset_path("pipeline_exclusions.csv")
    exclusions_path.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(rows).reindex(columns=PIPELINE_EXCLUSION_SCHEMA)
    file_exists = exclusions_path.exists()
    new_df.to_csv(exclusions_path, mode="a", header=not file_exists, index=False)
