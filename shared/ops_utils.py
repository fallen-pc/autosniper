"""Shared utilities for Ops/QA/Builder pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from shared.canonical_tagging import UNCLASSIFIED
from shared.curves import load_curves
from shared.data_loader import dataset_path, ensure_datasets_available


QUALITY_DIR = "quality"
NOTES_FILE = dataset_path(f"{QUALITY_DIR}/listing_notes.csv")
FLAGS_FILE = dataset_path(f"{QUALITY_DIR}/listing_flags.csv")
CURVE_QUEUE_FILE = dataset_path(f"{QUALITY_DIR}/curve_backlog.csv")


ISSUE_DEFINITIONS: dict[str, dict[str, str]] = {
    "NO_URL": {"severity": "red", "label": "Missing URL", "hint": "Listing has no URL."},
    "BAD_PARSE": {"severity": "red", "label": "Bad parse", "hint": "Missing core identity fields."},
    "MISSING_VARIANT": {"severity": "red", "label": "Missing variant", "hint": "Variant is blank."},
    "MISSING_VIN": {"severity": "red", "label": "Missing VIN", "hint": "VIN is blank or too short."},
    "MISSING_ODOM": {"severity": "red", "label": "Missing odometer", "hint": "Odometer missing or invalid."},
    "NO_TAG": {"severity": "yellow", "label": "No tag", "hint": "Canonical tag is missing."},
    "TAG_AMBIGUOUS": {"severity": "yellow", "label": "Tag ambiguous", "hint": "Canonical reason indicates ambiguity."},
    "NO_CURVE": {"severity": "yellow", "label": "No curve", "hint": "No curve data for this tag."},
    "LOW_CONFIDENCE": {"severity": "yellow", "label": "Low confidence", "hint": "AI confidence below threshold."},
    "COND_NOTES_EMPTY": {"severity": "gray", "label": "No condition notes", "hint": "general_condition is blank."},
    "NOT_ACTIVE": {"severity": "gray", "label": "Not active", "hint": "Listing status is not active."},
}

SEVERITY_RANK = {"green": 0, "gray": 1, "yellow": 2, "red": 3}
AMBIG_TOKENS = ("ambig", "multiple", "unknown", "unmapped", "fallback", "best guess")


@dataclass(frozen=True)
class IssueSummary:
    url: str
    severity: str
    issue_codes: list[str]
    issue_count: int


@dataclass(frozen=True)
class CurveMeta:
    canonical_tag: str
    last_updated: datetime | None
    anchor_years: list[int]


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() in {"nan", "none"}


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and pd.isna(value):
            return None
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_percent(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and pd.isna(value):
            return None
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_currency(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and pd.isna(value):
            return None
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    matches = re.findall(r"-?\\d+(?:\\.\\d+)?", text)
    if not matches:
        return None
    numbers = [float(match) for match in matches]
    if len(numbers) > 1 and "-" in text:
        return sum(numbers) / len(numbers)
    return numbers[0]


def parse_time_remaining_hours(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if not text or any(token in text for token in ("sold", "ended", "closed")):
        return None
    day_matches = re.findall(r"(\d+)\s*d", text)
    hour_matches = re.findall(r"(\d+)\s*h", text)
    minute_matches = re.findall(r"(\d+)\s*m", text)
    total_hours = sum(int(val) for val in day_matches) * 24
    total_hours += sum(int(val) for val in hour_matches)
    total_hours += sum(int(val) for val in minute_matches) / 60
    if total_hours == 0:
        clock_match = re.search(r"(\d{1,2}):(\d{2})", text)
        if clock_match:
            total_hours = int(clock_match.group(1)) + int(clock_match.group(2)) / 60
    return total_hours if total_hours > 0 else None


def time_bucket(hours: float | None) -> str:
    if hours is None:
        return "Unknown"
    if hours < 24:
        return "<24h"
    if hours < 48:
        return "1-2d"
    if hours < 72:
        return "2-3d"
    return "3+d"


def confidence_bucket(value: object) -> str:
    score = _to_float(value)
    if score is None:
        return "Unknown"
    if score >= 0.75:
        return "High"
    if score >= 0.6:
        return "Medium"
    return "Low"


def load_csv(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_static_df() -> pd.DataFrame:
    ensure_datasets_available(["vehicle_static_details.csv"])
    return load_csv(dataset_path("vehicle_static_details.csv"))


def load_active_df() -> pd.DataFrame:
    ensure_datasets_available(["active_vehicle_details.csv"])
    return load_csv(dataset_path("active_vehicle_details.csv"))


def load_valuations_df() -> pd.DataFrame:
    path = dataset_path("ai_listing_valuations.csv")
    df = load_csv(path)
    if df.empty:
        return df
    if "analysis_timestamp" in df.columns:
        df["analysis_timestamp"] = pd.to_datetime(df["analysis_timestamp"], errors="coerce")
        df = df.sort_values("analysis_timestamp").drop_duplicates("url", keep="last")
    return df


def load_group_map_df() -> pd.DataFrame:
    return load_csv(dataset_path("restricted_group_map.csv"))


def load_curves_df() -> pd.DataFrame:
    return load_curves()


def _ensure_quality_path(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_notes_df() -> pd.DataFrame:
    return load_csv(NOTES_FILE)


def load_flags_df() -> pd.DataFrame:
    return load_csv(FLAGS_FILE)


def load_curve_queue_df() -> pd.DataFrame:
    return load_csv(CURVE_QUEUE_FILE)


def append_note(url: str, note: str, author: str | None = None) -> None:
    _ensure_quality_path(NOTES_FILE)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "note": note,
        "author": author or "",
    }
    df = pd.DataFrame([entry])
    write_header = not NOTES_FILE.exists()
    df.to_csv(NOTES_FILE, mode="a", header=write_header, index=False)


def append_flag(url: str, flag: str, reason: str | None = None) -> None:
    _ensure_quality_path(FLAGS_FILE)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "flag": flag,
        "reason": reason or "",
    }
    df = pd.DataFrame([entry])
    write_header = not FLAGS_FILE.exists()
    df.to_csv(FLAGS_FILE, mode="a", header=write_header, index=False)


def append_curve_queue(url: str, canonical_tag: str) -> None:
    _ensure_quality_path(CURVE_QUEUE_FILE)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": url,
        "canonical_tag": canonical_tag,
    }
    df = pd.DataFrame([entry])
    write_header = not CURVE_QUEUE_FILE.exists()
    df.to_csv(CURVE_QUEUE_FILE, mode="a", header=write_header, index=False)


def build_curve_meta(curves_df: pd.DataFrame) -> dict[str, CurveMeta]:
    if curves_df.empty:
        return {}
    working = curves_df.copy()
    working["canonical_tag"] = working.get("canonical_tag", "").astype(str).str.strip()
    working = working[working["canonical_tag"] != ""]
    if working.empty:
        return {}
    working["anchor_year"] = pd.to_numeric(working.get("anchor_year"), errors="coerce")
    meta: dict[str, CurveMeta] = {}
    for canonical_tag, subset in working.groupby("canonical_tag"):
        anchor_years = sorted({int(val) for val in subset["anchor_year"].dropna().tolist()})
        meta[canonical_tag] = CurveMeta(
            canonical_tag=str(canonical_tag),
            last_updated=None,
            anchor_years=anchor_years,
        )
    return meta


def has_curve(canonical_tag: str, curve_meta: dict[str, CurveMeta]) -> bool:
    if not canonical_tag:
        return False
    return canonical_tag in curve_meta


def build_issue_index(
    static_df: pd.DataFrame,
    active_df: pd.DataFrame | None = None,
    valuations_df: pd.DataFrame | None = None,
    curve_meta: dict[str, CurveMeta] | None = None,
) -> pd.DataFrame:
    if static_df is None or static_df.empty:
        return pd.DataFrame(columns=["url", "severity", "issue_codes", "issue_count"])

    curve_meta = curve_meta or {}
    active_lookup = {}
    if active_df is not None and not active_df.empty and "url" in active_df.columns:
        active_lookup = active_df.set_index("url").to_dict(orient="index")

    valuation_lookup = {}
    if valuations_df is not None and not valuations_df.empty and "url" in valuations_df.columns:
        valuation_lookup = valuations_df.set_index("url").to_dict(orient="index")

    summaries: list[IssueSummary] = []

    for _, row in static_df.iterrows():
        url = str(row.get("url", "")).strip()
        issues: list[str] = []

        if _is_blank(url):
            issues.append("NO_URL")

        for core in ("year", "make", "model"):
            if _is_blank(row.get(core)):
                if "BAD_PARSE" not in issues:
                    issues.append("BAD_PARSE")

        if _is_blank(row.get("variant")):
            issues.append("MISSING_VARIANT")

        vin = str(row.get("vin", "")).strip()
        if _is_blank(vin) or len(vin) < 10:
            issues.append("MISSING_VIN")

        odom = _to_float(row.get("odometer_reading"))
        if odom is None or odom <= 0:
            issues.append("MISSING_ODOM")

        canonical_tag = str(row.get("canonical_tag", "")).strip()
        if _is_blank(canonical_tag) or canonical_tag == UNCLASSIFIED:
            issues.append("NO_TAG")
        else:
            if not has_curve(canonical_tag, curve_meta):
                issues.append("NO_CURVE")

        canonical_reason = str(row.get("canonical_reason", "")).strip().lower()
        if any(token in canonical_reason for token in AMBIG_TOKENS):
            issues.append("TAG_AMBIGUOUS")

        if _is_blank(row.get("general_condition")):
            issues.append("COND_NOTES_EMPTY")

        if url and url in active_lookup:
            status = str(active_lookup[url].get("status", "")).strip().lower()
            if status and status != "active":
                issues.append("NOT_ACTIVE")

        if url and url in valuation_lookup:
            confidence = valuation_lookup[url].get("confidence")
            if confidence is not None:
                conf_value = _to_float(confidence)
                if conf_value is not None and conf_value < 0.6:
                    issues.append("LOW_CONFIDENCE")

        severity = "green"
        if issues:
            severity = max(
                (ISSUE_DEFINITIONS.get(code, {}).get("severity", "gray") for code in issues),
                key=lambda level: SEVERITY_RANK.get(level, 0),
            )

        summaries.append(
            IssueSummary(
                url=url,
                severity=severity,
                issue_codes=sorted(set(issues)),
                issue_count=len(set(issues)),
            )
        )

    return pd.DataFrame([
        {
            "url": summary.url,
            "severity": summary.severity,
            "issue_codes": summary.issue_codes,
            "issue_summary": ", ".join(summary.issue_codes),
            "issue_count": summary.issue_count,
        }
        for summary in summaries
    ])


def explode_issues(issue_df: pd.DataFrame) -> pd.DataFrame:
    if issue_df.empty:
        return pd.DataFrame(columns=["url", "issue_code", "severity"])
    working = issue_df.copy()
    working = working.explode("issue_codes")
    working = working.rename(columns={"issue_codes": "issue_code"})
    working["issue_code"] = working["issue_code"].fillna("")
    working = working[working["issue_code"] != ""]
    return working


def format_issue_label(code: str) -> str:
    meta = ISSUE_DEFINITIONS.get(code, {})
    return meta.get("label", code)


def issue_hint(code: str) -> str:
    meta = ISSUE_DEFINITIONS.get(code, {})
    return meta.get("hint", "")


def load_spec_data() -> dict:
    return {}


def list_missing_curve_anchors(spec: dict, curves_df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame()


def apply_global_filters(
    df: pd.DataFrame,
    *,
    make_filter: Iterable[str] | None = None,
    model_filter: Iterable[str] | None = None,
    status_filter: Iterable[str] | None = None,
    verdict_filter: Iterable[str] | None = None,
    confidence_filter: Iterable[str] | None = None,
    time_bucket_filter: Iterable[str] | None = None,
    has_curve_filter: str | None = None,
) -> pd.DataFrame:
    filtered = df.copy()
    if make_filter:
        filtered = filtered[filtered["make"].isin(make_filter)]
    if model_filter and "model" in filtered.columns:
        filtered = filtered[filtered["model"].isin(model_filter)]
    if status_filter and "status" in filtered.columns:
        filtered = filtered[filtered["status"].isin(status_filter)]
    if verdict_filter and "verdict" in filtered.columns:
        filtered = filtered[filtered["verdict"].isin(verdict_filter)]
    if confidence_filter and "confidence_bucket" in filtered.columns:
        filtered = filtered[filtered["confidence_bucket"].isin(confidence_filter)]
    if time_bucket_filter and "time_bucket" in filtered.columns:
        filtered = filtered[filtered["time_bucket"].isin(time_bucket_filter)]
    if has_curve_filter == "Yes" and "has_curve" in filtered.columns:
        filtered = filtered[filtered["has_curve"]]
    if has_curve_filter == "No" and "has_curve" in filtered.columns:
        filtered = filtered[~filtered["has_curve"]]
    return filtered
