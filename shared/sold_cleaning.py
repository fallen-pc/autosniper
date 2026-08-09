"""Reusable helpers for cleaning scraped sold-car rows."""

from __future__ import annotations

import re

import pandas as pd

from shared.schema import (
    DISALLOWED_MAKE_PATTERNS,
    DISALLOWED_MAKE_VALUES,
    SOLD_LISTING_SCHEMA,
    SOLD_RAW_SCRAPE_COLUMNS,
)

DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
FUEL_MAP = {
    "petrol": {"petrol", "gasoline", "unleaded", "gas"},
    "diesel": {"diesel", "turbo diesel", "tdi"},
    "electric": {"electric", "ev"},
    "hybrid": {"hybrid", "phev", "plugin hybrid"},
}
TRANSMISSION_PATTERN = re.compile(r"\b(\d+[- ]*speed|automatic|manual|auto|man)\b", re.IGNORECASE)
SEAT_PATTERN = re.compile(r"\b\d+\s*seats?\b", re.IGNORECASE)
KMS_PATTERN = re.compile(r"\b\d[\d\s,]*k?ms?\b", re.IGNORECASE)
EX_GOV_PATTERN = re.compile(r"\(\s*ex-?gov\s*\)", re.IGNORECASE)
CERT_PATTERN = re.compile(r"\(?\s*(pinkslip|rwc)\s+issued[^,;)]*\)?", re.IGNORECASE)
COMP_PATTERN = re.compile(r"\(\s*(comp|complied)[^)]*\)?", re.IGNORECASE)
COMP_BARE_PATTERN = re.compile(r"\b(comp|complied)\b", re.IGNORECASE)
YEAR_PAREN_PATTERN = re.compile(r"\(\s*\d{4}[^)]*\)?")
COMPLIANCE_SLUG_PATTERN = re.compile(r"(?:^|-)comp(?:-|$)|complied", re.IGNORECASE)
COMPLIANCE_NOTE_PATTERN = re.compile(r"\bcomplied\s+for\s+\d+(?:\s+seats?)?(?:[^\n.;]*)", re.IGNORECASE)
SPARSE_THRESHOLD = 6
BODY_KEYWORD_ALIASES = {
    "wagon": ["wagon"],
    "hatchback": ["hatchback", "hatch"],
    "people mover": ["people mover", "people-mover"],
    "crew cab chassis": ["crew cab chassis", "crew chassis", "crew cab"],
    "bus": ["bus"],
    "cab chassis": ["cab chassis", "cab-chassis", "chassis"],
    "dual cab": ["dual cab", "dual-cab", "dualcab"],
    "ute": ["ute", "pick-up", "pickup"],
    "coupe": ["coupe"],
    "sedan": ["sedan"],
    "convertible": ["convertible"],
}
CANONICAL_BODY_LABELS = {
    "wagon": "Wagon",
    "hatchback": "Hatchback",
    "people mover": "People Mover",
    "crew cab chassis": "Crew Cab Chassis",
    "bus": "Bus",
    "cab chassis": "Cab Chassis",
    "dual cab": "Dual Cab",
    "ute": "Ute",
    "coupe": "Coupe",
    "sedan": "Sedan",
    "convertible": "Convertible",
}


def clean_date_sold(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    text = re.sub(r"(?i)^closed:\s*", "", text)
    match = DATE_RE.search(text)
    if match:
        return match.group(1)
    return text


def normalize_fuel_type(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    text = text.replace("turbo", "").replace("t/diesel", "diesel")
    text = re.sub(r"[^a-z]", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    for fuel, aliases in FUEL_MAP.items():
        if any(alias in text for alias in aliases):
            return fuel.capitalize()
    return text.capitalize() if text else ""


def normalize_transmission(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value)
    text = re.sub(r"\b\d+[- ]*speed\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[,/]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    words = text.lower().split()
    if "cvt" in words:
        return "CVT"
    if "auto" in words or "automatic" in words:
        return "Automatic"
    if "manual" in words or "man" in words:
        return "Manual"
    return text.title()


def remove_transmission_from_variant(variant: object, transmission: object) -> str:
    if not variant:
        return ""
    text = str(variant)
    transmission_text = str(transmission or "").lower()
    if not transmission_text:
        return text
    keywords = []
    if "automatic" in transmission_text or "auto" in transmission_text:
        keywords.extend(["automatic", "auto"])
    if "manual" in transmission_text or "man" in transmission_text:
        keywords.extend(["manual", "man"])
    if "cvt" in transmission_text:
        keywords.append("cvt")
    if keywords:
        pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE)
        text = pattern.sub("", text)
    text = re.sub(r"\b\d+\s*[-/]?\s*speed\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[,/]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,-/")
    return text


def remove_fuel_from_variant(variant: object, fuel_type: object) -> str:
    if not variant:
        return ""
    text = str(variant)
    fuel = (fuel_type or "").lower()
    keywords = []
    if "diesel" in fuel:
        keywords.extend(["diesel", "turbo diesel"])
    if not keywords:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE)
    text = pattern.sub("", text)
    text = re.sub(r"[,/]+", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,-/")
    return text


def remove_seat_count(value: object) -> str:
    if not value:
        return ""
    text = re.sub(SEAT_PATTERN, "", str(value))
    text = re.sub(KMS_PATTERN, "", text)
    text = EX_GOV_PATTERN.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,-/")
    return text


def remove_cert_notes(value: object) -> str:
    if not value:
        return ""
    text = CERT_PATTERN.sub("", str(value))
    text = re.sub(r"\s{2,}", " ", text).strip(" ,-/")
    return text


def remove_compliance_markers(value: object) -> str:
    if not value:
        return ""
    text = str(value)
    text = COMP_PATTERN.sub("", text)
    text = COMP_BARE_PATTERN.sub("", text)
    text = YEAR_PAREN_PATTERN.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,-/")
    return text


def remove_compliance_notes(value: object) -> str:
    if not value:
        return ""
    text = str(value)
    text = COMPLIANCE_NOTE_PATTERN.sub("", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,;:-")
    return text


def is_compliance_slug(value: object) -> bool:
    if not value:
        return False
    slug = str(value).strip().rstrip("/").rsplit("/", 1)[-1].lower()
    if not slug:
        return False
    return bool(COMPLIANCE_SLUG_PATTERN.search(slug))


def normalize_odometer_display(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    cleaned = text.replace(",", "")
    match = re.search(r"[-+]?\d*\.?\d+(?:e[+-]?\d+)?", cleaned, flags=re.IGNORECASE)
    if match:
        try:
            numeric = float(match.group(0))
        except ValueError:
            numeric = None
    else:
        numeric = None
    if numeric is None:
        digits = re.sub(r"[^\d]", "", text)
        if not digits:
            return ""
        try:
            numeric = float(digits)
        except ValueError:
            return ""
    if numeric < 0:
        numeric = abs(numeric)
    while numeric > 2_000_000:
        numeric = numeric / 10.0
    return str(int(round(numeric)))


def normalize_engine_capacity(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    text = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return text
    num = float(match.group(1))
    if num >= 100:
        num = num / 1000.0
    formatted = f"{num:.1f}".rstrip("0").rstrip(".")
    return formatted


def clean_rego_expiry(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    text = re.sub(
        r"Registration will only be transferred.*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(r"\s*-\s*$", "", text).strip()
    lowered = text.lower()
    if "sold unregistered" in lowered or "unregistered" in lowered or "without plates" in lowered:
        return "Unregistered"
    return text


def normalize_listing_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize listing fields to the shared sold-listing rules."""
    working = df.copy()
    if "url" in working.columns:
        drop_mask = working["url"].apply(is_compliance_slug)
        if drop_mask.any():
            working = working.loc[~drop_mask].copy()
    if "general_condition" in working.columns:
        working["general_condition"] = working["general_condition"].apply(remove_compliance_notes)
    if "referral_reason" in working.columns:
        working["referral_reason"] = working["referral_reason"].apply(remove_compliance_notes)
    if "make" in working.columns:
        working["make"] = working["make"].apply(
            lambda v: remove_compliance_markers("" if pd.isna(v) else str(v).strip())
        )
        drop_mask = pd.Series(False, index=working.index)
        if DISALLOWED_MAKE_VALUES:
            drop_mask |= working["make"].str.lower().isin(DISALLOWED_MAKE_VALUES)
        if DISALLOWED_MAKE_PATTERNS:
            for pattern in DISALLOWED_MAKE_PATTERNS:
                drop_mask |= working["make"].str.contains(pattern, regex=True, case=False, na=False)
        if drop_mask.any():
            working = working.loc[~drop_mask].copy()
        working["make"] = working["make"].str.upper()
    if "model" in working.columns:
        working["model"] = working["model"].apply(
            lambda v: remove_compliance_markers("" if pd.isna(v) else str(v).strip())
        )
        working["model"] = working["model"].apply(lambda text: text[:1].upper() + text[1:].lower() if text else "")
    if "vin" in working.columns:
        working["vin"] = working["vin"].apply(lambda v: "" if pd.isna(v) else str(v).strip().upper())

    if "fuel_type" in working.columns:
        working["fuel_type"] = working["fuel_type"].apply(normalize_fuel_type)

    if "transmission" in working.columns:
        working["transmission"] = working["transmission"].apply(normalize_transmission)
    if "transmission" in working.columns and "variant" in working.columns:
        working["transmission"] = working.apply(
            lambda row: row["transmission"]
            if str(row.get("transmission") or "").strip()
            else ("Automatic" if re.search(r"\bauto\b|automatic", str(row.get("variant") or ""), re.IGNORECASE) else ""),
            axis=1,
        )

    if "odometer_reading" in working.columns:
        working["odometer_reading"] = working["odometer_reading"].apply(normalize_odometer_display)
    if "engine_capacity" in working.columns:
        working["engine_capacity"] = working["engine_capacity"].apply(normalize_engine_capacity)

    if "rego_expiry" in working.columns:
        working["rego_expiry"] = working["rego_expiry"].apply(clean_rego_expiry)
        working["rego_expiry"] = working["rego_expiry"].apply(
            lambda v: v if v else "Unregistered"
        )
    if "rego_no" in working.columns:
        working["rego_no"] = working["rego_no"].apply(lambda v: str(v).strip() if v not in (None, "") else "No plates")

    if "variant" in working.columns and "transmission" in working.columns:
        working["variant"] = working.apply(
            lambda row: remove_transmission_from_variant(row["variant"], row["transmission"]),
            axis=1,
        )
    if "variant" in working.columns and "fuel_type" in working.columns:
        working["variant"] = working.apply(
            lambda row: remove_fuel_from_variant(row["variant"], row["fuel_type"]),
            axis=1,
        )
    if "variant" in working.columns:
        working["variant"] = working["variant"].apply(remove_seat_count)
        working["variant"] = working["variant"].apply(remove_cert_notes)
        working["variant"] = working["variant"].apply(remove_compliance_markers)
    if "body_type" in working.columns and "variant" in working.columns:
        body_variant = working.apply(_apply_body_rules, axis=1, result_type="expand")
        working["body_type"] = body_variant[0]
        working["variant"] = body_variant[1]

    if "vin" in working.columns and "odometer_reading" in working.columns:
        working["_vin_norm"] = working["vin"].astype(str).str.strip().str.lower().replace("", pd.NA)
        working["_odo_norm"] = working["odometer_reading"].astype(str).str.strip()
        working["_price_norm"] = ""
        for price_col in ("final_price", "price", "sold_price", "hammer_price"):
            if price_col in working.columns:
                working["_price_norm"] = working["_price_norm"].where(
                    working["_price_norm"].astype(bool),
                    working[price_col].astype(str).str.replace(r"[^\d.]", "", regex=True),
                )
        valid = (
            working["_vin_norm"].notna()
            & working["_odo_norm"].astype(bool)
            & working["_price_norm"].astype(bool)
        )
        if valid.any():
            if "date_sold" in working.columns:
                working["_dup_sort"] = pd.to_datetime(working["date_sold"], errors="coerce")
                working = working.sort_values(by="_dup_sort", kind="mergesort")
                working.drop(columns=["_dup_sort"], inplace=True)
            duplicate_mask = valid & working.duplicated(
                subset=["_vin_norm", "_odo_norm", "_price_norm"],
                keep="last",
            )
            if duplicate_mask.any():
                working = working.loc[~duplicate_mask].copy()
        working.drop(columns=["_vin_norm", "_odo_norm", "_price_norm"], inplace=True)

    return working


def ensure_schema(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    for column in SOLD_RAW_SCRAPE_COLUMNS:
        if column not in working.columns:
            working[column] = None
    trimmed = working[SOLD_RAW_SCRAPE_COLUMNS].copy()
    if "time_remaining_or_date_sold" in trimmed.columns:
        trimmed["date_sold"] = trimmed["time_remaining_or_date_sold"].apply(clean_date_sold)
        trimmed.drop(columns=["time_remaining_or_date_sold"], inplace=True)
    else:
        trimmed["date_sold"] = ""
    trimmed = normalize_listing_fields(trimmed)

    columns_to_remove = [
        "build_date",
        "compliance_date",
        "status",
        "rego_state",
        "no_of_plates",
        "odometer_unit",
        "features_list",
    ]
    trimmed.drop(columns=[col for col in columns_to_remove if col in trimmed.columns], inplace=True)
    ordered = [col for col in SOLD_LISTING_SCHEMA if col in trimmed.columns]
    ordered += [col for col in trimmed.columns if col not in ordered]
    return trimmed[ordered]


def drop_sparse_rows(df: pd.DataFrame, threshold: int = SPARSE_THRESHOLD) -> pd.DataFrame:
    def _is_missing(value: object) -> bool:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return True
        if isinstance(value, str) and not value.strip():
            return True
        return False

    mask = df.apply(lambda row: sum(_is_missing(val) for val in row), axis=1) < threshold
    return df[mask].reset_index(drop=True)


def drop_invalid_years(df: pd.DataFrame, *, allow_missing: bool = False) -> pd.DataFrame:
    if "year" not in df.columns:
        return df
    def _parse_year(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.endswith(".0"):
                text = text[:-2]
            if not YEAR_RE.match(text):
                return None
            try:
                return int(text)
            except ValueError:
                return None
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        if pd.isna(num) or not num.is_integer():
            return None
        year = int(num)
        if 1900 <= year <= 2099:
            return year
        return None

    def _is_missing(value: object) -> bool:
        if value is None:
            return True
        text = str(value).strip().lower()
        return text in {"", "nan", "none"}

    def _is_valid(value: object) -> bool:
        if allow_missing and _is_missing(value):
            return True
        return _parse_year(value) is not None

    mask = df["year"].apply(_is_valid)
    return df[mask].reset_index(drop=True)


def drop_invalid_odometer_rows(df: pd.DataFrame, *, allow_missing: bool = False) -> pd.DataFrame:
    if "odometer_reading" not in df.columns:
        return df
    series = df["odometer_reading"].astype(str).str.strip()
    mask = series.str.len() > 0
    mask &= series != "0"
    if allow_missing:
        missing_mask = series.eq("") | series.str.lower().isin({"nan", "none", "0"})
        mask = mask | missing_mask
    return df[mask].reset_index(drop=True)


def _apply_body_rules(row: pd.Series) -> tuple[str, str]:
    body = str(row.get("body_type") or "").strip()
    variant = str(row.get("variant") or "").strip()
    body_lower = body.lower()
    variant_lower = variant.lower()
    canonical: str | None = None

    for key, aliases in BODY_KEYWORD_ALIASES.items():
        if any(alias in body_lower for alias in aliases):
            canonical = key
            break

    if canonical is None:
        for key, aliases in BODY_KEYWORD_ALIASES.items():
            if any(alias in variant_lower for alias in aliases):
                canonical = key
                body = CANONICAL_BODY_LABELS.get(key, key.title())
                body_lower = body.lower()
                break

    if canonical:
        aliases = BODY_KEYWORD_ALIASES[canonical]
        pattern = re.compile(r"\b(" + "|".join(re.escape(alias) for alias in aliases) + r")\b", re.IGNORECASE)
        variant = pattern.sub("", variant).strip(" ,-/")
        variant = re.sub(r"\s{2,}", " ", variant)
        body = CANONICAL_BODY_LABELS.get(canonical, canonical.title())

    return body, variant
