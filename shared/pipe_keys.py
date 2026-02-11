"""Helpers for pipe-form group identifiers."""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Optional, Tuple

from shared.canonical_tagging import load_allowed_variants

PIPE_DELIM = " | "
PIPE_PARTS = 4
SERIES_FALLBACK = "NA"


def _normalize_model(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_group_key(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _normalize_series(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text.upper()


def _normalize_year(value: object) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def looks_like_pipe_key(value: object) -> bool:
    if value is None:
        return False
    return PIPE_DELIM in str(value)


def format_pipe_key(
    model: object,
    group_key: object,
    series: object,
    anchor_year: object,
) -> str:
    model_text = _normalize_model(model)
    group_text = _normalize_group_key(group_key)
    series_text = _normalize_series(series) or SERIES_FALLBACK
    year_val = _normalize_year(anchor_year)
    year_text = str(year_val) if year_val is not None else SERIES_FALLBACK
    return f"{model_text}{PIPE_DELIM}{group_text}{PIPE_DELIM}{series_text}{PIPE_DELIM}{year_text}"


def parse_pipe_key(value: object) -> Optional[Tuple[str, str, str, Optional[int]]]:
    if value is None:
        return None
    text = str(value)
    if PIPE_DELIM not in text:
        return None
    parts = [part.strip() for part in text.split("|")]
    if len(parts) < PIPE_PARTS:
        return None
    model, group_key, series, year_text = parts[:PIPE_PARTS]
    year_val = _normalize_year(year_text)
    return model, group_key, series, year_val


def _pick_anchor_year(anchor_years: list[int], year: Optional[int]) -> Optional[int]:
    if not anchor_years:
        return year
    if year is None:
        return anchor_years[0]
    return min(anchor_years, key=lambda val: abs(val - year))


def _normalize_rule_token(value: object) -> str:
    text = str(value).strip().upper()
    return re.sub(r"[^A-Z0-9]+", "", text)


def _rule_matches(rule_value: object, candidate: str) -> bool:
    if rule_value is None or rule_value == "":
        return True
    candidate_norm = _normalize_rule_token(candidate)
    if isinstance(rule_value, (list, tuple, set)):
        return candidate_norm in {_normalize_rule_token(item) for item in rule_value}
    return candidate_norm == _normalize_rule_token(rule_value)


def _find_matching_spec_group_id(
    spec_data: dict, variant: object, year: Optional[int]
) -> Optional[str]:
    groups = spec_data.get("groups") or []
    make = "TOYOTA"
    model = str(getattr(variant, "model", "")).strip().upper()
    body = str(getattr(variant, "body", "")).strip().upper()
    fuel = str(getattr(variant, "fuel", "")).strip().upper()
    transmission = str(getattr(variant, "transmission", "")).strip().upper()
    for group in groups:
        rules = group.get("rules") or {}
        if "make" not in rules or "model" not in rules:
            continue
        if not _rule_matches(rules.get("make"), make):
            continue
        if not _rule_matches(rules.get("model"), model):
            continue
        if not _rule_matches(rules.get("body"), body):
            continue
        if not _rule_matches(rules.get("fuel"), fuel):
            continue
        if not _rule_matches(rules.get("transmission"), transmission):
            continue
        group_id = group.get("group_id")
        if not group_id:
            continue
        series_key, reason = resolve_series_for_year(spec_data, group_id, year)
        if reason in ("", "INSUFFICIENT_DATA"):
            return group_id
    return None


@lru_cache(maxsize=1)
def _allowed_variants_by_tag() -> dict[str, object]:
    return {variant.canonical_tag: variant for variant in load_allowed_variants()}


def pipe_key_from_canonical(
    canonical_tag: object,
    year: Optional[int],
    *,
    series_override: object | None = None,
    anchor_year_override: object | None = None,
    spec: Optional[dict] = None,
) -> Optional[str]:
    if canonical_tag is None:
        return None
    tag = str(canonical_tag).strip()
    if not tag:
        return None
    variants = _allowed_variants_by_tag()
    variant = variants.get(tag)
    if not variant:
        return None
    model = variant.model
    group_key = f"{variant.body}_{variant.fuel}_{variant.transmission}"
    if (
        model == "camry"
        and variant.body == "sedan"
        and variant.fuel == "petrol"
        and variant.transmission == "auto"
    ):
        badge_norm = _normalize_group_key(variant.badge)
        if badge_norm:
            group_key = f"{group_key}_{badge_norm}"
        if "2.5i" in tag:
            group_key = f"{group_key}_2_5i"

    series_key = _normalize_series(series_override)
    if not series_key:
        series_key = ""
    if not series_key:
        series_key = SERIES_FALLBACK

    anchor_year_val = _normalize_year(anchor_year_override)
    if anchor_year_val is None:
        anchor_year_val = _pick_anchor_year([], year)
    if anchor_year_val is None:
        anchor_year_val = year

    return format_pipe_key(model, group_key, series_key, anchor_year_val)


def legacy_group_id_to_pipe(
    group_id: object,
    series: object,
    anchor_year: object,
    *,
    spec: Optional[dict] = None,
) -> str:
    if group_id is None:
        return format_pipe_key("", "", series, anchor_year)
    raw = str(group_id).strip()
    if looks_like_pipe_key(raw):
        return raw
    if raw.startswith("toyota_"):
        pipe_key = pipe_key_from_canonical(
            raw,
            _normalize_year(anchor_year),
            series_override=series,
            anchor_year_override=anchor_year,
            spec=spec,
        )
        if pipe_key:
            return pipe_key
    parts = raw.split("_")
    model = parts[1] if len(parts) > 1 else raw
    group_key = "_".join(parts[2:]) if len(parts) > 2 else ""
    return format_pipe_key(model, group_key, series, anchor_year)
