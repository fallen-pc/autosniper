from __future__ import annotations

from pathlib import Path
from typing import Iterable
import logging
import re

import pandas as pd

from shared.csv_utils import CSV_READ_ERRORS

logger = logging.getLogger(__name__)


REPORT_DIR = Path("CSV_data/reports")
DECISIONS_PATH = REPORT_DIR / "repair_review_decisions.csv"
LIVE_QUEUE_PATH = REPORT_DIR / "repair_review_live_queue.csv"

REVIEW_COLUMNS = [
    "repair_key",
    "repair_item",
    "review_bucket",
    "decision",
    "target_category",
    "canonical_defect",
    "severity_hint",
    "cost_model",
    "notes",
]

LIVE_QUEUE_COLUMNS = [
    "repair_key",
    "repair_item",
    "review_bucket",
    "status",
    "category",
    "canonical_defects",
    "occurrences",
    "listing_count",
    "source_file",
    "example_vehicles",
    "example_urls",
    "example_condition_notes",
]

RESOLVED_DECISIONS = {
    "Add dictionary rule",
    "Ignore as boilerplate",
    "Mark feature-list leak",
    "Mark context fragment",
    "Mark usage risk",
}

UNMAPPED_STATUSES = {"unclassified", "not_assessed_after_hard_avoid"}
UNMAPPED_CATEGORIES = {"unclassified", "not_assessed"}


def safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def review_key(value: object) -> str:
    text = safe_text(value).lower()
    return text.replace("’", "'").replace("‘", "'")


def normalized_review_key(value: object) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", review_key(value))
    return re.sub(r"\s+", " ", text).strip()


def load_repair_review_decisions(path: Path = DECISIONS_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    try:
        df = pd.read_csv(path).fillna("")
    except CSV_READ_ERRORS as exc:
        logger.warning(
            "Unreadable repair review decisions %s (%s: %s); treating them as empty.",
            path,
            type(exc).__name__,
            exc,
        )
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    for column in REVIEW_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[REVIEW_COLUMNS]


def latest_repair_decisions(decisions: pd.DataFrame) -> pd.DataFrame:
    """Return the current decision for each repair key.

    The review CSV has historically been used both as an append-only audit trail
    and as an upserted current-state file. Downstream counts must collapse it
    before counting phrases, canonicals, or pricing requirements.
    """
    if decisions.empty or "repair_key" not in decisions.columns:
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    out = decisions.copy()
    for column in REVIEW_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out["repair_key"] = out["repair_key"].map(safe_text)
    out = out[out["repair_key"] != ""]
    return out.drop_duplicates(subset=["repair_key"], keep="last")[REVIEW_COLUMNS].reset_index(drop=True)


def latest_decision_lookup(decisions: pd.DataFrame | None = None) -> dict[str, dict[str, str]]:
    df = load_repair_review_decisions() if decisions is None else decisions
    latest = latest_repair_decisions(df)
    if latest.empty:
        return {}
    lookup: dict[str, dict[str, str]] = {}
    for _, row in latest.iterrows():
        record = {column: safe_text(row.get(column)) for column in REVIEW_COLUMNS}
        for value in (row.get("repair_key"), row.get("repair_item")):
            for key in {review_key(value).rstrip(". "), normalized_review_key(value)}:
                if key:
                    lookup[key] = record
    return lookup


def _needs_mapping(record: dict[str, object]) -> bool:
    status = safe_text(record.get("status"))
    category = safe_text(record.get("category"))
    defects = safe_text(record.get("canonical_defects"))
    if status in {"hard_avoid", "not_assessed_after_hard_avoid"}:
        return False
    return status in UNMAPPED_STATUSES or category in UNMAPPED_CATEGORIES or not defects


def repair_mapping_summary(
    records: Iterable[dict[str, object]],
    decisions: pd.DataFrame | None = None,
) -> dict[str, object]:
    lookup = latest_decision_lookup(decisions)
    mapped: list[dict[str, object]] = []
    needs_review: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []

    for record in records:
        repair_key = review_key(record.get("repair_key")).rstrip(". ")
        decision = lookup.get(repair_key, lookup.get(normalized_review_key(record.get("repair_key")), {}))
        decision_label = safe_text(decision.get("decision"))
        if decision_label == "Leave unclassified":
            unresolved.append({**record, "review_decision": decision_label})
        elif decision_label in RESOLVED_DECISIONS:
            mapped.append({**record, "review_decision": decision_label})
        elif _needs_mapping(record):
            needs_review.append({**record, "review_decision": ""})
        else:
            mapped.append({**record, "review_decision": ""})

    total = len(mapped) + len(needs_review) + len(unresolved)
    return {
        "total": total,
        "mapped_count": len(mapped),
        "needs_review_count": len(needs_review),
        "unresolved_count": len(unresolved),
        "pass": total > 0 and not needs_review and not unresolved,
        "mapped_records": mapped,
        "needs_review_records": needs_review,
        "unresolved_records": unresolved,
    }


def append_live_review_items(
    records: Iterable[dict[str, object]],
    *,
    vehicle: str,
    url: str,
    condition_notes: str,
    source_file: str = "AI_ANALYSIS_LIVE",
    path: Path = LIVE_QUEUE_PATH,
) -> int:
    rows: list[dict[str, object]] = []
    for record in records:
        repair_key = review_key(record.get("repair_key"))
        if not repair_key:
            continue
        rows.append(
            {
                "repair_key": repair_key,
                "repair_item": safe_text(record.get("original_text")),
                "review_bucket": "Needs AI Analysis review",
                "status": safe_text(record.get("status")) or "unclassified",
                "category": safe_text(record.get("category")) or "unclassified",
                "canonical_defects": safe_text(record.get("canonical_defects")),
                "occurrences": 1,
                "listing_count": 1,
                "source_file": source_file,
                "example_vehicles": vehicle,
                "example_urls": url,
                "example_condition_notes": condition_notes,
            }
        )
    if not rows:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_csv(path).fillna("") if path.exists() else pd.DataFrame(columns=LIVE_QUEUE_COLUMNS)
    for column in LIVE_QUEUE_COLUMNS:
        if column not in existing.columns:
            existing[column] = ""
    incoming = pd.DataFrame(rows, columns=LIVE_QUEUE_COLUMNS)
    combined = pd.concat([existing[LIVE_QUEUE_COLUMNS], incoming], ignore_index=True)
    combined = combined.drop_duplicates(subset=["repair_key"], keep="last")
    combined.to_csv(path, index=False)
    return len(incoming)


def append_unclassified_condition_lines(
    lines: Iterable[object],
    *,
    vehicle: str,
    url: str,
    condition_notes: str,
    source_file: str = "AI_ANALYSIS_LIVE",
    path: Path = LIVE_QUEUE_PATH,
) -> int:
    records: list[dict[str, object]] = []
    for line in lines:
        text = safe_text(line)
        if not text or text.rstrip(".").isdigit():
            continue
        records.append(
            {
                "repair_key": review_key(text),
                "original_text": text,
                "status": "unclassified",
                "category": "unclassified",
                "canonical_defects": "",
            }
        )
    return append_live_review_items(
        records,
        vehicle=vehicle,
        url=url,
        condition_notes=condition_notes,
        source_file=source_file,
        path=path,
    )
