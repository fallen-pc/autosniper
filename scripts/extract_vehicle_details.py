from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import time
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
    from shared.schema import SOLD_RAW_SCRAPE_COLUMNS, STATIC_VEHICLE_SCHEMA
    from shared.sold_cleaning import (
        drop_invalid_odometer_rows,
        drop_invalid_years,
        drop_sparse_rows,
        normalize_listing_fields,
        remove_compliance_markers,
    )
    from shared.canonical_tagging import ELIGIBLE_CANONICAL_REASONS, UNCLASSIFIED, tag_dataframe
    from shared.validators import ValidatorConfig, validate_static_row
    from shared.validators import validate_vehicle_static_df
    from shared.exclusions import append_pipeline_exclusions
else:
    from shared.data_loader import dataset_path
    from shared.schema import SOLD_RAW_SCRAPE_COLUMNS, STATIC_VEHICLE_SCHEMA
    from shared.sold_cleaning import (
        drop_invalid_odometer_rows,
        drop_invalid_years,
        drop_sparse_rows,
        normalize_listing_fields,
        remove_compliance_markers,
    )
    from shared.canonical_tagging import ELIGIBLE_CANONICAL_REASONS, UNCLASSIFIED, tag_dataframe
    from shared.validators import ValidatorConfig, validate_static_row
    from shared.validators import validate_vehicle_static_df
    from shared.exclusions import append_pipeline_exclusions

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
INPUT_FILE = dataset_path("active_vehicle_links.csv")
RAW_OUTPUT_FILE = dataset_path("raw_vehicle_data.csv")
NORMALIZED_OUTPUT_FILE = dataset_path("normalised_data.csv")
OUTPUT_FILE = dataset_path("vehicle_static_details.csv")
ACTIVE_OUTPUT_FILE = dataset_path("active_vehicle_details.csv")
FAILURES_FILE = dataset_path("excluded_listings.csv")
ACTIVE_LINKS_FILE = dataset_path("active_vehicle_links.csv")
SKIPPED_LOG = ROOT_DIR / "logs" / "skipped_links.txt"

SCHEMA_FIELDS = SOLD_RAW_SCRAPE_COLUMNS.copy()
STATIC_OUTPUT_COLUMNS = list(
    dict.fromkeys(list(STATIC_VEHICLE_SCHEMA) + ["canonical_tag", "canonical_reason"])
)
_FAILURE_SEEN_KEYS: set[tuple[str, str]] | None = None

FIELD_MAP = {
    "body_type": "Body Type",
    "no_of_seats": "No. of Seats",
    "build_date": "Build Date",
    "compliance_date": "Compliance Date",
    "vin": "VIN",
    "rego_no": "Registration No",
    "rego_state": "Registration State",
    "rego_expiry": "Registration Expiry Date",
    "no_of_plates": "No. of Plates",
    "no_of_cylinders": "No. of Cylinders",
    "engine_capacity": "Engine Capacity",
    "fuel_type": "Fuel Type",
    "transmission": "Transmission",
    "odometer_reading": "Indicated Odometer Reading",
    "exterior_colour": "Exterior Colour",
    "interior_colour": "Interior Colour",
    "key": "Key",
    "spare_key": "Spare Key",
    "owners_manual": "Owners Manual",
    "service_history": "Service History",
    "engine_turns_over": "Engine Turns Over",
    "location": "Location",
}

STATE_CODES = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"}

REQUEST_TIMEOUT = float(os.getenv("AUTOSNIPER_REQUEST_TIMEOUT", "25"))
REQUEST_DELAY = float(os.getenv("AUTOSNIPER_REQUEST_DELAY", "1.1"))
MAX_FETCH_RETRIES = int(os.getenv("AUTOSNIPER_FETCH_RETRIES", "3"))
PROXY_PREFIX_HTTPS = "https://r.jina.ai/https://"
PROXY_PREFIX_HTTP = "https://r.jina.ai/http://"
PROXY_ROTATION = ("", PROXY_PREFIX_HTTPS, PROXY_PREFIX_HTTP)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

YEAR_RE = re.compile(r"^(\d{4})$")
STATE_RE = re.compile(r"\b(NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\b", re.IGNORECASE)

CONDITION_METADATA_FIELDS = {
    "key",
    "spare key",
    "owners manual",
    "owner's manual",
    "service history",
    "engine turns over",
}

ALLOWED_BODY_TYPES = {
    "Wagon",
    "Sedan",
    "Hatchback",
    "Ute",
    "Van",
    "Cab Chassis",
    "Crew Cab Chassis",
    "Dual Cab",
    "People Mover",
    "Coupe",
    "Convertible",
    "Bus",
    "SUV",
}
WOVR_PATTERN = re.compile(
    r"\bwovr\b|wovr[-\s]*(?:inspected|repairable|statutory)|write[-\s]?off",
    re.IGNORECASE,
)


def clean_joined_fields(text: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1, \2", text)


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _normalize_url_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _load_url_set(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        df = pd.read_csv(path, usecols=["url"])
    except (ValueError, pd.errors.EmptyDataError):
        df = pd.read_csv(path) if path.exists() else pd.DataFrame()
    if "url" not in df.columns:
        return set()
    urls = df["url"].dropna().apply(_normalize_url_value)
    return {url for url in urls if url}


def _lock_schema(df: pd.DataFrame, expected_columns: Iterable[str]) -> pd.DataFrame:
    columns = list(expected_columns)
    if df.empty:
        return pd.DataFrame(columns=columns)
    out = df.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = ""
    return out.reindex(columns=columns)


def _merge_pipeline_snapshot(
    path: Path,
    new_df: pd.DataFrame,
    *,
    expected_columns: Iterable[str],
) -> pd.DataFrame:
    if new_df.empty:
        return pd.DataFrame(columns=list(expected_columns))
    if path.exists():
        try:
            existing_df = pd.read_csv(path, low_memory=False)
        except (ValueError, pd.errors.EmptyDataError):
            existing_df = pd.DataFrame()
    else:
        existing_df = pd.DataFrame()
    existing_df = _lock_schema(existing_df, expected_columns)
    new_df = _lock_schema(new_df, expected_columns)
    combined = pd.concat([existing_df, new_df], ignore_index=True, sort=False)
    if "url" in combined.columns:
        combined["_url_norm"] = combined["url"].astype(str).str.strip().str.lower()
        combined = combined.drop_duplicates(subset=["_url_norm"], keep="last")
        combined = combined.drop(columns=["_url_norm"], errors="ignore")
    else:
        combined = combined.drop_duplicates()
    combined = combined.reset_index(drop=True)
    return _lock_schema(combined, expected_columns)


def _prepare_raw_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    snapshot = df.copy()
    snapshot = snapshot.drop(columns=["canonical_tag", "canonical_reason"], errors="ignore")
    for column in STATIC_VEHICLE_SCHEMA:
        if column not in snapshot.columns:
            snapshot[column] = ""
    return snapshot.reindex(columns=STATIC_VEHICLE_SCHEMA)


def _prepare_normalised_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    working = normalize_listing_fields(df)
    working = drop_invalid_years(working, allow_missing=True)
    working = drop_invalid_odometer_rows(working, allow_missing=True)
    working = working.drop(columns=["canonical_tag", "canonical_reason"], errors="ignore")
    for column in STATIC_VEHICLE_SCHEMA:
        if column not in working.columns:
            working[column] = ""
    return working.reindex(columns=STATIC_VEHICLE_SCHEMA)


def load_make_whitelist(existing_df: pd.DataFrame) -> set[str]:
    whitelist: set[str] = set()
    sold_path = dataset_path("sold_cars.csv")
    if sold_path.exists():
        try:
            sold_df = pd.read_csv(sold_path, usecols=["make"])
            whitelist = {
                str(make).strip().upper()
                for make in sold_df["make"].dropna().unique().tolist()
                if str(make).strip()
            }
        except Exception:
            whitelist = set()
    if not whitelist and "make" in existing_df.columns:
        whitelist = {
            str(make).strip().upper()
            for make in existing_df["make"].dropna().unique().tolist()
            if str(make).strip()
        }
    return whitelist


def _load_failure_seen_keys() -> set[tuple[str, str]]:
    global _FAILURE_SEEN_KEYS
    if _FAILURE_SEEN_KEYS is not None:
        return _FAILURE_SEEN_KEYS
    keys: set[tuple[str, str]] = set()
    if FAILURES_FILE.exists():
        try:
            existing = pd.read_csv(FAILURES_FILE, usecols=["url", "reason_code"], low_memory=False)
        except (ValueError, pd.errors.EmptyDataError):
            existing = pd.DataFrame(columns=["url", "reason_code"])
        if not existing.empty:
            urls = existing["url"].fillna("").astype(str).str.strip()
            reasons = existing["reason_code"].fillna("").astype(str).str.strip()
            keys = {(url, reason) for url, reason in zip(urls, reasons) if url}
    _FAILURE_SEEN_KEYS = keys
    return _FAILURE_SEEN_KEYS


def append_failure_log(records: list[dict[str, Any]], *, stage: str = "static_validation") -> None:
    if not records:
        return
    FAILURES_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_df = pd.DataFrame(records)
    if "url" not in new_df.columns:
        append_pipeline_exclusions(records, stage=stage)
        return
    if "reason_code" not in new_df.columns:
        new_df["reason_code"] = ""
    new_df["url"] = new_df["url"].fillna("").astype(str).str.strip()
    new_df["reason_code"] = new_df["reason_code"].fillna("").astype(str).str.strip()
    new_df = new_df[new_df["url"].ne("")].copy()
    if new_df.empty:
        append_pipeline_exclusions(records, stage=stage)
        return
    new_df = new_df.drop_duplicates(subset=["url", "reason_code"], keep="first")

    seen_keys = _load_failure_seen_keys()
    key_series = list(zip(new_df["url"], new_df["reason_code"]))
    fresh_mask = [key not in seen_keys for key in key_series]
    to_append = new_df.loc[fresh_mask].copy()
    if to_append.empty:
        append_pipeline_exclusions(records, stage=stage)
        return
    for key in zip(to_append["url"], to_append["reason_code"]):
        seen_keys.add(key)

    file_exists = FAILURES_FILE.exists()
    if file_exists:
        try:
            existing_columns = list(pd.read_csv(FAILURES_FILE, nrows=0).columns)
        except (ValueError, pd.errors.EmptyDataError):
            existing_columns = list(to_append.columns)
    else:
        existing_columns = list(to_append.columns)
    for column in existing_columns:
        if column not in to_append.columns:
            to_append[column] = ""
    to_append = to_append.reindex(columns=existing_columns)
    to_append.to_csv(FAILURES_FILE, mode="a", header=not file_exists, index=False)
    append_pipeline_exclusions(records, stage=stage)


def filter_static_rows(df: pd.DataFrame, make_whitelist: set[str]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if df.empty:
        return df, []
    failures: list[dict[str, Any]] = []
    now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    cfg = ValidatorConfig(
        make_whitelist=make_whitelist,
        enforce_vic_only=False,
        allow_suspect_odometer=False,
        allowed_body_types=ALLOWED_BODY_TYPES,
    )
    kept_rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        row_dict = row.to_dict()
        is_valid, reason, cleaned = validate_static_row(row_dict, cfg)
        if is_valid:
            kept_rows.append(cleaned)
        else:
            snapshot = {
                key: row_dict.get(key, "")
                for key in (
                    "year",
                    "make",
                    "model",
                    "variant",
                    "body_type",
                    "transmission",
                    "fuel_type",
                    "odometer_reading",
                    "vin",
                    "location",
                )
            }
            failures.append(
                {
                    "timestamp": now_ts,
                    "url": row_dict.get("url", ""),
                    "reason_code": reason,
                    "field_snapshot": json.dumps(snapshot, ensure_ascii=True),
                }
            )
    if not kept_rows:
        return df.iloc[0:0].copy(), failures
    filtered = pd.DataFrame(kept_rows)
    for column in df.columns:
        if column not in filtered.columns:
            filtered[column] = pd.NA
    filtered = filtered.reindex(columns=df.columns)
    return filtered.reset_index(drop=True), failures


def build_canonical_exclusion_failures(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if df.empty:
        return df, []

    working = df.copy()
    if "canonical_tag" not in working.columns:
        working["canonical_tag"] = ""
    if "canonical_reason" not in working.columns:
        working["canonical_reason"] = ""

    tags = working["canonical_tag"].fillna("").astype(str).str.strip()
    reasons = working["canonical_reason"].fillna("").astype(str).str.strip()
    eligible_mask = tags.ne("") & tags.ne(UNCLASSIFIED) & reasons.isin(ELIGIBLE_CANONICAL_REASONS)
    if eligible_mask.all():
        return working, []

    now_ts = time.strftime("%Y-%m-%d %H:%M:%S")
    excluded = working.loc[~eligible_mask].copy()
    snapshot_cols = (
        "year",
        "make",
        "model",
        "variant",
        "body_type",
        "transmission",
        "fuel_type",
        "odometer_reading",
        "vin",
        "location",
        "canonical_tag",
        "canonical_reason",
    )
    snapshot_records = excluded.reindex(columns=snapshot_cols, fill_value="").fillna("").to_dict("records")
    if "url" in excluded.columns:
        url_values = excluded["url"].fillna("").astype(str).tolist()
    else:
        url_values = [""] * len(excluded)
    reason_values = excluded["canonical_reason"].fillna("").astype(str).str.strip().tolist()
    failures = [
        {
            "timestamp": now_ts,
            "url": url,
            "reason_code": reason or "NOT_CANONICAL_ELIGIBLE",
            "field_snapshot": json.dumps(snapshot, ensure_ascii=True),
        }
        for url, reason, snapshot in zip(url_values, reason_values, snapshot_records)
    ]
    kept = working.loc[eligible_mask].copy()
    return kept.reset_index(drop=True), failures


def _has_valid_year(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if text.endswith(".0"):
        text = text[:-2]
    if YEAR_RE.match(text):
        return True
    try:
        num = float(value)
    except (TypeError, ValueError):
        return False
    if pd.isna(num) or not num.is_integer():
        return False
    year = int(num)
    return 1900 <= year <= 2099


def _has_valid_odometer(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"nan", "none"}:
        return False
    return text != "0"


def select_best_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer the most complete/valid row per URL to avoid losing listings."""
    if df.empty or "url" not in df.columns:
        return df

    working = df.copy()
    working["_url_norm"] = working["url"].astype(str).str.strip().str.casefold()
    base_columns = list(df.columns)
    working["_row_order"] = range(len(working))

    def _non_missing(row: pd.Series) -> int:
        return sum(not _is_missing(row[col]) for col in base_columns)

    working["_non_missing"] = working.apply(_non_missing, axis=1)
    if "year" in working.columns:
        working["_valid_year"] = working["year"].apply(_has_valid_year)
    else:
        working["_valid_year"] = False
    if "odometer_reading" in working.columns:
        working["_valid_odometer"] = working["odometer_reading"].apply(_has_valid_odometer)
    else:
        working["_valid_odometer"] = False

    working["_score"] = (
        working["_non_missing"]
        + working["_valid_year"].astype(int) * 100
        + working["_valid_odometer"].astype(int) * 100
    )

    working.sort_values(
        by=["_url_norm", "_score", "_row_order"],
        ascending=[True, True, True],
        inplace=True,
    )
    best = working.groupby("_url_norm", as_index=False).tail(1)
    best = best.drop(
        columns=[
            "_url_norm",
            "_row_order",
            "_non_missing",
            "_valid_year",
            "_valid_odometer",
            "_score",
        ],
        errors="ignore",
    )
    return best.reset_index(drop=True)


def safe_get_text(tag: Tag | None) -> str:
    return tag.get_text(strip=True) if tag else ""


def extract_field(soup: BeautifulSoup, label: str) -> str:
    """Find a `<li>` entry in the spec list by its label."""
    for li in soup.find_all("li"):
        text = safe_get_text(li)
        if not text:
            continue
        if re.match(rf"^{re.escape(label)}\s*:", text, flags=re.IGNORECASE):
            parts = text.split(":", 1)
            if len(parts) == 2:
                return clean_joined_fields(parts[1].strip())
    return ""


def extract_bullets(soup: BeautifulSoup, title_pattern: str) -> str:
    title = soup.find("strong", string=re.compile(title_pattern, re.IGNORECASE))
    if not title:
        return ""
    parent = title.find_parent("p")
    if not parent:
        return ""
    ul = parent.find_next_sibling("ul")
    if not ul:
        return ""
    items = [safe_get_text(li) for li in ul.find_all("li") if safe_get_text(li)]
    return "\n".join(items)


def filter_condition_entries(entries: Iterable[str]) -> list[str]:
    filtered: list[str] = []
    for entry in entries:
        cleaned = entry.strip()
        if not cleaned:
            continue
        normalized = cleaned.lstrip("\u2022-* \t").strip().lower()
        prefix = normalized.split(":", 1)[0].strip()
        if prefix in CONDITION_METADATA_FIELDS:
            continue
        filtered.append(cleaned)
    return filtered


def normalize_state(text: str) -> str:
    if not text:
        return ""
    match = STATE_RE.search(text)
    if match:
        return match.group(1).upper()
    return text.strip()


def extract_location(soup: BeautifulSoup) -> str:
    for td in soup.find_all("td"):
        header_text = safe_get_text(td)
        if not header_text:
            continue
        if re.match(r"location", header_text, re.IGNORECASE):
            value = safe_get_text(td.find_next_sibling("td"))
            return normalize_state(value)
    return ""


PRICE_RE = re.compile(r"\$[\d,]+(?:\.\d+)?")
BIDS_RE = re.compile(r"(\d+)\s*bids?", re.IGNORECASE)
JS_LITERAL_RE = re.compile(r"\\b(true|false|null)\\b", re.IGNORECASE)


def extract_sale_meta(soup: BeautifulSoup) -> tuple[str | None, str | None, str | None, str | None]:
    price_text: str | None = None
    bids_value: str | None = None
    closing_text: str | None = None
    derived_status: str | None = None

    price_block = soup.find("div", class_=lambda classes: classes and "currentbid_price" in classes)
    if price_block:
        block_text = price_block.get_text(" ", strip=True)
        match = PRICE_RE.search(block_text)
        if match:
            price_text = match.group(0)
        if "sold" in block_text.lower():
            derived_status = "sold"

    bids_anchor = soup.find("a", attrs={"data-target": "#dvBidHistoryPop"})
    if bids_anchor:
        anchor_text = bids_anchor.get_text(" ", strip=True)
        match = BIDS_RE.search(anchor_text)
        if match:
            bids_value = match.group(1)
    if bids_value is None:
        bids_node = soup.find(string=re.compile(r"Bids\s*\(\d+", re.IGNORECASE))
        if bids_node:
            node_text = bids_node.parent.get_text(" ", strip=True)
            match = BIDS_RE.search(node_text)
            if match:
                bids_value = match.group(1)

    if bids_value is None:
        page_text = soup.get_text(" ", strip=True)
        match = BIDS_RE.search(page_text)
        if match:
            bids_value = match.group(1)

    for label in ("Closed:", "Closes:"):
        closing_node = soup.find(string=re.compile(label, re.IGNORECASE))
        if closing_node:
            container = closing_node.parent
            closing_text = container.get_text(" ", strip=True)
            if label.lower().startswith("closed"):
                page_text = soup.get_text(" ", strip=True).lower()
                if "sold" in page_text:
                    derived_status = "sold"
            break

    return price_text, bids_value, closing_text, derived_status


def extract_title_parts(soup: BeautifulSoup) -> tuple[str, str, str, str]:
    title_elem = soup.find("h1", class_="dls-heading-3")
    title = safe_get_text(title_elem)
    if not title:
        return ("", "", "", "")

    cleaned_title = remove_compliance_markers(title)
    parts = cleaned_title.split()
    year = parts[0] if parts and YEAR_RE.match(parts[0]) else ""
    make = parts[1] if len(parts) > 1 else ""
    model = parts[2] if len(parts) > 2 else ""
    variant = " ".join(parts[3:]) if len(parts) > 3 else ""
    return year, make, model, variant


def parse_money(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value)
    match = PRICE_RE.search(text)
    if not match:
        return ""
    cleaned = match.group(0).replace(",", "")
    try:
        return f"{float(cleaned):.2f}"
    except ValueError:
        return ""


def parse_int(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = re.sub(r"[^\d-]", "", str(value))
    if not text:
        return ""
    try:
        return str(int(text))
    except ValueError:
        return ""


def _normalize_js_literals(raw: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        text = match.group(1).lower()
        if text == "true":
            return "True"
        if text == "false":
            return "False"
        if text == "null":
            return "None"
        return match.group(0)

    return JS_LITERAL_RE.sub(_replace, raw)


def _parse_literal(raw: str) -> Any:
    normalized = _normalize_js_literals(raw)
    try:
        return ast.literal_eval(normalized)
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return None


def _extract_data_layer_arrays(html: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for match in re.finditer(r"(?:window\.)?dataLayer\s*=\s*\[", html, re.IGNORECASE):
        start = match.end() - 1
        depth = 0
        end = start
        while end < len(html):
            char = html[end]
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    end += 1
                    break
            end += 1
        snippet = html[start:end]
        parsed = _parse_literal(snippet)
        if isinstance(parsed, list):
            payloads.extend(entry for entry in parsed if isinstance(entry, dict))
    return payloads


def _extract_data_layer_pushes(html: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for match in re.finditer(r"dataLayer\.push\(\s*(\{.*?\})\s*\);", html, re.S | re.IGNORECASE):
        snippet = match.group(1)
        parsed = _parse_literal(snippet)
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def parse_data_layer(html: str) -> dict[str, Any]:
    payloads = _extract_data_layer_arrays(html) + _extract_data_layer_pushes(html)
    if not payloads:
        return {}
    for entry in reversed(payloads):
        if isinstance(entry, dict) and (
            "Analytics_CurrentBid" in entry
            or "Analytics_LotStatus" in entry
            or "lotStatus" in entry
        ):
            return entry
    return payloads[-1]


def extract_dynamic_metrics(html: str) -> dict[str, str]:
    data = parse_data_layer(html)
    metrics = {
        "price": "",
        "bids": "",
        "time_remaining_or_date_sold": "",
        "status": "",
    }
    if not data:
        return metrics

    metrics["price"] = parse_money(
        data.get("Analytics_CurrentBid")
        or data.get("currentBid")
        or data.get("LotCurrentPrice")
        or data.get("LotPrice")
    )
    metrics["bids"] = parse_int(
        data.get("Analytics_TotalBids")
        or data.get("totalBids")
        or data.get("LotBidCount")
    )

    time_remaining = data.get("Analytics_AuctionEnds") or data.get("lotCountdownText") or data.get("LotEndsOn")
    if isinstance(time_remaining, (int, float)):
        metrics["time_remaining_or_date_sold"] = str(time_remaining)
    elif isinstance(time_remaining, str):
        metrics["time_remaining_or_date_sold"] = time_remaining.strip()

    status = (
        data.get("Analytics_LotStatus")
        or data.get("LotStatus")
        or data.get("lotStatus")
        or data.get("status")
    )
    if isinstance(status, str):
        metrics["status"] = status.strip()

    return metrics


def extract_year_from_url(url: str) -> str:
    match = re.search(r"/((?:19|20)\\d{2})-", url)
    return match.group(1) if match else ""


def read_general_condition(soup: BeautifulSoup) -> str:
    section = soup.find(attrs={"id": re.compile("ConditionAssessment", re.IGNORECASE)})
    if section:
        bullet_items = filter_condition_entries(safe_get_text(li) for li in section.find_all("li"))
        if bullet_items:
            return "\n".join(bullet_items)

        paragraphs = filter_condition_entries(safe_get_text(p) for p in section.find_all("p"))
        if paragraphs:
            return "\n".join(paragraphs)

    legacy_note = soup.find("strong", string=re.compile("condition assessment", re.IGNORECASE))
    if legacy_note:
        parent = legacy_note.find_parent("p")
        if parent:
            next_list = parent.find_next_sibling("ul")
            if next_list:
                bullet_items = filter_condition_entries(safe_get_text(li) for li in next_list.find_all("li"))
                if bullet_items:
                    return "\n".join(bullet_items)

    condition = extract_bullets(soup, "condition")
    if condition:
        filtered_condition = filter_condition_entries(condition.splitlines())
        if filtered_condition:
            return "\n".join(filtered_condition)
    return ""


def assemble_details(soup: BeautifulSoup, url: str, html: str) -> dict[str, Any]:
    year, make, model, variant = extract_title_parts(soup)

    details: dict[str, Any] = {
        "year": year,
        "make": make,
        "model": model,
        "variant": variant,
        "odometer_unit": "km",
        "url": url,
    }

    for field_key, label in FIELD_MAP.items():
        value = extract_field(soup, label)
        details[field_key] = value

    if not details.get("year") and details.get("build_date"):
        match = YEAR_RE.search(details["build_date"])
        if match:
            details["year"] = match.group(1)
    if not details.get("year"):
        details["year"] = extract_year_from_url(url)

    details["general_condition"] = read_general_condition(soup)
    details["location"] = normalize_state(details.get("location", "") or extract_location(soup))

    metrics = extract_dynamic_metrics(html)
    details.update(metrics)

    details["bids"] = details.get("bids", "")
    details["price"] = details.get("price", "")
    details["time_remaining_or_date_sold"] = details.get("time_remaining_or_date_sold", "")
    status_value = str(details.get("status", "")).strip().lower()
    details["status"] = status_value or "active"

    price_text, bids_value, closing_text, derived_status = extract_sale_meta(soup)
    if price_text:
        details["price"] = price_text
    if bids_value:
        details["bids"] = bids_value
    if closing_text:
        details["time_remaining_or_date_sold"] = closing_text
    if derived_status:
        details["status"] = derived_status

    raw_status = (details.get("status") or "").strip().lower()
    details["status"] = normalize_status(raw_status)

    return details


def normalize_status(value: str) -> str:
    mapping = {
        "open": "active",
        "new": "active",
        "active": "active",
        "sold": "sold",
        "closed": "sold",
        "referred": "referred",
        "refer": "referred",
    }
    return mapping.get(value, "active" if not value else value)


def fetch_html(session: requests.Session, url: str) -> str:
    last_error: str | None = None
    for attempt in range(1, MAX_FETCH_RETRIES + 1):
        prefix = PROXY_ROTATION[min(attempt - 1, len(PROXY_ROTATION) - 1)]
        use_proxy = bool(prefix) or url.startswith(prefix)
        if prefix:
            suffix = url.replace("https://", "").replace("http://", "")
            target_url = f"{prefix}{suffix}"
        else:
            target_url = url
        try:
            response = session.get(target_url, timeout=REQUEST_TIMEOUT)
            body_lower = response.text.lower()
            blocked_body = "request could not be satisfied" in body_lower or "generated by cloudfront" in body_lower
            if response.status_code == 200 and len(response.text) > 2000 and not blocked_body:
                return response.text
            if response.status_code == 403 or blocked_body:
                last_error = "CloudFront 403"
                continue
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(REQUEST_DELAY)
    if last_error:
        print(f"Failed to fetch {url}: {last_error}")
    return ""


def process_links(links: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    link_list = list(links)
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    results: list[dict[str, Any]] = []
    skipped: list[str] = []
    for idx, url in enumerate(link_list, start=1):
        print(f"[{idx}/{len(link_list)}] Scraping {url}")
        html = fetch_html(session, url)
        if not html:
            skipped.append(url)
            continue
        soup = BeautifulSoup(html, "html.parser")
        details = assemble_details(soup, url, html)
        results.append(details)
        time.sleep(REQUEST_DELAY)
    return results, skipped


def write_skipped(skipped: list[str]) -> None:
    if not skipped:
        return
    SKIPPED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SKIPPED_LOG.open("a", encoding="utf-8") as handle:
        for url in skipped:
            handle.write(url + "\n")


def remove_from_active_links(urls: Iterable[str]) -> None:
    if ACTIVE_LINKS_FILE is None or not ACTIVE_LINKS_FILE.exists():
        return
    url_list = [str(url).strip() for url in urls if str(url).strip()]
    if not url_list:
        return
    df = pd.read_csv(ACTIVE_LINKS_FILE)
    if "url" not in df.columns or df.empty:
        return
    normalized_remove = {_normalize_url_value(url) for url in url_list if _normalize_url_value(url)}
    df["_url_norm"] = df["url"].astype(str).str.strip().str.lower()
    df = df[~df["_url_norm"].isin(normalized_remove)].copy()
    df.drop(columns=["_url_norm"], inplace=True, errors="ignore")
    atomic_write(df, ACTIVE_LINKS_FILE)


def remove_from_active_details(urls: Iterable[str]) -> None:
    if ACTIVE_OUTPUT_FILE is None or not ACTIVE_OUTPUT_FILE.exists():
        return
    url_list = [str(url).strip() for url in urls if str(url).strip()]
    if not url_list:
        return
    df = pd.read_csv(ACTIVE_OUTPUT_FILE)
    if "url" not in df.columns or df.empty:
        return
    normalized_remove = {_normalize_url_value(url) for url in url_list if _normalize_url_value(url)}
    df["_url_norm"] = df["url"].astype(str).str.strip().str.lower()
    df = df[~df["_url_norm"].isin(normalized_remove)].copy()
    df.drop(columns=["_url_norm"], inplace=True, errors="ignore")
    atomic_write(df, ACTIVE_OUTPUT_FILE)


def prune_to_active_queue(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Keep only rows whose URLs are still present in active_vehicle_links.csv."""
    if df.empty or "url" not in df.columns:
        return df, 0
    if ACTIVE_LINKS_FILE is None or not ACTIVE_LINKS_FILE.exists():
        return df, 0
    active_urls = _load_url_set(ACTIVE_LINKS_FILE)
    # Safety: avoid accidental full wipe when active queue is unexpectedly empty.
    if not active_urls:
        print("Active queue is empty; skipping static prune for safety.")
        return df, 0
    out = df.copy()
    out["_url_norm"] = out["url"].astype(str).str.strip().str.lower()
    mask = out["_url_norm"].isin(active_urls)
    removed = int((~mask).sum())
    out = out.loc[mask].copy()
    out.drop(columns=["_url_norm"], inplace=True, errors="ignore")
    return out.reset_index(drop=True), removed


def atomic_write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    try:
        df.to_csv(temp_path, index=False)
        shutil.move(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _normalize_text_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    columns = {
        "make",
        "model",
        "variant",
        "body_type",
        "fuel_type",
        "transmission",
        "location",
        "general_condition",
        "canonical_tag",
        "canonical_reason",
        "series",
        "badge",
    }
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].astype(str).str.lower()
            out[col] = out[col].replace({"nan": ""})
    return out


def merge_and_save_static(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    if new_df.empty:
        return existing_df
    new_df = normalize_listing_fields(new_df)
    new_df = drop_invalid_years(new_df, allow_missing=True)
    new_df = drop_invalid_odometer_rows(new_df, allow_missing=True)
    new_df = new_df.reindex(columns=SCHEMA_FIELDS)

    if existing_df.empty:
        combined = new_df
    else:
        existing_df = existing_df.reindex(columns=SCHEMA_FIELDS)
        combined = pd.concat([existing_df, new_df], ignore_index=True, sort=False)
    combined = combined.reset_index(drop=True)
    combined = select_best_rows(combined)
    make_whitelist = load_make_whitelist(existing_df)
    combined, failures = filter_static_rows(combined, make_whitelist)
    append_failure_log(failures, stage="static_validation")
    if failures:
        failure_urls = [record.get("url", "") for record in failures]
        remove_from_active_links(failure_urls)
        remove_from_active_details(failure_urls)
    static_export = combined.drop_duplicates(subset=["url"], keep="last")
    static_export = static_export.reindex(columns=STATIC_VEHICLE_SCHEMA, fill_value="")
    static_export, stats = validate_vehicle_static_df(static_export)
    if stats["rows_dropped"]:
        print(f"Validator dropped {stats['rows_dropped']} invalid static rows before write.")

    static_export = tag_dataframe(
        static_export,
        source="grays_static",
        require_price=False,
        filter_unclassified=False,
        append_log=False,
    )
    static_export = _normalize_text_columns(static_export)
    _canonical_kept, canonical_failures = build_canonical_exclusion_failures(static_export)
    if canonical_failures:
        append_failure_log(canonical_failures, stage="canonical_eligibility")
        print(
            f"Canonical audit flagged {len(canonical_failures)} listing(s); keeping rows in static export."
        )
    if "drivetrain_source" in static_export.columns:
        static_export = static_export.drop(columns=["drivetrain_source"])
    static_export = static_export.reindex(columns=STATIC_OUTPUT_COLUMNS, fill_value="")
    static_export, pruned_rows = prune_to_active_queue(static_export)
    if pruned_rows:
        print(f"Pruned {pruned_rows} stale static row(s) not present in active link queue.")
    atomic_write(static_export, OUTPUT_FILE)
    return static_export


def seed_active_dataset(static_df: pd.DataFrame) -> None:
    """Create the active listings CSV from the static scrape output."""
    if static_df is None:
        return
    active_df = static_df.copy()
    active_df = tag_dataframe(
        active_df,
        source="grays_active",
        require_price=False,
        filter_unclassified=False,
        append_log=True,
    )
    active_df = _normalize_text_columns(active_df)
    if "drivetrain_source" in active_df.columns:
        active_df = active_df.drop(columns=["drivetrain_source"])
    base_columns = list(static_df.columns)
    existing_active = pd.read_csv(ACTIVE_OUTPUT_FILE) if ACTIVE_OUTPUT_FILE.exists() else pd.DataFrame()

    def _normalize_url(series: pd.Series) -> pd.Series:
        return series.astype(str).str.strip().str.lower()

    def _is_blank(series: pd.Series) -> pd.Series:
        lowered = series.astype(str).str.strip().str.lower()
        return lowered.isin({"", "nan", "none"})

    if active_df.empty:
        active_df = pd.DataFrame(columns=base_columns)
    if not active_df.empty:
        wovr_columns = [col for col in ("variant", "url") if col in active_df.columns]
        if wovr_columns:
            combined = active_df[wovr_columns].fillna("").astype(str).agg(" ".join, axis=1)
            wovr_mask = combined.str.contains(WOVR_PATTERN, na=False)
            if wovr_mask.any():
                active_df = active_df.loc[~wovr_mask].copy()
    # Ensure required dynamic columns exist.
    for column in ("time_remaining_or_date_sold", "price", "bids"):
        if column not in active_df.columns:
            active_df[column] = ""
    # Preserve scraped status where present; default blanks to active.
    if "status" not in active_df.columns:
        active_df["status"] = "active"
    else:
        active_df["status"] = active_df["status"].fillna("").astype(str).str.strip().str.lower()
        active_df.loc[active_df["status"] == "", "status"] = "active"

    if not existing_active.empty and "url" in active_df.columns and "url" in existing_active.columns:
        active_df["_url_norm"] = _normalize_url(active_df["url"])
        existing_active = existing_active.copy()
        existing_active["_url_norm"] = _normalize_url(existing_active["url"])
        existing_active = existing_active.drop_duplicates(subset=["_url_norm"], keep="last")
        lookup = existing_active.set_index("_url_norm")
        for column in ("time_remaining_or_date_sold", "price", "bids"):
            if column not in active_df.columns:
                active_df[column] = ""
            if column not in lookup.columns:
                continue
            blank_mask = _is_blank(active_df[column])
            active_df.loc[blank_mask, column] = active_df.loc[blank_mask, "_url_norm"].map(lookup[column])
        active_df.drop(columns=["_url_norm"], inplace=True, errors="ignore")

    dynamic_columns = [
        col
        for col in ("status", "time_remaining_or_date_sold", "price", "bids")
        if col not in base_columns
    ]
    ordered_columns = base_columns + dynamic_columns
    active_df = active_df.reindex(columns=ordered_columns, fill_value="")
    atomic_write(active_df, ACTIVE_OUTPUT_FILE)


def main(
    batch_size: int | None = None,
    *,
    force_all: bool = False,
    checkpoint_every: int | None = None,
    raw_only: bool = False,
) -> None:
    if not INPUT_FILE.exists():
        fallback = dataset_path("all_vehicle_links.csv")
        if not fallback.exists():
            print(f"Missing input file: {INPUT_FILE}")
            return
        print(f"Active links missing; falling back to {fallback}.")
        input_path = fallback
    else:
        input_path = INPUT_FILE

    links_df = pd.read_csv(input_path)
    raw_links = links_df.get("url", pd.Series(dtype=str)).dropna().astype(str).tolist()
    all_links: list[str] = []
    seen_links: set[str] = set()
    for url in raw_links:
        normalized = _normalize_url_value(url)
        if not normalized or normalized in seen_links:
            continue
        all_links.append(url)
        seen_links.add(normalized)
    if not all_links:
        print("No URLs found in the links CSV.")
        return

    existing_df = pd.read_csv(OUTPUT_FILE) if OUTPUT_FILE.exists() else pd.DataFrame(columns=SCHEMA_FIELDS)
    processed_urls = {
        _normalize_url_value(url)
        for url in existing_df.get("url", pd.Series(dtype=str)).dropna().tolist()
    }
    sold_urls = _load_url_set(dataset_path("sold_cars.csv"))
    referred_urls = _load_url_set(dataset_path("referred_cars.csv"))
    completed_urls = sold_urls | referred_urls
    if completed_urls:
        before = len(all_links)
        all_links = [url for url in all_links if _normalize_url_value(url) not in completed_urls]
        skipped = before - len(all_links)
        if skipped:
            print(f"Skipping {skipped} sold/referred listing(s) from link queue.")

    pending_links = [url for url in all_links if _normalize_url_value(url) not in processed_urls]

    target_links = all_links if force_all else (pending_links or all_links)
    if batch_size is not None and batch_size > 0:
        target_links = target_links[:batch_size]
        print(
            f"Limiting run to {len(target_links)} listing(s) based on batch size {batch_size}. "
            f"(Pending queue length: {len(pending_links)}.)"
        )
    else:
        print(f"Processing {len(target_links)} listings (pending: {len(pending_links)}).")

    checkpoint_every = checkpoint_every or 0
    if checkpoint_every > 0:
        total = len(target_links)
        total_skipped = 0
        total_scraped = 0
        for start in range(0, total, checkpoint_every):
            batch = target_links[start : start + checkpoint_every]
            print(f"Checkpoint batch {start + 1}-{start + len(batch)} of {total}.")
            data, skipped = process_links(batch)
            total_skipped += len(skipped)
            write_skipped(skipped)
            if data:
                total_scraped += len(data)
                new_df = pd.DataFrame(data)
                raw_snapshot = _prepare_raw_snapshot(new_df)
                raw_merged = _merge_pipeline_snapshot(
                    RAW_OUTPUT_FILE,
                    raw_snapshot,
                    expected_columns=STATIC_VEHICLE_SCHEMA,
                )
                if not raw_merged.empty:
                    atomic_write(raw_merged, RAW_OUTPUT_FILE)

                if raw_only:
                    print(f"Checkpoint saved raw only ({len(new_df)} new rows).")
                else:
                    normalized_snapshot = _prepare_normalised_snapshot(new_df)
                    normalized_merged = _merge_pipeline_snapshot(
                        NORMALIZED_OUTPUT_FILE,
                        normalized_snapshot,
                        expected_columns=STATIC_VEHICLE_SCHEMA,
                    )
                    if not normalized_merged.empty:
                        atomic_write(normalized_merged, NORMALIZED_OUTPUT_FILE)

                    existing_df = merge_and_save_static(existing_df, new_df)
                    print(
                        f"Checkpoint saved ({len(new_df)} new rows, total {len(existing_df)})."
                    )
            else:
                print("No listings were scraped in this batch.")
        if total_scraped == 0:
            print("No listings were scraped.")
            return
        if raw_only:
            print(f"Saved {total_scraped} raw rows. Output: {RAW_OUTPUT_FILE}")
        else:
            seed_active_dataset(existing_df)
            print(f"Saved {total_scraped} rows (total {len(existing_df)}). Output: {OUTPUT_FILE}")
        if total_skipped:
            print(f"{total_skipped} URLs skipped. See {SKIPPED_LOG}")
        return

    data, skipped = process_links(target_links)
    new_df = pd.DataFrame(data)
    if new_df.empty:
        print("No listings were scraped.")
        return

    raw_snapshot = _prepare_raw_snapshot(new_df)
    raw_merged = _merge_pipeline_snapshot(
        RAW_OUTPUT_FILE,
        raw_snapshot,
        expected_columns=STATIC_VEHICLE_SCHEMA,
    )
    if not raw_merged.empty:
        atomic_write(raw_merged, RAW_OUTPUT_FILE)

    if raw_only:
        print(f"Saved {len(new_df)} raw rows to {RAW_OUTPUT_FILE}")
    else:
        normalized_snapshot = _prepare_normalised_snapshot(new_df)
        normalized_merged = _merge_pipeline_snapshot(
            NORMALIZED_OUTPUT_FILE,
            normalized_snapshot,
            expected_columns=STATIC_VEHICLE_SCHEMA,
        )
        if not normalized_merged.empty:
            atomic_write(normalized_merged, NORMALIZED_OUTPUT_FILE)

        existing_df = merge_and_save_static(existing_df, new_df)
        seed_active_dataset(existing_df)
        print(f"Saved {len(new_df)} rows (total {len(existing_df)}). Output: {OUTPUT_FILE}")

    write_skipped(skipped)
    if skipped:
        print(f"{len(skipped)} URLs skipped. See {SKIPPED_LOG}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape vehicle details from stored links.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Limit the number of listings processed in this run. Omit to scrape the entire queue.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Force a full re-scrape of every stored link (not just pending ones).",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=50,
        help="Save progress every N listings (0 = disable).",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="Only write raw_vehicle_data.csv (skip normalise/exclude/static).",
    )
    args = parser.parse_args()
    main(
        batch_size=args.batch_size,
        force_all=args.all,
        checkpoint_every=args.checkpoint_every,
        raw_only=args.raw_only,
    )
