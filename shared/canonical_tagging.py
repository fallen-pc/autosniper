"""Canonical Toyota tagging helpers for cross-dataset joins."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence, Tuple

import pandas as pd

from shared.data_loader import dataset_path
from shared.validators import R

UNCLASSIFIED = "UNCLASSIFIED"

AMBIG_BADGE = "[AMBIG_BADGE]"
AMBIG_FUEL = "[AMBIG_FUEL]"
AMBIG_TRANS = "[AMBIG_TRANS]"
AMBIG_DRIVETRAIN = "[AMBIG_DRIVETRAIN]"
OUT_OF_SCOPE = "[OUT_OF_SCOPE]"
POLICY_IMPLICIT_FWD_AU = "POLICY_IMPLICIT_FWD_AU"

ALLOWED_VARIANTS_PATH = Path(__file__).resolve().parent.parent / "config" / "toyota_allowed_variants.csv"
NORMALISATION_RULES_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "toyota_normalisation_rules.csv"
)
TAG_LOG_PATH = dataset_path("quality/canonical_tagging_log.csv")
ELIGIBLE_CANONICAL_REASONS = {"", R.OK, "MATCHED", "NORMALISED_MATCH"}

MAKE_ALIASES = {
    "toyota": "toyota",
}

MODEL_ALIASES = {
    "camry": "camry",
    "corolla": "corolla",
    "hilux": "hilux",
    "hi-lux": "hilux",
    "hiluxsr5": "hilux",
    "rav4": "rav4",
}

TOYOTA_SCOPE_MODELS = {"corolla", "camry", "hilux", "rav4"}
IMPLICIT_FWD_MODELS_AU = {"corolla", "camry"}


def is_canonical_eligible(canonical_tag: object, canonical_reason: object) -> bool:
    tag_text = str(canonical_tag or "").strip()
    if not tag_text or tag_text == UNCLASSIFIED:
        return False
    reason_text = str(canonical_reason or "").strip()
    return reason_text in ELIGIBLE_CANONICAL_REASONS

BODY_ALIASES: Tuple[Tuple[str, str], ...] = (
    ("hatchback", "hatch"),
    ("hatch", "hatch"),
    ("sedan", "sedan"),
    ("saloon", "sedan"),
    ("suv", "suv"),
    ("wagon", "wagon"),
    ("dual cab", "dualcab_ute"),
    ("double cab", "dualcab_ute"),
    ("dualcab", "dualcab_ute"),
    ("ute", "ute"),
    ("cab chassis", "cab_chassis"),
    ("crew cab chassis", "cab_chassis"),
    ("van", "van"),
    ("people mover", "people_mover"),
    ("coupe", "coupe"),
    ("convertible", "convertible"),
    ("bus", "bus"),
)

FUEL_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("diesel", (r"\bdiesel\b",)),
    ("petrol", (r"\bpetrol\b", r"\bunleaded\b", r"\bulp\b", r"\bgasoline\b")),
    ("hybrid", (r"\bhybrid\b",)),
    ("electric", (r"\belectric\b", r"\bev\b")),
)

TRANS_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("auto", (r"\bauto\b", r"\bautomatic\b", r"\bcvt\b", r"\bdct\b")),
    ("manual", (r"\bmanual\b",)),
)

DRIVETRAIN_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("4x4", (r"\b4x4\b", r"\b4wd\b", r"\bawd\b", r"all wheel drive", r"four wheel drive")),
    ("fwd", (r"\bfwd\b", r"front wheel drive")),
    ("rwd", (r"\brwd\b", r"rear wheel drive")),
)

DRIVE_2WD_PATTERN = re.compile(r"\b(2wd|two wheel drive)\b", re.IGNORECASE)
DRIVE_2X4_PATTERN = re.compile(r"\b(2x4|4x2)\b", re.IGNORECASE)

YEAR_PATTERN = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
NON_VEHICLE_PATTERN = re.compile(
    r"motorcycle|motor[-\s]?bike|trailer|boat", re.IGNORECASE
)


@dataclass(frozen=True)
class AllowedVariant:
    canonical_tag: str
    make: str
    model: str
    body: str
    fuel: str
    transmission: str
    badge: str
    series: str
    badge_aliases: Tuple[str, ...]
    body_aliases: Tuple[str, ...]
    excluded_keywords: Tuple[str, ...]


class Normaliser:
    def __init__(self, rules: Mapping[str, Mapping[str, str]]) -> None:
        self._rules = {field: dict(values) for field, values in rules.items()}

    def norm(self, field: str, value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        if not text:
            return ""
        return self._rules.get(field, {}).get(text, text)


def _normalize_key(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _split_pipe(value: object) -> Tuple[str, ...]:
    if value is None:
        return ()
    text = str(value).strip()
    if not text:
        return ()
    return tuple(part.strip().lower() for part in text.split("|") if part.strip())


def _to_int(value: object) -> int:
    if value is None:
        return 0
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _compile_alias(alias: str) -> re.Pattern:
    escaped = re.escape(alias).replace(r"\ ", r"\s+")
    return re.compile(rf"\b{escaped}\b", re.IGNORECASE)


def _alias_in_text(text: str, alias: str) -> bool:
    if not text or not alias:
        return False
    return bool(_compile_alias(alias).search(text))


def _extract_text_blob(row: Mapping[str, object]) -> str:
    parts = []
    for key in ("make", "model", "variant", "body_type", "transmission", "fuel_type", "title", "url"):
        value = row.get(key, "")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            parts.append(text)
    return " ".join(parts).lower()


def _parse_year(value: object, fallback_text: str) -> int | None:
    if value is not None and str(value).strip() != "":
        try:
            return int(float(str(value).strip()))
        except ValueError:
            pass
    match = YEAR_PATTERN.search(fallback_text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _normalize_make(value: object) -> str:
    key = _normalize_key(value)
    return MAKE_ALIASES.get(key, key)


def _normalize_model(value: object) -> str:
    key = _normalize_key(value)
    return MODEL_ALIASES.get(key, key)


def _normalize_body(body_value: object, text_blob: str) -> str:
    candidates = []
    raw = _normalize_text(body_value)
    if raw:
        candidates.append(raw)
    if text_blob:
        candidates.append(text_blob)
    for candidate in candidates:
        for alias, canonical in BODY_ALIASES:
            if _alias_in_text(candidate, alias):
                return canonical
    return ""


def _detect_single(text: str, patterns: Sequence[Tuple[str, Sequence[str]]]) -> str | None:
    hits = []
    for label, rules in patterns:
        for rule in rules:
            if re.search(rule, text, re.IGNORECASE):
                hits.append(label)
                break
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        return "__AMBIG__"
    return None


def _parse_fuel(text: str) -> str | None:
    return _detect_single(text, FUEL_PATTERNS)


def _parse_transmission(text: str) -> str | None:
    return _detect_single(text, TRANS_PATTERNS)


def _parse_drivetrain(text: str) -> str | None:
    return _detect_single(text, DRIVETRAIN_PATTERNS)


def _looks_like_non_vehicle(url: str, text: str) -> bool:
    return bool(NON_VEHICLE_PATTERN.search(f"{url} {text}".lower()))


def _extract_price(row: Mapping[str, object]) -> int | None:
    for key in (
        "price",
        "price_numeric",
        "final_price",
        "final_price_numeric",
        "sale_price",
        "amount",
    ):
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip().replace(",", "")
        if not text:
            continue
        match = re.search(r"\d+", text)
        if not match:
            continue
        try:
            parsed = int(match.group(0))
        except ValueError:
            continue
        if parsed > 0:
            return parsed
    return None


def _build_raw_text_blob(row: Mapping[str, object]) -> str:
    parts = []
    for key in (
        "title",
        "make",
        "model",
        "variant",
        "series",
        "badge",
        "body_type",
        "transmission",
        "fuel_type",
        "drivetrain",
    ):
        value = row.get(key, "")
        if value is None:
            continue
        text = str(value).strip()
        if text:
            parts.append(text)
    return " ".join(parts).lower()


def _derive_drivetrain(row: Mapping[str, object]) -> str:
    blob = str(row.get("_blob") or "")
    drivetrain_raw = str(row.get("drivetrain") or "")
    combined = f"{blob} {drivetrain_raw}".strip().lower()
    if not combined:
        return ""

    parsed = _parse_drivetrain(combined)
    if parsed:
        return parsed

    model = _normalize_model(row.get("model"))
    if model in {"corolla", "camry", "rav4"} and (
        DRIVE_2WD_PATTERN.search(combined) or DRIVE_2X4_PATTERN.search(combined)
    ):
        return "fwd"

    return ""


def _validate_required_fields(row: Mapping[str, object]) -> str:
    if not row.get("year"):
        return R.BAD_PARSE
    if not row.get("fuel_type"):
        return AMBIG_FUEL
    if not row.get("transmission"):
        return AMBIG_TRANS
    if not row.get("badge"):
        return AMBIG_BADGE
    if not row.get("body_type"):
        return R.BAD_PARSE
    return R.OK


def _badge_matches(text: str, aliases: Iterable[str]) -> bool:
    for alias in aliases:
        if _alias_in_text(text, alias):
            return True
    return False


def _body_matches(row_body: str, body_aliases: Iterable[str], body_value: str, text: str) -> bool:
    if row_body and body_value == row_body:
        return True
    for alias in body_aliases:
        if _alias_in_text(text, alias):
            return True
    return False


def _has_excluded_keyword(text: str, keywords: Iterable[str]) -> bool:
    for keyword in keywords:
        if _alias_in_text(text, keyword):
            return True
    return False


@lru_cache(maxsize=1)
def load_allowed_variants(path: Path | None = None) -> Tuple[AllowedVariant, ...]:
    source = path or ALLOWED_VARIANTS_PATH
    if not source.exists():
        return ()
    df = pd.read_csv(source)
    variants: list[AllowedVariant] = []
    for _, row in df.iterrows():
        canonical_tag = _normalize_text(row.get("canonical_tag"))
        if not canonical_tag:
            continue
        make = _normalize_text(row.get("make"))
        model = _normalize_text(row.get("model"))
        body = _normalize_text(row.get("body"))
        fuel = _normalize_text(row.get("fuel"))
        transmission = _normalize_text(row.get("transmission"))
        badge = _normalize_text(row.get("badge"))
        series = _normalize_text(row.get("series"))
        badge_aliases = _split_pipe(row.get("allowed_badge_aliases")) or (badge,)
        body_aliases = _split_pipe(row.get("allowed_body_aliases")) or (body,)
        excluded = _split_pipe(row.get("excluded_keywords"))
        variants.append(
            AllowedVariant(
                canonical_tag=canonical_tag,
                make=make,
                model=model,
                body=body,
                fuel=fuel,
                transmission=transmission,
                badge=badge,
                series=series,
                badge_aliases=badge_aliases,
                body_aliases=body_aliases,
                excluded_keywords=excluded,
            )
        )
    return tuple(variants)


@lru_cache(maxsize=1)
def load_normaliser(path: Path | None = None) -> Normaliser:
    source = path or NORMALISATION_RULES_PATH
    if not source.exists():
        return Normaliser({})
    df = pd.read_csv(source)
    rules: dict[str, dict[str, str]] = {}
    for _, row in df.iterrows():
        field = _normalize_text(row.get("field"))
        raw = _normalize_text(row.get("raw"))
        norm = _normalize_text(row.get("normalised"))
        if not field or not raw:
            continue
        rules.setdefault(field, {})[raw] = norm or raw
    return Normaliser(rules)


def assign_canonical_tag(
    row: Mapping[str, object],
    *,
    require_price: bool = False,
    allowed_variants: Sequence[AllowedVariant] | None = None,
) -> Tuple[str, str, str]:
    url = str(row.get("url", "") or "").strip()
    if not url:
        return UNCLASSIFIED, R.NO_URL, ""
    raw_blob = _build_raw_text_blob(row)
    text_blob = raw_blob
    if _looks_like_non_vehicle(url, text_blob):
        return UNCLASSIFIED, R.NON_VEHICLE, ""
    if require_price and _extract_price(row) is None:
        return UNCLASSIFIED, R.NO_PRICE, ""

    normaliser = load_normaliser()
    normalized_row = dict(row)
    normalized_row["_blob"] = raw_blob
    normalized_row["make"] = normaliser.norm("make", normalized_row.get("make"))
    normalized_row["model"] = normaliser.norm("model", normalized_row.get("model"))
    normalized_row["body_type"] = normaliser.norm("body", normalized_row.get("body_type"))
    normalized_row["transmission"] = normaliser.norm("transmission", normalized_row.get("transmission"))
    normalized_row["fuel_type"] = normaliser.norm("fuel", normalized_row.get("fuel_type"))
    normalized_row["badge"] = normaliser.norm("badge", normalized_row.get("badge"))

    make = _normalize_make(normalized_row.get("make"))
    if make != "toyota":
        return UNCLASSIFIED, OUT_OF_SCOPE, ""
    model = _normalize_model(normalized_row.get("model"))
    if not model:
        return UNCLASSIFIED, R.BAD_PARSE, ""
    if model not in TOYOTA_SCOPE_MODELS:
        return UNCLASSIFIED, OUT_OF_SCOPE, ""

    variants = allowed_variants or load_allowed_variants()
    candidates = [v for v in variants if v.make == make and v.model == model]
    if not candidates:
        return UNCLASSIFIED, OUT_OF_SCOPE, ""

    year = _parse_year(normalized_row.get("year"), text_blob)
    if year is None:
        return UNCLASSIFIED, R.BAD_PARSE, ""

    body_value = _normalize_body(normalized_row.get("body_type"), text_blob)
    if not body_value:
        return UNCLASSIFIED, R.BAD_PARSE, ""
    candidates = [v for v in candidates if _body_matches(v.body, v.body_aliases, body_value, text_blob)]
    if not candidates:
        return UNCLASSIFIED, OUT_OF_SCOPE, ""

    fuel = _parse_fuel(text_blob)
    if fuel in (None, "__AMBIG__"):
        return UNCLASSIFIED, AMBIG_FUEL, ""
    candidates = [v for v in candidates if v.fuel == fuel]
    if not candidates:
        return UNCLASSIFIED, OUT_OF_SCOPE, ""

    transmission = _parse_transmission(text_blob)
    if transmission in (None, "__AMBIG__"):
        return UNCLASSIFIED, AMBIG_TRANS, ""
    candidates = [v for v in candidates if v.transmission == transmission]
    if not candidates:
        return UNCLASSIFIED, OUT_OF_SCOPE, ""

    drivetrain_source = ""

    candidates = [v for v in candidates if not _has_excluded_keyword(text_blob, v.excluded_keywords)]
    if not candidates:
        return UNCLASSIFIED, OUT_OF_SCOPE, ""

    badge_matches = [v for v in candidates if _badge_matches(text_blob, v.badge_aliases)]
    if not badge_matches:
        return UNCLASSIFIED, AMBIG_BADGE, ""
    unique_tags = {v.canonical_tag for v in badge_matches}
    if len(unique_tags) > 1:
        return UNCLASSIFIED, AMBIG_BADGE, ""
    required_reason = _validate_required_fields(
        {
            "year": year,
            "fuel_type": fuel,
            "transmission": transmission,
            "badge": badge_matches[0].badge,
            "body_type": body_value,
        }
    )
    if required_reason != R.OK:
        return UNCLASSIFIED, required_reason, ""
    return badge_matches[0].canonical_tag, R.OK, drivetrain_source


def _snapshot_fields(row: Mapping[str, object]) -> dict[str, object]:
    snapshot_keys = (
        "year",
        "make",
        "model",
        "variant",
        "body_type",
        "transmission",
        "fuel_type",
        "price",
        "location",
    )
    return {key: row.get(key, "") for key in snapshot_keys}


def _append_tag_log(rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        return
    TAG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = TAG_LOG_PATH.exists()
    df = pd.DataFrame(rows)
    df.to_csv(TAG_LOG_PATH, mode="a", header=not file_exists, index=False)


def tag_dataframe(
    df: pd.DataFrame,
    *,
    source: str,
    require_price: bool = False,
    filter_unclassified: bool = False,
    append_log: bool = True,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df.copy() if df is not None else pd.DataFrame()

    variants = load_allowed_variants()
    tags: list[str] = []
    reasons: list[str] = []
    drivetrain_sources: list[str] = []
    log_rows: list[dict[str, object]] = []
    timestamp = datetime.utcnow().isoformat(timespec="seconds")

    for _, row in df.iterrows():
        row_map = row.to_dict()
        tag, reason, drivetrain_source = assign_canonical_tag(
            row_map, require_price=require_price, allowed_variants=variants
        )
        tags.append(tag)
        reasons.append(reason)
        drivetrain_sources.append(drivetrain_source)
        if tag == UNCLASSIFIED and append_log:
            log_rows.append(
                {
                    "timestamp": timestamp,
                    "source": source,
                    "url": row_map.get("url", ""),
                    "reason_code": reason,
                    "field_snapshot": json.dumps(_snapshot_fields(row_map), ensure_ascii=True),
                }
            )

    tagged = df.copy()
    tagged["canonical_tag"] = tags
    tagged["canonical_reason"] = reasons
    tagged["drivetrain_source"] = drivetrain_sources
    if filter_unclassified:
        tagged = tagged[tagged["canonical_tag"] != UNCLASSIFIED].copy()

    if append_log:
        _append_tag_log(log_rows)
    return tagged
