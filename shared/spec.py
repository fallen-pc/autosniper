"""Spec loader and helpers for the restricted valuation universe."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, Tuple
import os

SPEC_PATH = Path(__file__).resolve().parent.parent / "config" / "spec_v1.yaml"


def normalize_mapping_key(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


def load_spec(path: Path | None = None) -> Dict[str, Any]:
    spec_path = path or SPEC_PATH
    if not spec_path.exists():
        return {}
    try:
        import yaml
    except ImportError:  # pragma: no cover - handled by requirements
        return {"_error": "pyyaml_missing", "_path": str(spec_path)}
    with spec_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def get_spec_error(spec: Dict[str, Any] | None) -> str | None:
    if not spec:
        return None
    return spec.get("_error")


def get_group_index(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    groups = spec.get("groups") or []
    index: Dict[str, Dict[str, Any]] = {}
    for group in groups:
        group_id = group.get("group_id")
        if group_id:
            index[group_id] = group
    return index


def get_group_spec(spec: Dict[str, Any], group_id: str | None) -> Dict[str, Any] | None:
    if not spec or not group_id:
        return None
    return get_group_index(spec).get(group_id)


def build_pipe_mapping(spec: Dict[str, Any]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for group in spec.get("groups") or []:
        group_id = group.get("group_id")
        if not group_id:
            continue
        for key in group.get("pipe_mappings") or []:
            norm = normalize_mapping_key(key)
            if norm:
                mapping[norm] = group_id
    return mapping


def normalize_series(group_spec: Dict[str, Any] | None, series: str | None) -> str | None:
    if series is None:
        return None
    text = str(series).strip()
    if not text:
        return None
    if not group_spec:
        return text
    aliases = group_spec.get("series_aliases") or {}
    if aliases:
        alias_map = {str(key).strip().lower(): str(val).strip() for key, val in aliases.items()}
        mapped = alias_map.get(text.lower())
        if mapped:
            return mapped
    return text


def is_series_allowed(group_spec: Dict[str, Any] | None, series: str | None) -> bool:
    if not group_spec:
        return True
    allowed = group_spec.get("series_allowed")
    if not allowed:
        return True
    normalized = normalize_series(group_spec, series)
    if normalized is None:
        return False
    allowed_norm = {str(item).strip().lower() for item in allowed}
    return str(normalized).strip().lower() in allowed_norm


def resolve_series_for_year(
    spec: Dict[str, Any], group_id: str | None, year: int | None
) -> Tuple[str | None, str]:
    group_spec = get_group_spec(spec, group_id)
    if not group_spec:
        return None, "UNKNOWN_GROUP_MAPPING"
    guard = group_spec.get("series_year_guard") or {}
    if not guard:
        return None, ""
    if year is None:
        return None, "INSUFFICIENT_DATA"
    for series, bounds in guard.items():
        year_min = bounds.get("year_min")
        year_max = bounds.get("year_max")
        if year_min is not None and year < year_min:
            continue
        if year_max is not None and year > year_max:
            continue
        return series, ""
    return None, "GENERATION_NOT_COVERED"


def validate_curve_requirements(spec: Dict[str, Any], curves_df: Any) -> list[str]:
    if os.getenv("CURVE_MODEL", "v2").strip().lower() == "v2":
        return []
    if not spec or curves_df is None or getattr(curves_df, "empty", True):
        return []
    issues: list[str] = []
    for group in spec.get("groups") or []:
        group_id = group.get("group_id")
        if not group_id:
            continue
        subset = curves_df[curves_df["group_id"] == group_id]
        if subset.empty:
            issues.append(f"{group_id}: no curve rows found")
            continue
        allowed_series = group.get("series_allowed") or []
        if allowed_series:
            allowed_norm = {str(val).strip().lower() for val in allowed_series}
            present_series = set()
            for val in subset["series"].dropna().unique().tolist():
                normalized = normalize_series(group, val)
                if normalized:
                    present_series.add(str(normalized).strip().lower())
            unexpected = sorted(series for series in present_series if series not in allowed_norm)
            if unexpected:
                issues.append(f"{group_id}: unexpected series {', '.join(unexpected)}")
        if allowed_series and len(allowed_series) > 1 and not group.get("series_year_guard"):
            issues.append(f"{group_id}: series_year_guard missing for multi-series group")
        requirements = group.get("curve_requirements") or {}
        anchor_years = requirements.get("anchor_years") or []
        km_anchors = requirements.get("km_anchors") or []
        for anchor_year in anchor_years:
            for km_anchor in km_anchors:
                mask = (subset["anchor_year"] == anchor_year) & (subset["km_anchor"] == km_anchor)
                if not mask.any():
                    issues.append(f"{group_id}: missing anchor {anchor_year} @ {km_anchor}km")
    return issues
