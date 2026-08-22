"""Read-only repair dictionary and pricing coverage views.

The workbench helpers deliberately contain no Streamlit code.  They provide one
latest-decision interpretation for the review and pricing pages and make the UI
status labels testable without loading the application.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

import pandas as pd

from shared.repair_review import latest_repair_decisions, safe_text


DICTIONARY_NODE_COLUMNS = [
    "canonical_defect",
    "category",
    "phrase_count",
    "cost_model",
    "hard_avoid",
    "mixed_category",
    "phrases",
]

LEDGER_STATUSES = ["Verified", "Partial", "Provisional", "Generic fallback", "Missing"]
PARTIAL_MARKERS = (
    "part only",
    "parts only",
    "labour only",
    "labor only",
    "install only",
    "install-only",
    "excluding",
    "excludes",
    "supply only",
    "plus labour",
    "plus labor",
)
PROVISIONAL_MARKERS = ("provisional", "baseline", "public guide", "indicative", "estimate only")


def _mode(values: Iterable[object], fallback: str = "unknown") -> str:
    cleaned = [safe_text(value) for value in values if safe_text(value)]
    if not cleaned:
        return fallback
    counts = Counter(cleaned)
    return sorted(counts, key=lambda value: (-counts[value], value))[0]


def repair_dictionary_nodes(decisions: pd.DataFrame) -> pd.DataFrame:
    """Summarise active dictionary rules by canonical repair type."""
    current = latest_repair_decisions(decisions)
    if current.empty:
        return pd.DataFrame(columns=DICTIONARY_NODE_COLUMNS)
    active = current[current["decision"].map(safe_text) == "Add dictionary rule"].copy()
    active["canonical_defect"] = active["canonical_defect"].map(safe_text)
    active = active[active["canonical_defect"] != ""]
    if active.empty:
        return pd.DataFrame(columns=DICTIONARY_NODE_COLUMNS)

    rows: list[dict[str, object]] = []
    for canonical, group in active.groupby("canonical_defect", sort=True):
        categories = [safe_text(value) for value in group["target_category"] if safe_text(value)]
        models = [safe_text(value) for value in group["cost_model"] if safe_text(value)]
        phrases = list(dict.fromkeys(safe_text(value) for value in group["repair_item"] if safe_text(value)))
        rows.append(
            {
                "canonical_defect": canonical,
                "category": _mode(categories),
                "phrase_count": len(phrases),
                "cost_model": _mode(models, ""),
                "hard_avoid": "hard_avoid" in models,
                "mixed_category": len(set(categories)) > 1,
                "phrases": phrases,
            }
        )
    return pd.DataFrame(rows, columns=DICTIONARY_NODE_COLUMNS).sort_values(
        ["phrase_count", "canonical_defect"], ascending=[False, True]
    ).reset_index(drop=True)


def dictionary_phrase_rows(decisions: pd.DataFrame, canonical_defect: object) -> pd.DataFrame:
    """Return current phrase mappings for one canonical, ready for display."""
    canonical = safe_text(canonical_defect)
    current = latest_repair_decisions(decisions)
    if not canonical or current.empty:
        return pd.DataFrame(columns=["repair_item", "target_category", "cost_model", "repair_key"])
    rows = current[
        (current["decision"].map(safe_text) == "Add dictionary rule")
        & (current["canonical_defect"].map(safe_text) == canonical)
    ].copy()
    return rows[["repair_item", "target_category", "cost_model", "repair_key"]].sort_values("repair_item")


def pricing_evidence_status(row: pd.Series | dict[str, object] | None) -> str:
    """Classify an exact schedule row by evidence completeness and confidence."""
    if row is None:
        return "Missing"
    get = row.get
    source = safe_text(get("evidence_source"))
    method = safe_text(get("pricing_method")).lower()
    confidence = safe_text(get("confidence")).lower()
    notes = " ".join([source, safe_text(get("notes"))]).lower()
    if not source:
        return "Missing"
    if any(marker in notes for marker in PARTIAL_MARKERS):
        return "Partial"
    if method == "internal_default" or confidence == "low" or any(marker in notes for marker in PROVISIONAL_MARKERS):
        return "Provisional"
    estimates: list[float] = []
    for column in ("low_estimate", "default_estimate", "high_estimate"):
        try:
            estimates.append(float(get(column)))
        except (TypeError, ValueError):
            return "Provisional"
    if not (0 < estimates[0] <= estimates[1] <= estimates[2]):
        return "Provisional"
    if confidence in {"medium", "high"} and method in {
        "repair_quote",
        "wrecker_part_price",
        "parts_supplier_price",
        "parts_plus_labour",
    }:
        return "Verified"
    return "Provisional"


def pricing_coverage_ledger(matrix: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """Attach evidence-quality labels and source details to coverage cells."""
    if matrix.empty:
        return pd.DataFrame(
            columns=[
                "canonical_defect",
                "vehicle_class",
                "cost_model",
                "status",
                "evidence_quality",
                "occurrences",
                "default_estimate",
                "evidence_source",
                "evidence_date",
                "confidence",
            ]
        )

    schedule_rows: dict[tuple[str, str], dict[str, object]] = {}
    for _, row in schedule.iterrows():
        canonical = safe_text(row.get("canonical_defect"))
        vehicle_class = safe_text(row.get("vehicle_class")).lower()
        if canonical and vehicle_class:
            schedule_rows[(canonical, vehicle_class)] = row.to_dict()

    records: list[dict[str, object]] = []
    for _, cell in matrix.iterrows():
        canonical = safe_text(cell.get("canonical_defect"))
        vehicle_class = safe_text(cell.get("vehicle_class")).lower()
        exact = schedule_rows.get((canonical, vehicle_class))
        generic = schedule_rows.get((canonical, "generic"))
        coverage = safe_text(cell.get("status"))
        evidence = exact or generic
        if exact is not None:
            status = pricing_evidence_status(exact)
        elif generic is not None and coverage.lower() == "generic":
            status = "Generic fallback"
        else:
            status = "Missing"
        try:
            occurrences = int(float(cell.get("occurrences", 0) or 0))
        except (TypeError, ValueError):
            occurrences = 0
        records.append(
            {
                "canonical_defect": canonical,
                "vehicle_class": vehicle_class,
                "cost_model": safe_text(cell.get("cost_model")),
                "status": status,
                "evidence_quality": pricing_evidence_status(evidence),
                "occurrences": occurrences,
                "default_estimate": evidence.get("default_estimate", "") if evidence else "",
                "evidence_source": safe_text(evidence.get("evidence_source")) if evidence else "",
                "evidence_date": safe_text(evidence.get("evidence_date")) if evidence else "",
                "confidence": safe_text(evidence.get("confidence")) if evidence else "",
            }
        )
    return pd.DataFrame(records).sort_values(
        ["occurrences", "canonical_defect", "vehicle_class"], ascending=[False, True, True]
    ).reset_index(drop=True)
