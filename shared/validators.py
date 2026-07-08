"""Validation helpers for critical CSV datasets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

import pandas as pd
from dateutil import parser as date_parser

VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
MOTORCYCLE_PATTERN = re.compile(r"motorcycle|motor[-\\s]?bike|motor\\s*cycle", re.IGNORECASE)
TRAILER_PATTERN = re.compile(r"trailer", re.IGNORECASE)
BOAT_PATTERN = re.compile(r"boat", re.IGNORECASE)
PRICE_PER_KM_BUCKET_SIZE = 0.05
TIME_TOKEN_PATTERN = re.compile(
    r"(\d+)\s*(d|day|days|h|hour|hours|m|min|minute|minutes|s|sec|second|seconds)",
    re.IGNORECASE,
)
DATE_SOLD_HINT = re.compile(r"\b\d{1,2}\s+[A-Za-z]+\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AU_TZINFOS = {"AEST": 10 * 3600, "AEDT": 11 * 3600}


class R:
    # URL / fetch
    NO_URL = "[NO_URL]"
    BAD_URL = "[BAD_URL]"
    DUPLICATE_URL = "[DUPLICATE_URL]"
    DEAD_URL = "[DEAD_URL]"
    FETCH_FAIL = "[FETCH_FAIL]"
    BAD_PARSE = "[BAD_PARSE]"

    # Auction state (active)
    NO_TIME = "[NO_TIME]"
    EXPIRED_UNSOLD = "[EXPIRED_UNSOLD]"
    WITHDRAWN = "[WITHDRAWN]"
    SOLD_DETECTED = "[SOLD_DETECTED]"

    # Required fields
    MISSING_YEAR = "[MISSING_YEAR]"
    BAD_YEAR = "[BAD_YEAR]"
    BAD_YEAR_RANGE = "[BAD_YEAR_RANGE]"
    MISSING_MAKE = "[MISSING_MAKE]"
    BAD_MAKE = "[BAD_MAKE]"
    MISSING_MODEL = "[MISSING_MODEL]"
    MISSING_BODY_TYPE = "[MISSING_BODY_TYPE]"
    MISSING_TRANSMISSION = "[MISSING_TRANSMISSION]"
    MISSING_FUEL_TYPE = "[MISSING_FUEL_TYPE]"
    MISSING_LOCATION = "[MISSING_LOCATION]"

    # Odometer / numeric hygiene
    MISSING_ODOMETER = "[MISSING_ODOMETER]"
    BAD_ODOMETER = "[BAD_ODOMETER]"
    BAD_ODOMETER_RANGE = "[BAD_ODOMETER_RANGE]"
    SUSPECT_ODOMETER = "[SUSPECT_ODOMETER]"

    # VIN / identity
    MISSING_VIN = "[MISSING_VIN]"
    BAD_VIN = "[BAD_VIN]"

    # Sold-only validity
    NO_PRICE = "[NO_PRICE]"
    BAD_PRICE = "[BAD_PRICE]"
    NO_DATE_SOLD = "[NO_DATE_SOLD]"
    BAD_DATE_SOLD = "[BAD_DATE_SOLD]"
    BAD_BIDS = "[BAD_BIDS]"

    # Non-vehicle / scope filters
    NON_VEHICLE = "[NON_VEHICLE]"
    MOTORCYCLE = "[MOTORCYCLE]"
    TRAILER = "[TRAILER]"
    BOAT = "[BOAT]"
    NON_VIC = "[NON_VIC]"

    # Manual / admin
    MANUAL_EXCLUDE = "[MANUAL_EXCLUDE]"
    TEST_ROW = "[TEST_ROW]"

    OK = "[OK]"


@dataclass(frozen=True)
class ValidatorConfig:
    make_whitelist: set[str]
    enforce_vic_only: bool = False
    allow_suspect_odometer: bool = False
    odo_min: int = 1000
    odo_max: int = 700_000
    year_min: int = 1950
    year_max_offset: int = 1
    allowed_body_types: Optional[set[str]] = None


def _s(value: object) -> str:
    return "" if value is None else str(value).strip()


def _upper(value: object) -> str:
    return _s(value).upper()


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    if not text:
        return True
    return text.lower() in {"nan", "none", "n/a"}


def _parse_signed_int(value: object) -> int | None:
    if _is_blank(value):
        return None
    text = str(value).strip().replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return int(round(float(match.group(0))))
    except ValueError:
        return None


def _parse_non_negative_int(value: object) -> int | None:
    parsed = _parse_signed_int(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _parse_year(value: object) -> int | None:
    parsed = _parse_non_negative_int(value)
    if parsed is None:
        return None
    current_year = datetime.utcnow().year
    if 1950 <= parsed <= current_year + 1:
        return parsed
    return None


def _parse_price(value: object) -> int | None:
    parsed = _parse_non_negative_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _parse_date_iso(value: object) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    if ISO_DATE_RE.match(text):
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    try:
        parsed = date_parser.parse(text, fuzzy=True, dayfirst=True, tzinfos=AU_TZINFOS)
    except (ValueError, TypeError):
        return None
    return parsed.date().isoformat()


def _build_stats(rows_in: int, rows_out: int) -> Dict[str, int]:
    return {
        "rows_in": int(rows_in),
        "rows_out": int(rows_out),
        "rows_dropped": int(max(rows_in - rows_out, 0)),
    }


def _looks_like_non_vehicle(url: str, extra_text: str = "") -> str | None:
    haystack = f"{url} {extra_text}".lower()
    if MOTORCYCLE_PATTERN.search(haystack):
        return R.MOTORCYCLE
    if TRAILER_PATTERN.search(haystack):
        return R.TRAILER
    if BOAT_PATTERN.search(haystack):
        return R.BOAT
    return None


def _parse_time_or_sold(value: object) -> tuple[str | None, str | None]:
    if _is_blank(value):
        return None, None
    text = str(value).strip()
    if TIME_TOKEN_PATTERN.search(text):
        return "countdown", None
    if DATE_SOLD_HINT.search(text):
        return "sold", text
    return None, None


def _normalize_location(value: object) -> str:
    return _upper(value)


def validate_static_row(row: Dict[str, object], cfg: ValidatorConfig) -> tuple[bool, str, Dict[str, object]]:
    clean = dict(row)
    url = _s(clean.get("url"))
    if not url:
        return False, R.NO_URL, clean
    if not url.startswith("http"):
        return False, R.BAD_URL, clean
    clean["url"] = url

    non_vehicle_reason = _looks_like_non_vehicle(url, _s(clean.get("variant")))
    if non_vehicle_reason:
        return False, non_vehicle_reason, clean

    year_text = _s(clean.get("year"))
    if not year_text:
        return False, R.MISSING_YEAR, clean
    year_val = _parse_signed_int(year_text)
    if year_val is None:
        return False, R.BAD_YEAR, clean
    year_max = datetime.utcnow().year + cfg.year_max_offset
    if year_val < cfg.year_min or year_val > year_max:
        return False, R.BAD_YEAR_RANGE, clean
    clean["year"] = year_val

    make_text = _s(clean.get("make"))
    if not make_text:
        return False, R.MISSING_MAKE, clean
    make_value = _upper(make_text)
    if cfg.make_whitelist and make_value not in cfg.make_whitelist:
        return False, R.BAD_MAKE, clean
    clean["make"] = make_value

    model_text = _s(clean.get("model"))
    if not model_text:
        return False, R.MISSING_MODEL, clean
    clean["model"] = model_text

    body_text = _s(clean.get("body_type"))
    if not body_text:
        return False, R.MISSING_BODY_TYPE, clean
    if cfg.allowed_body_types:
        allowed_map = {str(value).strip().lower(): str(value).strip() for value in cfg.allowed_body_types}
        body_key = body_text.strip().lower()
        if body_key not in allowed_map:
            return False, R.BAD_PARSE, clean
        clean["body_type"] = allowed_map[body_key]
    else:
        clean["body_type"] = body_text

    transmission_text = _s(clean.get("transmission"))
    if not transmission_text:
        return False, R.MISSING_TRANSMISSION, clean
    clean["transmission"] = transmission_text

    fuel_text = _s(clean.get("fuel_type"))
    if not fuel_text:
        return False, R.MISSING_FUEL_TYPE, clean
    clean["fuel_type"] = fuel_text

    location_text = _s(clean.get("location"))
    if not location_text:
        return False, R.MISSING_LOCATION, clean
    location_value = _normalize_location(location_text)
    if cfg.enforce_vic_only and location_value != "VIC":
        return False, R.NON_VIC, clean
    clean["location"] = location_value

    odo_text = _s(clean.get("odometer_reading"))
    if not odo_text:
        return False, R.MISSING_ODOMETER, clean
    odo_value = _parse_signed_int(odo_text)
    if odo_value is None:
        return False, R.BAD_ODOMETER, clean
    if odo_value < cfg.odo_min or odo_value > cfg.odo_max:
        if cfg.allow_suspect_odometer:
            clean["odometer_reading"] = None
            clean["odo_suspect"] = 1
        else:
            return False, R.BAD_ODOMETER_RANGE, clean
    else:
        clean["odometer_reading"] = odo_value
        clean["odo_suspect"] = 0

    vin_value = _upper(clean.get("vin"))
    if vin_value:
        if not VIN_RE.match(vin_value):
            return False, R.BAD_VIN, clean
        clean["vin"] = vin_value
    else:
        clean["vin"] = ""

    return True, R.OK, clean


def validate_active_row(row: Dict[str, object], cfg: ValidatorConfig) -> tuple[bool, str, Dict[str, object]]:
    ok, reason, clean = validate_static_row(row, cfg)
    if not ok:
        return False, reason, clean

    time_value = clean.get("time_remaining_or_date_sold")
    kind, _ = _parse_time_or_sold(time_value)
    if kind is None:
        return False, R.NO_TIME, clean
    if kind == "sold":
        return False, R.SOLD_DETECTED, clean

    clean["status"] = "active"
    return True, R.OK, clean


def validate_sold_row(row: Dict[str, object], cfg: ValidatorConfig) -> tuple[bool, str, Dict[str, object]]:
    clean = dict(row)
    url = _s(clean.get("url"))
    if not url:
        return False, R.NO_URL, clean
    if not url.startswith("http"):
        return False, R.BAD_URL, clean
    clean["url"] = url

    if "sold-test" in url.lower() or _s(clean.get("year")).lower() == "test":
        return False, R.TEST_ROW, clean
    make_text = _s(clean.get("make")).lower()
    model_text = _s(clean.get("model")).lower()
    if make_text == "test" and model_text == "test":
        return False, R.TEST_ROW, clean

    year_text = _s(clean.get("year"))
    if not year_text:
        return False, R.MISSING_YEAR, clean
    year_val = _parse_signed_int(year_text)
    if year_val is None:
        return False, R.BAD_YEAR, clean
    year_max = datetime.utcnow().year + cfg.year_max_offset
    if year_val < cfg.year_min or year_val > year_max:
        return False, R.BAD_YEAR_RANGE, clean
    clean["year"] = year_val

    price_text = _s(clean.get("price"))
    if not price_text:
        return False, R.NO_PRICE, clean
    price_val = _parse_non_negative_int(price_text)
    if price_val is None or price_val <= 0:
        return False, R.BAD_PRICE, clean
    clean["price"] = price_val

    date_candidate = _s(clean.get("date_sold") or clean.get("time_remaining_or_date_sold"))
    if not date_candidate:
        return False, R.NO_DATE_SOLD, clean
    date_sold = _parse_date_iso(date_candidate)
    if date_sold is None:
        return False, R.BAD_DATE_SOLD, clean
    clean["date_sold"] = date_sold

    bids_text = _s(clean.get("bids"))
    if bids_text:
        bids_val = _parse_signed_int(bids_text)
        if bids_val is None or bids_val < 0:
            return False, R.BAD_BIDS, clean
        clean["bids"] = bids_val
    elif "bids" in clean:
        clean["bids"] = 0

    odo_text = _s(clean.get("odometer_reading"))
    if odo_text:
        odo_val = _parse_signed_int(odo_text)
        if odo_val is None:
            if cfg.allow_suspect_odometer:
                clean["odometer_reading"] = None
                clean["odo_suspect"] = 1
            else:
                return False, R.BAD_ODOMETER, clean
        else:
            if odo_val < cfg.odo_min or odo_val > cfg.odo_max:
                if cfg.allow_suspect_odometer:
                    clean["odometer_reading"] = None
                    clean["odo_suspect"] = 1
                else:
                    return False, R.BAD_ODOMETER_RANGE, clean
            else:
                clean["odometer_reading"] = odo_val
                clean["odo_suspect"] = 0
    else:
        clean["odometer_reading"] = None
        clean["odo_suspect"] = 1 if cfg.allow_suspect_odometer else 0

    vin_value = _upper(clean.get("vin"))
    if vin_value and not VIN_RE.match(vin_value):
        return False, R.BAD_VIN, clean
    clean["vin"] = vin_value

    location_value = _normalize_location(clean.get("location"))
    if cfg.enforce_vic_only and location_value and location_value != "VIC":
        return False, R.NON_VIC, clean
    clean["location"] = location_value

    return True, R.OK, clean


def validate_vehicle_static_df(
    df: pd.DataFrame,
    *,
    strict: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if df is None or df.empty:
        return df, _build_stats(0, 0)

    required = ("url", "year", "make", "model", "odometer_reading")
    missing = [col for col in required if col not in df.columns]
    if missing:
        if strict:
            raise ValueError(
                f"vehicle_static_details.csv missing required columns: {', '.join(missing)}"
            )
        return df.copy(), _build_stats(len(df), len(df))

    working = df.copy()
    url_series = working["url"].astype(str).str.strip()
    invalid_mask = url_series.eq("") | url_series.str.contains(MOTORCYCLE_PATTERN, na=False)

    make_series = working["make"].astype(str).str.strip()
    model_series = working["model"].astype(str).str.strip()
    invalid_mask |= make_series.eq("") | model_series.eq("")

    year_series = pd.to_numeric(working["year"].apply(_parse_year), errors="coerce")
    invalid_mask |= year_series.isna()

    odo_series = pd.to_numeric(
        working["odometer_reading"].apply(_parse_non_negative_int),
        errors="coerce",
    )
    invalid_mask |= odo_series.isna()
    invalid_mask |= (odo_series < 1000) | (odo_series > 700000)

    if "vin" in working.columns:
        vin_series = working["vin"].fillna("").astype(str).str.strip().str.upper()
        invalid_mask |= (vin_series != "") & ~vin_series.str.match(VIN_RE)
        working["vin"] = vin_series

    cleaned = working.loc[~invalid_mask].copy()
    cleaned["year"] = year_series.loc[cleaned.index].astype(int)
    cleaned["odometer_reading"] = odo_series.loc[cleaned.index].astype(int)
    return cleaned, _build_stats(len(df), len(cleaned))


def validate_sold_cars_df(
    df: pd.DataFrame,
    *,
    strict: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if df is None or df.empty:
        return df, _build_stats(0, 0)

    working = df.copy()
    if "date_sold" not in working.columns:
        if "time_remaining_or_date_sold" in working.columns:
            working["date_sold"] = working["time_remaining_or_date_sold"]
        else:
            if strict:
                raise ValueError("sold_cars.csv missing required column: date_sold")
            return working, _build_stats(len(df), len(df))

    required = ("price", "date_sold", "odometer_reading")
    missing = [col for col in required if col not in working.columns]
    if missing:
        if strict:
            raise ValueError(f"sold_cars.csv missing required columns: {', '.join(missing)}")
        return working, _build_stats(len(df), len(df))

    date_candidate = working["date_sold"]
    if "time_remaining_or_date_sold" in working.columns:
        fallback = working["time_remaining_or_date_sold"]
        blank_mask = date_candidate.apply(_is_blank)
        date_candidate = date_candidate.where(~blank_mask, fallback)

    price_series = pd.to_numeric(working["price"].apply(_parse_price), errors="coerce")
    date_series = date_candidate.apply(_parse_date_iso)
    odo_series = pd.to_numeric(
        working["odometer_reading"].apply(_parse_non_negative_int),
        errors="coerce",
    )
    bids_series = (
        pd.to_numeric(working["bids"].apply(_parse_signed_int), errors="coerce")
        if "bids" in working.columns
        else pd.Series(0, index=working.index)
    )

    invalid_mask = price_series.isna() | date_series.isna() | odo_series.isna()
    invalid_mask |= (price_series <= 0)
    invalid_mask |= (odo_series < 1000) | (odo_series > 700000)
    if bids_series is not None:
        invalid_mask |= bids_series.fillna(0) < 0

    cleaned = working.loc[~invalid_mask].copy()
    cleaned["price"] = price_series.loc[cleaned.index].astype(int)
    cleaned["date_sold"] = date_series.loc[cleaned.index]
    cleaned["odometer_reading"] = odo_series.loc[cleaned.index].astype(int)
    if "bids" in cleaned.columns:
        cleaned["bids"] = bids_series.loc[cleaned.index].fillna(0).astype(int)
    return cleaned, _build_stats(len(df), len(cleaned))
