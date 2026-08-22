from __future__ import annotations

import argparse
import asyncio
import ctypes
import gc
import html
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.canonical_tagging import is_canonical_eligible, tag_dataframe
    from shared.curves import load_curves, resolve_curve_canonical_tag
    from shared.schema import ACTIVE_DETAIL_SCHEMA
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.canonical_tagging import is_canonical_eligible, tag_dataframe
    from shared.curves import load_curves, resolve_curve_canonical_tag
    from shared.schema import ACTIVE_DETAIL_SCHEMA


DEFAULT_OUTPUT_DIR = Path("output") / "external_auction_scrape"
DEFAULT_SOURCES = ("pickles", "manheim", "slattery")

LISTING_COLUMNS = list(
    dict.fromkeys(
        [
            "source",
            "scraped_at",
            "title",
            "url",
            *[column for column in ACTIVE_DETAIL_SCHEMA if column != "url"],
            "curve_tag",
            "scrape_status",
        ]
    )
)

AUDIT_COLUMNS = [
    "source",
    "scraped_at",
    "discovery_status",
    "completeness_status",
    "list_pages_planned",
    "list_pages_visited",
    "pagination_exhausted",
    "page_cap_reached",
    "blocked_pages",
    "discovered_links",
    "selected_for_detail",
    "detail_cap_reached",
    "selected_details_scraped",
    "selected_details_missing",
    "selected_details_unavailable",
    "detail_errors",
    "seed_details_scraped",
    "notes",
]

LINK_COLUMNS = [
    "source",
    "discovered_at",
    "url",
    "title_hint",
    "canonical_tag",
    "canonical_reason",
    "curve_tag",
    "selected_for_detail",
]

SOURCE_URLS: dict[str, list[str]] = {
    "pickles": [
        "https://www.pickles.com.au/used/search/cars?contentkey=all-cars&filter=and%255B0%255D%255Bor%255D%255B0%255D%255Bsalvage%255D=non-Salvage",
    ],
    "manheim": [
        "https://www.manheim.com.au/passenger-vehicles/for-sale/sydney?navType=C&sortBy=buildyear+desc",
        "https://www.manheim.com.au/passenger-vehicles/for-sale/melbourne?navType=C&sortBy=buildyear+desc",
    ],
    "slattery": [
        "https://slatteryauctions.com.au/categories/motor-vehicles",
    ],
}

MAX_AUTO_LIST_PAGES: dict[str, int] = {
    "pickles": 100,
    "manheim": 20,
    "slattery": 1,
}
DETAIL_BATCH_SIZE = 4
DEFAULT_DETAIL_BROWSER_RECYCLE_SIZE = 40
DEFAULT_DISCOVERY_BROWSER_RECYCLE_PAGES = 10

DETAIL_PATTERNS: dict[str, re.Pattern[str]] = {
    "pickles": re.compile(r"/used/details/cars/[^/?#]+/\d+", re.IGNORECASE),
    "manheim": re.compile(r"/passenger-vehicles/\d{8,}/[^/?#]+", re.IGNORECASE),
    "slattery": re.compile(r"/assets/\d+\?auctionId=\d+", re.IGNORECASE),
}

DETAIL_URL_FALLBACKS: dict[str, re.Pattern[str]] = {
    "pickles": re.compile(r"https://www\.pickles\.com\.au/used/details/cars/[^\"'<>\s#]+/\d+", re.IGNORECASE),
    "manheim": re.compile(r"https://www\.manheim\.com\.au/passenger-vehicles/\d{8,}/[^\"'<>\s#]+", re.IGNORECASE),
    "slattery": re.compile(
        r"(?:https://slatteryauctions\.com\.au)?/assets/\d+\?auctionId=\d+",
        re.IGNORECASE,
    ),
}

MAKE_ALIASES = {
    "toyota": "Toyota",
    "mazda": "Mazda",
    "hyundai": "Hyundai",
    "ford": "Ford",
    "holden": "Holden",
    "mitsubishi": "Mitsubishi",
    "isuzu": "Isuzu",
    "volkswagen": "Volkswagen",
    "vw": "Volkswagen",
    "nissan": "Nissan",
    "subaru": "Subaru",
    "kia": "Kia",
}

MODEL_ALIASES = {
    "cx-5": "CX-5",
    "cx5": "CX-5",
    "d-max": "D-MAX",
    "dmax": "D-MAX",
    "mu-x": "MU-X",
    "mux": "MU-X",
    "x-trail": "X-Trail",
    "xtrail": "X-Trail",
    "i30": "i30",
    "ix35": "ix35",
}

MULTI_WORD_MODELS = {
    ("bt-50",): "BT-50",
    ("d-max",): "D-MAX",
    ("landcruiser", "prado"): "Landcruiser Prado",
    ("santa", "fe"): "Santa Fe",
    ("x-trail",): "X-Trail",
}

BODY_KEYWORDS = (
    ("cab chassis", "Cab Chassis"),
    ("crew cab", "Dual Cab"),
    ("dual cab", "Dual Cab"),
    ("double cab", "Dual Cab"),
    ("hatchback", "Hatchback"),
    ("hatch", "Hatchback"),
    ("sedan", "Sedan"),
    ("wagon", "Wagon"),
    ("suv", "SUV"),
    ("utility", "Ute"),
    ("ute", "Ute"),
    ("van", "Van"),
    ("people mover", "People Mover"),
)

FIELD_ALIASES = {
    "year": ("Build Year", "Year Of Manufacture", "Year"),
    "make": ("Make", "Make & Brand"),
    "model": ("Model",),
    "variant": ("Variant", "Asset Name"),
    "body_type": ("Body Type", "Body"),
    "transmission": ("Transmission", "Transmission Type"),
    "fuel_type": ("Fuel Type", "Fuel"),
    "odometer_reading": ("Odometer", "Odometer (Showing on)", "Indicated Odometer Reading"),
    "no_of_seats": ("Seats", "No of Seats", "No. of Seats"),
    "vin": ("VIN",),
    "rego_no": ("Registration", "Registration Number", "Registration No"),
    "rego_expiry": ("Reg Expiry", "Registration Expiry Date"),
    "no_of_cylinders": ("Cylinders",),
    "engine_capacity": ("Engine Capacity", "Capacity", "Engine"),
    "exterior_colour": ("Body Colour", "Colour", "Exterior Colour"),
    "key": ("Keys", "Key"),
    "owners_manual": ("Owners Manual", "Owners Manual Available"),
    "service_history": ("Service History",),
    "location": ("Item Location", "Location"),
    "price": ("Current Bid", "Buy Now", "Price"),
    "bids": ("Bids",),
    "time_remaining_or_date_sold": ("Starts", "Sale End", "Closing Time", "Ends"),
}

PICKLES_CONDITION_STATUS_LINES = {
    "comment only",
    "requires quote",
    "rr&p* level 1",
    "rr & p* level 1",
    "rr&p level 1",
    "rr & p level 1",
}

PICKLES_CONDITION_IGNORE_LINES = {
    "damage and description disclaimer",
    "rr & p* = remove refit and/or replace part",
    "rr&p* = remove refit and/or replace part",
    "pdr** = paintless dent repair",
    "no visible damage",
    "no damage visible",
    "no longer available",
}

PICKLES_CONDITION_STOP_LINES = {
    "item info",
    "item info (print)",
    "tyres",
    "location",
    "item location",
    "add note",
    "add a note",
    "enquire now",
    "products",
    "sale details",
    "sale info",
    "fees",
    "overview",
    "item details",
    "description",
    "documents",
    "contact",
}

PICKLES_CONDITION_BOUNDARY_PHRASES = (
    "this description indicates the motor vehicle has a body appraisal",
    "damage and description disclaimer",
    "sorry this item is no longer available",
    "find similar items",
    "view similar items",
    "we're not accepting more bids for this item",
    "please refresh browser for updated status",
)

PICKLES_METADATA_SECTION_MARKERS = {
    "keys",
    "spare keys",
    "compliance date",
    "build date",
    "odometer (showing on)",
}
PICKLES_RISK_NOTE_MARKERS = (
    "please note",
    "this vehicle will need to be transported",
    "this asset is a non runner",
    "this asset is a non-runner",
    "tilt tray required",
)


@dataclass(frozen=True)
class BrowserListing:
    source: str
    url: str
    title_hint: str = ""


@dataclass(frozen=True)
class DiscoveryResult:
    listings: list[BrowserListing]
    pages_planned: int
    pages_visited: int
    pagination_exhausted: bool
    page_cap_reached: bool
    blocked_pages: int


def _with_query_params(url: str, **updates: object) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in updates.items():
        query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_source_list_urls(source: str, max_list_pages: int) -> list[str]:
    if source == "slattery":
        return SOURCE_URLS[source]
    page_count = max_list_pages if max_list_pages > 0 else MAX_AUTO_LIST_PAGES[source]
    urls: list[str] = []
    if source == "pickles":
        base = SOURCE_URLS[source][0]
        for page in range(1, page_count + 1):
            urls.append(_with_query_params(base, page=page))
        return urls
    if source == "manheim":
        # Interleave locations by page so pagination exhaustion is assessed
        # across both Sydney and Melbourne rather than stopping after the
        # first location's empty tail.
        for page in range(1, page_count + 1):
            for base in SOURCE_URLS[source]:
                urls.append(
                    _with_query_params(
                        base,
                        navType="P",
                        sortBy="buildyear desc",
                        page=page,
                        rowsPerPage=120,
                    )
                )
        return urls
    return SOURCE_URLS[source]


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _normalise_url(url: object) -> str:
    text = _clean_text(url)
    if not text:
        return ""
    return text.split("#", 1)[0]


def _extract_money(value: object) -> str:
    text = _clean_text(value)
    match = re.search(r"\$?\s*([0-9][0-9,]*(?:\.\d+)?)", text)
    return match.group(1).replace(",", "") if match else ""


def _extract_int(value: object) -> str:
    text = _clean_text(value)
    match = re.search(r"([0-9][0-9,]*)", text)
    return match.group(1).replace(",", "") if match else ""


def _pickles_stock_number(url: str) -> str:
    match = re.search(r"/(\d+)(?:[/?#]|$)", _normalise_url(url))
    return match.group(1) if match else ""


def _normalise_embedded_page_text(text: str) -> str:
    return html.unescape(str(text)).replace('\\"', '"').replace("\\/", "/")


def _extract_jsonish_value(text: str, field: str) -> str:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*("[^"]*"|null|true|false|-?\d+(?:\.\d+)?)', text)
    if not match:
        return ""
    value = match.group(1)
    if value in {"null", "true", "false"}:
        return "" if value == "null" else value
    return value.strip('"')


def _pickles_embedded_listing_window(url: str, text: str) -> str:
    normalised = _normalise_embedded_page_text(text)
    stock = _pickles_stock_number(url)
    if not stock:
        return normalised
    index = normalised.find(f'"stockNumber":"{stock}"')
    if index < 0:
        index = normalised.find(stock)
    if index < 0:
        return normalised
    return normalised[max(0, index - 15_000) : index + 40_000]


def _extract_pickles_terminal_fields(url: str, text: str) -> dict[str, str]:
    normalised = _normalise_embedded_page_text(text)
    visible_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", normalised)).strip()
    window = _pickles_embedded_listing_window(url, text)
    fields = {
        "date_sold": _extract_jsonish_value(window, "dateSold"),
        "lot_end_time": _extract_jsonish_value(window, "lotEndTime"),
        "sale_status": _extract_jsonish_value(window, "saleStatus"),
        "status": _extract_jsonish_value(window, "status"),
        "no_longer_available": "1" if re.search(r"\bno longer available\b", visible_text, re.IGNORECASE) else "",
        "price": "",
    }
    for price_field in (
        "finalSalePrice",
        "salePrice",
        "soldPrice",
        "hammerPrice",
        "currentBid",
        "currentBidAmount",
        "currentBidValue",
        "askingPrice",
        "fixedPrice",
    ):
        price = _extract_money(_extract_jsonish_value(window, price_field))
        if price:
            fields["price"] = price
            break
    return fields


def _apply_pickles_terminal_fields(row: dict[str, object], terminal: dict[str, str]) -> None:
    terminal_status_text = " ".join(
        _clean_text(terminal.get(key, ""))
        for key in ("sale_status", "status")
    ).lower()
    is_terminal = bool(
        terminal.get("date_sold")
        or terminal.get("no_longer_available")
        or re.search(r"\b(sold|closed|ended|complete|completed)\b", terminal_status_text)
    )
    if not is_terminal:
        return
    row["status"] = "Sold"
    if terminal.get("date_sold"):
        row["date_sold"] = terminal["date_sold"]
        row["time_remaining_or_date_sold"] = terminal["date_sold"]
    elif terminal.get("lot_end_time"):
        row["time_remaining_or_date_sold"] = terminal["lot_end_time"]
    elif not row.get("time_remaining_or_date_sold"):
        row["time_remaining_or_date_sold"] = "Sold"
    if not row.get("price") and terminal.get("price"):
        row["price"] = terminal["price"]


def _slattery_asset_id(url: str) -> str:
    match = re.search(r"/assets/(\d+)(?:[/?#]|$)", _normalise_url(url))
    return match.group(1) if match else ""


def _extract_slattery_live_fields(url: str, text: str) -> dict[str, str]:
    normalised = _normalise_embedded_page_text(text)
    asset_id = _slattery_asset_id(url)
    if not asset_id:
        return {"price": "", "bids": "", "closes_at": ""}

    bids_marker = normalised.find('"auctionAssetBids"')
    asset_window = normalised if bids_marker < 0 else normalised[max(0, bids_marker - 30_000) : bids_marker]
    bid_amounts = [
        float(value)
        for value in re.findall(
            rf'"assetId"\s*:\s*{re.escape(asset_id)}\b[^{{}}]{{0,500}}?"bidAmount"\s*:\s*([0-9]+(?:\.[0-9]+)?)',
            normalised,
            re.DOTALL,
        )
    ]
    starting_bid = _extract_money(_extract_jsonish_value(asset_window, "startingBidAmount"))
    price = ""
    if bid_amounts:
        highest_bid = max(bid_amounts)
        price = str(int(highest_bid)) if highest_bid.is_integer() else str(highest_bid)
    elif starting_bid:
        price = starting_bid

    return {
        "price": price,
        "bids": _extract_int(_extract_jsonish_value(asset_window, "bidCount")) or str(len(bid_amounts)),
        "closes_at": _clean_text(_extract_jsonish_value(asset_window, "closesAt")),
    }


def _apply_slattery_live_fields(row: dict[str, object], fields: dict[str, str]) -> None:
    for row_field, source_field in (
        ("price", "price"),
        ("bids", "bids"),
        ("time_remaining_or_date_sold", "closes_at"),
    ):
        if not row.get(row_field) and fields.get(source_field):
            row[row_field] = fields[source_field]


def _normalise_transmission(value: object) -> str:
    text = _clean_text(value)
    lower = text.lower()
    if "manual" in lower:
        return "Manual"
    if "cvt" in lower:
        return "CVT"
    if "auto" in lower or "dsg" in lower or "sports" in lower:
        return "Automatic"
    return text


def _normalise_fuel(value: object) -> str:
    text = _clean_text(value)
    lower = text.lower()
    if "hybrid" in lower:
        return "Hybrid"
    if "diesel" in lower or re.search(r"\b\d(?:\.\d)?\s*d\.?t\b", lower):
        return "Diesel"
    if "electric" in lower or lower == "ev":
        return "Electric"
    if "petrol" in lower or "unleaded" in lower:
        return "Petrol"
    return text


def _normalise_body(value: object, title: str = "") -> str:
    text = _clean_text(value)
    value_lower = text.lower()
    for keyword, body in BODY_KEYWORDS:
        if keyword in value_lower:
            return body
    haystack = f"{text} {title}".lower()
    for keyword, body in BODY_KEYWORDS:
        if keyword in haystack:
            return body
    return text


def _extract_state_location(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    state = re.search(r"\b(NSW|VIC|QLD|SA|WA|TAS|ACT|NT)\b", text, re.IGNORECASE)
    if state:
        return text
    return text


def _previous_value(lines: list[str], label: str) -> str:
    target = label.lower()
    label_set = {alias.lower() for aliases in FIELD_ALIASES.values() for alias in aliases}
    for index, line in enumerate(lines):
        if line.lower().rstrip(":") != target or index == 0:
            continue
        for value in reversed(lines[max(0, index - 4) : index]):
            clean = _clean_text(value)
            if not clean:
                continue
            if clean.lower().rstrip(":") in label_set:
                continue
            return clean
    return ""


def split_detail_lines(text: str) -> list[str]:
    return [_clean_text(line) for line in text.splitlines() if _clean_text(line)]


def extract_label_values(lines: Iterable[str]) -> dict[str, str]:
    items = list(lines)
    values: dict[str, str] = {}
    alias_pairs = [(field, alias.lower()) for field, aliases in FIELD_ALIASES.items() for alias in aliases]
    for index, line in enumerate(items):
        clean = _clean_text(line)
        if not clean:
            continue
        for field, alias_lower in alias_pairs:
            if field in values and values[field]:
                continue
            lower = clean.lower().rstrip(":")
            if lower == alias_lower:
                values[field] = _next_value(items, index + 1)
                continue
            prefix = f"{alias_lower}:"
            if lower.startswith(prefix):
                values[field] = clean.split(":", 1)[1].strip()
    return values


def _next_value(lines: list[str], start_index: int) -> str:
    label_set = {alias.lower() for aliases in FIELD_ALIASES.values() for alias in aliases}
    for value in lines[start_index : start_index + 4]:
        clean = _clean_text(value)
        if not clean:
            continue
        if clean.lower().rstrip(":") in label_set:
            continue
        return clean
    return ""


def parse_title_parts(title: str, fallback_text: str = "") -> dict[str, str]:
    text = _clean_text(title) or _clean_text(fallback_text)
    text = re.sub(r"\b(used car for sale|pickles au|slattery auctions|car auctions australia)\b", "", text, flags=re.I)
    text = re.sub(r"^used\s+", "", text, flags=re.I)
    year_match = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", text)
    year = year_match.group(1) if year_match else ""
    after_year = text[year_match.end() :] if year_match else text
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", after_year)
    make = ""
    model = ""
    variant_tokens: list[str] = []
    if tokens:
        first = tokens[0].lower()
        make = MAKE_ALIASES.get(first, tokens[0].title())
        if len(tokens) > 1:
            model, variant_tokens = _parse_model_tokens(first, tokens[1:])
    return {
        "year": year,
        "make": make,
        "model": model,
        "variant": " ".join(variant_tokens),
    }


def _parse_model_tokens(make_key: str, tokens: list[str]) -> tuple[str, list[str]]:
    if not tokens:
        return "", []
    if make_key == "mazda" and tokens[0] in {"3", "6"}:
        return tokens[0], tokens[1:]
    lowered = [token.lower() for token in tokens]
    for model_tokens, model_name in sorted(MULTI_WORD_MODELS.items(), key=lambda item: len(item[0]), reverse=True):
        count = len(model_tokens)
        if tuple(lowered[:count]) == model_tokens:
            return model_name, tokens[count:]
    raw_model = tokens[0]
    model_key = raw_model.lower()
    if len(tokens) > 1 and f"{model_key}-{tokens[1].lower()}" in MODEL_ALIASES:
        model_key = f"{model_key}-{tokens[1].lower()}"
        return MODEL_ALIASES[model_key], tokens[2:]
    return MODEL_ALIASES.get(model_key, raw_model.title()), tokens[1:]


def _listing_heading_from_lines(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if not re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", line):
            continue
        if not any(make.lower() in line.lower() for make in MAKE_ALIASES.values()):
            continue
        parts = [line]
        if index + 1 < len(lines):
            next_line = lines[index + 1]
            if next_line.lower() not in {"share", "overview", "item info (print)"}:
                parts.append(next_line)
        return " ".join(parts)
    return ""


def parse_listing_text(source: str, url: str, title: str, text: str) -> dict[str, object]:
    lines = split_detail_lines(text)
    labels = extract_label_values(lines)
    body_heading = _listing_heading_from_lines(lines)
    title_parts = parse_title_parts(title, body_heading or text)
    body_title_parts = parse_title_parts(body_heading, title)
    if not title_parts.get("variant") or re.fullmatch(r"\d{5,}", str(title_parts.get("variant", ""))):
        title_parts = {**title_parts, **{k: v for k, v in body_title_parts.items() if v}}
    display_title = body_heading or _clean_text(title)
    row: dict[str, object] = {column: "" for column in LISTING_COLUMNS}
    row.update(
        {
            "source": source,
            "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "title": display_title,
            "url": _normalise_url(url),
            "scrape_status": "parsed",
        }
    )
    for field in ("year", "make", "model", "variant"):
        row[field] = labels.get(field) or title_parts.get(field, "")
    if source == "slattery" and labels.get("variant"):
        asset_parts = parse_title_parts(labels["variant"])
        for field in ("year", "make", "model", "variant"):
            row[field] = labels.get(field) or asset_parts.get(field, "") or row.get(field, "")
        labels["transmission"] = _previous_value(lines, "Transmission") or labels.get("transmission", "")
        labels["fuel_type"] = _previous_value(lines, "Fuel Type") or labels.get("fuel_type", "")
        labels["odometer_reading"] = _previous_value(lines, "Odometer") or labels.get("odometer_reading", "")

    row["body_type"] = _normalise_body(labels.get("body_type", ""), f"{row.get('title', '')} {text}")
    row["transmission"] = _normalise_transmission(labels.get("transmission", ""))
    row["fuel_type"] = _normalise_fuel(labels.get("fuel_type", "") or f"{row.get('variant', '')} {display_title}")
    row["odometer_reading"] = _extract_int(labels.get("odometer_reading", ""))
    row["no_of_seats"] = _extract_int(labels.get("no_of_seats", ""))
    row["vin"] = _clean_text(labels.get("vin", ""))
    row["rego_no"] = _clean_text(labels.get("rego_no", ""))
    row["rego_expiry"] = _clean_text(labels.get("rego_expiry", ""))
    row["no_of_cylinders"] = _extract_int(labels.get("no_of_cylinders", ""))
    row["engine_capacity"] = _clean_text(labels.get("engine_capacity", ""))
    row["exterior_colour"] = _clean_text(labels.get("exterior_colour", ""))
    row["key"] = _clean_text(labels.get("key", ""))
    row["owners_manual"] = _clean_text(labels.get("owners_manual", ""))
    row["service_history"] = _clean_text(labels.get("service_history", ""))
    row["location"] = _extract_state_location(labels.get("location", ""))
    row["price"] = _extract_money(labels.get("price", ""))
    row["bids"] = _extract_int(labels.get("bids", ""))
    row["time_remaining_or_date_sold"] = _clean_text(labels.get("time_remaining_or_date_sold", ""))
    if source == "pickles":
        _apply_pickles_terminal_fields(row, _extract_pickles_terminal_fields(url, text))
    elif source == "slattery":
        _apply_slattery_live_fields(row, _extract_slattery_live_fields(url, text))
    row["general_condition"] = _extract_pickles_condition_text(lines) if source == "pickles" else _extract_condition_text(lines)
    return row


def _strip_pickles_condition_number(line: str) -> str:
    return re.sub(r"^\s*\d+\.\s*", "", _clean_text(line)).strip()


def _is_pickles_condition_noise(line: str) -> bool:
    lower = _clean_text(line).lower().rstrip(":")
    return (
        not lower
        or lower in PICKLES_CONDITION_STATUS_LINES
        or lower in PICKLES_CONDITION_IGNORE_LINES
        or bool(re.fullmatch(r"attachments?\s*\(\d+\)", lower))
        or lower.startswith("rr & p")
        or lower.startswith("rr&p")
        or lower.startswith("pdr")
    )


def _is_pickles_condition_boundary(line: str) -> bool:
    lower = _clean_text(line).lower().rstrip(":")
    return lower in PICKLES_CONDITION_STOP_LINES or any(
        phrase in lower for phrase in PICKLES_CONDITION_BOUNDARY_PHRASES
    )


def _normalise_pickles_damage(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;")
    return text.lower()


def _looks_like_pickles_metadata_section(lines: list[str], start_index: int) -> bool:
    probe = {
        _strip_pickles_condition_number(line).lower().rstrip(":")
        for line in lines[start_index : start_index + 30]
    }
    identity_markers = {"keys", "spare keys"}
    dated_markers = {"compliance date", "build date", "odometer (showing on)"}
    return identity_markers.issubset(probe) and bool(dated_markers & probe)


def _extract_pickles_metadata_risk_notes(lines: list[str], start_index: int) -> str:
    notes: list[str] = []
    for line in lines[start_index:]:
        cleaned = _clean_text(line).strip(" *.")
        lowered = cleaned.lower()
        if (
            _is_pickles_condition_boundary(cleaned)
            or lowered in PICKLES_CONDITION_IGNORE_LINES
            or re.match(r"^[A-Za-z .'-]+,\s*(NSW|VIC|QLD|SA|WA|TAS|ACT|NT)$", cleaned, re.IGNORECASE)
        ):
            break
        for marker in PICKLES_RISK_NOTE_MARKERS:
            marker_index = lowered.find(marker)
            if marker_index < 0:
                continue
            note = cleaned[marker_index:].strip(" *.")
            if note:
                notes.append(note)
            break
    return "\n".join(dict.fromkeys(notes))


def _looks_like_pickles_metadata_condition(condition: str) -> bool:
    normalized = _clean_text(condition).lower()
    dated_or_identity_markers = (
        "compliance date",
        "build date",
        "odometer (showing on)",
        "registration",
        " vin",
    )
    return "keys spare keys" in normalized and sum(
        marker in normalized for marker in dated_or_identity_markers
    ) >= 2


def _extract_pickles_condition_text(lines: list[str]) -> str:
    start_index = None
    for index, line in enumerate(lines):
        if _clean_text(line).lower().startswith("condition details"):
            start_index = index + 1
            break
    if start_index is None:
        return _extract_condition_text(lines)
    if _looks_like_pickles_metadata_section(lines, start_index):
        return _extract_pickles_metadata_risk_notes(lines, start_index)

    snippets: list[str] = []
    index = start_index
    while index < len(lines):
        raw_component = _strip_pickles_condition_number(lines[index])
        component_lower = raw_component.lower().rstrip(":")
        if component_lower == "tyres" and not snippets:
            index += 1
            continue
        if snippets and re.match(r"^[A-Za-z .'-]+,\s*(NSW|VIC|QLD|SA|WA|TAS|ACT|NT)$", raw_component, re.IGNORECASE):
            break
        if _is_pickles_condition_boundary(raw_component):
            break
        if _is_pickles_condition_noise(raw_component):
            index += 1
            continue

        damage = ""
        lookahead = index + 1
        while lookahead < len(lines):
            candidate = _strip_pickles_condition_number(lines[lookahead])
            if _is_pickles_condition_boundary(candidate):
                break
            if _is_pickles_condition_noise(candidate):
                lookahead += 1
                continue
            damage = _normalise_pickles_damage(candidate)
            break

        if damage:
            snippets.append(f"{raw_component} {damage}.")
            index = lookahead + 1
        else:
            index += 1

    if not snippets:
        return ""

    condition = "\n".join(dict.fromkeys(snippets))
    if _looks_like_pickles_metadata_condition(condition):
        return _extract_pickles_metadata_risk_notes(lines, start_index)
    return condition


def _extract_condition_text(lines: list[str]) -> str:
    condition_labels = (
        "Condition Details",
        "Condition Report",
        "Asset Condition",
        "Body Condition",
        "Trim Condition",
        "Seat Condition",
        "Carpet Condition",
        "Paint Condition",
        "Brake Condition",
        "Damage",
        "Damage Notes",
        "Comments",
    )
    snippets: list[str] = []
    lower_labels = {label.lower() for label in condition_labels}
    for index, line in enumerate(lines):
        lower = line.lower().rstrip(":")
        if lower in lower_labels:
            value = _next_value(lines, index + 1)
            if value and value.lower() not in {"overview", "item details"}:
                snippets.append(f"{line}: {value}")
        elif lower.startswith("damage "):
            snippets.append(line)
    return "\n".join(dict.fromkeys(snippets))


def tag_with_curve_support(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    curves_df = load_curves()
    tagged = tag_dataframe(
        df,
        source="external_auction_sources",
        require_price=False,
        filter_unclassified=False,
        append_log=False,
    )
    tagged["curve_tag"] = tagged["canonical_tag"].apply(
        lambda value: resolve_curve_canonical_tag(value, curves_df=curves_df)
    )
    return tagged


def filter_curve_supported(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    curves_df = load_curves()
    curve_tags = {
        str(value).strip()
        for value in curves_df.get("canonical_tag", pd.Series(dtype="object")).dropna().astype(str).tolist()
        if str(value).strip()
    }
    tagged = tag_with_curve_support(df)
    eligible = tagged.apply(
        lambda row: is_canonical_eligible(row.get("canonical_tag"), row.get("canonical_reason"))
        and str(row.get("curve_tag", "")).strip() in curve_tags,
        axis=1,
    )
    return tagged[eligible].copy().reset_index(drop=True)


def tag_discovered_links(listings: Iterable[BrowserListing]) -> pd.DataFrame:
    rows = []
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for listing in listings:
        row = parse_listing_text(listing.source, listing.url, listing.title_hint, listing.title_hint)
        row["source"] = listing.source
        row["url"] = listing.url
        row["title_hint"] = listing.title_hint
        rows.append(row)
    if not rows:
        return pd.DataFrame(columns=LINK_COLUMNS)
    tagged = tag_with_curve_support(pd.DataFrame(rows))
    curves_df = load_curves()
    curve_tags = {
        str(value).strip()
        for value in curves_df.get("canonical_tag", pd.Series(dtype="object")).dropna().astype(str).tolist()
        if str(value).strip()
    }
    detail_worthy_reasons = {
        "[AMBIG_BADGE]",
        "[AMBIG_FUEL]",
        "[AMBIG_TRANS]",
        "[AMBIG_DRIVETRAIN]",
        "[BAD_PARSE]",
    }
    out_rows = []
    for _, row in tagged.iterrows():
        title_hint = _clean_text(row.get("title_hint", ""))
        curve_tag = str(row.get("curve_tag", "")).strip()
        reason = str(row.get("canonical_reason", "")).strip()
        selected = (
            not title_hint
            or (
                is_canonical_eligible(row.get("canonical_tag"), row.get("canonical_reason"))
                and curve_tag in curve_tags
            )
            or reason in detail_worthy_reasons
        )
        out_rows.append(
            {
                "source": row.get("source", ""),
                "discovered_at": timestamp,
                "url": row.get("url", ""),
                "title_hint": title_hint,
                "canonical_tag": row.get("canonical_tag", ""),
                "canonical_reason": row.get("canonical_reason", ""),
                "curve_tag": curve_tag,
                "selected_for_detail": "1" if selected else "0",
            }
        )
    return pd.DataFrame(out_rows).reindex(columns=LINK_COLUMNS, fill_value="")


def _trim_process_memory() -> None:
    gc.collect()
    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL("libc.so.6")
        malloc_trim = libc.malloc_trim
    except (AttributeError, OSError):
        return
    malloc_trim(0)

async def _new_browser_context(playwright: object, *, headless: bool) -> tuple[object, object]:
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        locale="en-AU",
    )
    return browser, context


async def _scrape_detail_batches(
    playwright: object,
    listings: list[BrowserListing],
    *,
    headless: bool,
    detail_timeout_ms: int,
    detail_wait_ms: int,
    browser_recycle_size: int,
    detail_batch_size: int = DETAIL_BATCH_SIZE,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    batch_size = max(1, detail_batch_size)
    recycle_size = max(batch_size, browser_recycle_size)
    for recycle_start in range(0, len(listings), recycle_size):
        recycle_group = listings[recycle_start : recycle_start + recycle_size]
        print(
            f"Detail browser cycle {recycle_start // recycle_size + 1}: {len(recycle_group)} listing(s)",
            flush=True,
        )
        browser, context = await _new_browser_context(playwright, headless=headless)
        try:
            for batch_start in range(0, len(recycle_group), batch_size):
                detail_batch = recycle_group[batch_start : batch_start + batch_size]
                detail_rows = await asyncio.gather(
                    *(
                        scrape_detail(
                            context,
                            listing,
                            detail_timeout_ms=detail_timeout_ms,
                            detail_wait_ms=detail_wait_ms,
                        )
                        for listing in detail_batch
                    )
                )
                records.extend(detail_rows)
                for listing, row in zip(detail_batch, detail_rows):
                    title = _clean_text(row.get("title", ""))
                    print(f"  parsed {listing.source}: {title[:90] or listing.url}", flush=True)
        finally:
            await context.close()
            await browser.close()
            _trim_process_memory()
    return records


async def _discover_source_links_with_browser_recycling(
    playwright: object,
    source: str,
    urls: list[str],
    *,
    headless: bool,
    browser_recycle_pages: int,
) -> DiscoveryResult:
    browser: object | None = None
    context: object | None = None
    pages_in_cycle = 0
    recycle_pages = max(1, browser_recycle_pages)

    async def load_page_batch(batch_urls: list[str]) -> list[tuple[int, list[list[str]], str]]:
        nonlocal browser, context, pages_in_cycle
        if context is None or (pages_in_cycle and pages_in_cycle + len(batch_urls) > recycle_pages):
            if context is not None:
                await context.close()
            if browser is not None:
                await browser.close()
            _trim_process_memory()
            browser, context = await _new_browser_context(playwright, headless=headless)
            pages_in_cycle = 0
            print(
                f"{source}: discovery browser cycle for next {min(recycle_pages, len(urls))} page(s)",
                flush=True,
            )
        page_results = await asyncio.gather(*(_discover_list_page(context, url) for url in batch_urls))
        pages_in_cycle += len(batch_urls)
        return page_results

    try:
        return await discover_source_links(
            None,
            source,
            urls,
            max_details=0,
            page_batch_loader=load_page_batch,
        )
    finally:
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        _trim_process_memory()

async def scrape_sources(
    sources: Iterable[str],
    *,
    max_list_pages_per_source: int,
    max_details_per_source: int,
    headless: bool,
    prefilter_list_to_curves: bool,
    detail_timeout_ms: int,
    detail_wait_ms: int,
    detail_browser_recycle_size: int = DEFAULT_DETAIL_BROWSER_RECYCLE_SIZE,
    discovery_browser_recycle_pages: int = DEFAULT_DISCOVERY_BROWSER_RECYCLE_PAGES,
    detail_batch_size: int = DETAIL_BATCH_SIZE,
    seed_listings: Iterable[BrowserListing] = (),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Playwright is required for external auction scraping.") from exc

    records: list[dict[str, object]] = []
    link_frames: list[pd.DataFrame] = []
    audit_rows: list[dict[str, object]] = []
    seeds_by_source: dict[str, list[BrowserListing]] = {}
    for listing in seed_listings:
        seeds_by_source.setdefault(listing.source, []).append(listing)
    _trim_process_memory()
    async with async_playwright() as playwright:
        for source in sources:
            discovery = await _discover_source_links_with_browser_recycling(
                playwright,
                source,
                build_source_list_urls(source, max_list_pages_per_source),
                headless=headless,
                browser_recycle_pages=discovery_browser_recycle_pages,
            )

            listings = discovery.listings
            links_df = tag_discovered_links(listings)
            link_frames.append(links_df)
            selected_listings = listings
            if prefilter_list_to_curves and not links_df.empty:
                selected_urls = set(
                    links_df.loc[links_df["selected_for_detail"].astype(str).eq("1"), "url"]
                    .dropna()
                    .astype(str)
                    .tolist()
                )
                selected_listings = [listing for listing in listings if listing.url in selected_urls]
            selected_from_discovery = list(selected_listings)
            detail_cap_reached = max_details_per_source > 0 and len(selected_listings) > max_details_per_source
            if max_details_per_source > 0:
                selected_listings = selected_listings[:max_details_per_source]
            seen_selected = {listing.url for listing in selected_listings}
            for seed in seeds_by_source.get(source, []):
                if seed.url in seen_selected:
                    continue
                selected_listings.append(seed)
                seen_selected.add(seed.url)
            print(
                f"{source}: discovered {len(listings)} candidate detail URL(s); "
                f"selected {len(selected_listings)} for detail scrape",
                flush=True,
            )
            records.extend(
                await _scrape_detail_batches(
                    playwright,
                    selected_listings,
                    headless=headless,
                    detail_timeout_ms=detail_timeout_ms,
                    detail_wait_ms=detail_wait_ms,
                    browser_recycle_size=detail_browser_recycle_size,
                    detail_batch_size=detail_batch_size,
                )
            )
            source_records = [row for row in records if str(row.get("source", "")) == source]
            selected_urls = {listing.url for listing in selected_from_discovery}
            scraped_selected_urls = {
                str(row.get("url", ""))
                for row in source_records
                if str(row.get("url", "")) in selected_urls
            }
            detail_errors = sum(
                str(row.get("scrape_status", "")).startswith("error:")
                or str(row.get("scrape_status", "")) in {"parsed_http_401", "parsed_http_403", "parsed_http_429"}
                for row in source_records
                if str(row.get("url", "")) in selected_urls
            )
            unavailable_details = sum(
                str(row.get("scrape_status", "")) == "unavailable_redirect"
                for row in source_records
                if str(row.get("url", "")) in selected_urls
            )
            selected_missing = max(0, len(selected_urls - scraped_selected_urls))
            discovery_status = "blocked" if discovery.blocked_pages else "complete"
            incomplete_reasons: list[str] = []
            if discovery_status == "blocked":
                incomplete_reasons.append("listing discovery blocked by HTTP access response")
            if discovery.page_cap_reached:
                incomplete_reasons.append("configured page safety cap reached before pagination exhaustion")
            if detail_cap_reached:
                incomplete_reasons.append("configured detail cap omitted selected listings")
            if selected_missing:
                incomplete_reasons.append(f"{selected_missing} selected listing(s) were not detail-scraped")
            if detail_errors:
                incomplete_reasons.append(f"{detail_errors} selected detail scrape(s) failed")
            audit_rows.append(
                {
                    "source": source,
                    "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "discovery_status": discovery_status,
                    "completeness_status": "incomplete" if incomplete_reasons else "complete",
                    "list_pages_planned": discovery.pages_planned,
                    "list_pages_visited": discovery.pages_visited,
                    "pagination_exhausted": "1" if discovery.pagination_exhausted else "0",
                    "page_cap_reached": "1" if discovery.page_cap_reached else "0",
                    "blocked_pages": discovery.blocked_pages,
                    "discovered_links": len(listings),
                    "selected_for_detail": len(selected_from_discovery),
                    "detail_cap_reached": "1" if detail_cap_reached else "0",
                    "selected_details_scraped": len(scraped_selected_urls),
                    "selected_details_missing": selected_missing,
                    "selected_details_unavailable": unavailable_details,
                    "detail_errors": detail_errors,
                    "seed_details_scraped": max(0, len(source_records) - len(scraped_selected_urls)),
                    "notes": "; ".join(incomplete_reasons),
                }
            )
    raw_df = pd.DataFrame(records).reindex(columns=LISTING_COLUMNS, fill_value="") if records else pd.DataFrame(columns=LISTING_COLUMNS)
    links_df = pd.concat(link_frames, ignore_index=True, sort=False).reindex(columns=LINK_COLUMNS, fill_value="") if link_frames else pd.DataFrame(columns=LINK_COLUMNS)
    audit_df = pd.DataFrame(audit_rows).reindex(columns=AUDIT_COLUMNS, fill_value="")
    return raw_df, links_df, audit_df

async def _discover_list_page(
    context: object,
    url: str,
) -> tuple[int, list[list[str]], str]:
    """Load one listing page; callers combine several pages in bounded batches."""
    page = await context.new_page()
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(2_500)
        await auto_scroll(page, max_rounds=6, delay_ms=500)
        anchors = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(a => [a.href, (a.innerText || '').trim()])",
        )
        content = await page.content()
        return (int(response.status) if response is not None else 0, anchors, content)
    finally:
        await page.close()


async def discover_source_links(
    context: object,
    source: str,
    urls: Iterable[str],
    *,
    max_details: int,
    page_batch_loader: Callable[
        [list[str]],
        Awaitable[list[tuple[int, list[list[str]], str]]],
    ]
    | None = None,
) -> DiscoveryResult:
    pattern = DETAIL_PATTERNS[source]
    fallback_pattern = DETAIL_URL_FALLBACKS[source]
    listings_by_url: dict[str, BrowserListing] = {}
    list_urls = list(urls)
    pages_visited = 0
    blocked_pages = 0
    consecutive_stale_pages = 0
    stale_page_limit = max(2, len(SOURCE_URLS[source]) * 2)
    pagination_exhausted = source == "slattery"

    def add_listing(clean_url: str, title: str = "") -> None:
        title_hint = _clean_text(title)
        existing = listings_by_url.get(clean_url)
        if existing is None:
            listings_by_url[clean_url] = BrowserListing(source=source, url=clean_url, title_hint=title_hint)
            return
        existing_has_year = bool(re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", existing.title_hint))
        new_has_year = bool(re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title_hint))
        if title_hint and (not existing.title_hint or (new_has_year and not existing_has_year) or len(title_hint) > len(existing.title_hint)):
            listings_by_url[clean_url] = BrowserListing(source=source, url=clean_url, title_hint=title_hint)

    batch_size = 5 if len(list_urls) > 20 else max(1, len(SOURCE_URLS[source]))
    stop_discovery = False
    for batch_start in range(0, len(list_urls), batch_size):
        batch_urls = list_urls[batch_start : batch_start + batch_size]
        page_results = (
            await page_batch_loader(batch_urls)
            if page_batch_loader is not None
            else await asyncio.gather(*(_discover_list_page(context, url) for url in batch_urls))
        )
        pages_visited += len(page_results)
        for status_code, anchors, content in page_results:
            before_count = len(listings_by_url)
            if status_code in {401, 403, 429}:
                blocked_pages += 1
            for href, title in anchors:
                clean_url = _normalise_url(href)
                if not clean_url:
                    continue
                if not pattern.search(clean_url):
                    continue
                add_listing(clean_url, title)
                if max_details > 0 and len(listings_by_url) >= max_details:
                    return DiscoveryResult(
                        listings=list(listings_by_url.values()),
                        pages_planned=len(list_urls),
                        pages_visited=pages_visited,
                        pagination_exhausted=False,
                        page_cap_reached=False,
                        blocked_pages=blocked_pages,
                    )
            for match in fallback_pattern.finditer(content):
                clean_url = _normalise_url(match.group(0))
                if clean_url.startswith("/"):
                    clean_url = f"https://slatteryauctions.com.au{clean_url}"
                if not clean_url:
                    continue
                if not pattern.search(clean_url):
                    continue
                add_listing(clean_url)
                if max_details > 0 and len(listings_by_url) >= max_details:
                    return DiscoveryResult(
                        listings=list(listings_by_url.values()),
                        pages_planned=len(list_urls),
                        pages_visited=pages_visited,
                        pagination_exhausted=False,
                        page_cap_reached=False,
                        blocked_pages=blocked_pages,
                    )
            if len(listings_by_url) == before_count:
                consecutive_stale_pages += 1
            else:
                consecutive_stale_pages = 0
            if source != "slattery" and consecutive_stale_pages >= stale_page_limit:
                pagination_exhausted = True
                stop_discovery = True
                break
        print(
            f"{source}: discovery visited {pages_visited}/{len(list_urls)} list page(s); "
            f"found {len(listings_by_url)} unique detail URL(s)",
            flush=True,
        )
        if stop_discovery:
            break
    page_cap_reached = source != "slattery" and not pagination_exhausted and pages_visited >= len(list_urls)
    return DiscoveryResult(
        listings=list(listings_by_url.values()),
        pages_planned=len(list_urls),
        pages_visited=pages_visited,
        pagination_exhausted=pagination_exhausted,
        page_cap_reached=page_cap_reached,
        blocked_pages=blocked_pages,
    )


async def auto_scroll(page: object, *, max_rounds: int = 12, delay_ms: int = 900) -> None:
    previous_height = 0
    stable_rounds = 0
    for _ in range(max_rounds):
        height = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(delay_ms)
        if height == previous_height:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_height = height
        if stable_rounds >= 2:
            break


async def scrape_detail(
    context: object,
    listing: BrowserListing,
    *,
    detail_timeout_ms: int,
    detail_wait_ms: int,
) -> dict[str, object]:
    page = await context.new_page()
    try:
        response = await page.goto(listing.url, wait_until="domcontentloaded", timeout=detail_timeout_ms)
        await page.wait_for_timeout(detail_wait_ms)
        await prepare_detail_page(page, listing.source)
        title = await page.title()
        text = await page.locator("body").inner_text(timeout=detail_timeout_ms)
        html_text = await page.content()
        row = parse_listing_text(listing.source, page.url, title or listing.title_hint, text)
        if listing.source in {"pickles", "slattery"}:
            response_text = ""
            try:
                if response is not None:
                    response_text = await response.text()
            except Exception:
                response_text = ""
            embedded_text = f"{html_text}\n{response_text}"
            if listing.source == "pickles":
                _apply_pickles_terminal_fields(row, _extract_pickles_terminal_fields(page.url, embedded_text))
            else:
                _apply_slattery_live_fields(row, _extract_slattery_live_fields(page.url, embedded_text))
        status_code = response.status if response is not None else ""
        resolved_url = str(page.url or "")
        unavailable = listing.source == "pickles" and (
            "item-not-available" in resolved_url.lower()
            or "page not found" in str(title or "").lower()
        )
        # Preserve the discovered URL as the stable reconciliation key even if
        # the auction site redirects a withdrawn lot to a generic terminal page.
        row["url"] = listing.url
        row["scrape_status"] = (
            "unavailable_redirect"
            if unavailable
            else (f"parsed_http_{status_code}" if status_code else "parsed")
        )
        return row
    except Exception as exc:
        row = {column: "" for column in LISTING_COLUMNS}
        row.update(
            {
                "source": listing.source,
                "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "url": listing.url,
                "title": listing.title_hint,
                "scrape_status": f"error:{type(exc).__name__}:{str(exc)[:160]}",
            }
        )
        return row
    finally:
        await page.close()


async def prepare_detail_page(page: object, source: str) -> None:
    if source != "pickles":
        return
    try:
        tab = page.locator("button:has-text('Condition Details')").first
        if await tab.count():
            await tab.click(timeout=3_000)
            try:
                await page.locator("text=Tyre (Spare)").first.wait_for(timeout=3_000)
            except Exception:
                await page.wait_for_timeout(1_000)
    except Exception:
        return


def write_outputs(raw_df: pd.DataFrame, links_df: pd.DataFrame, output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    links_path = output_dir / "external_auction_links.csv"
    all_path = output_dir / "external_auction_listings_all.csv"
    matched_path = output_dir / "external_auction_curve_matches.csv"
    tagged = tag_with_curve_support(raw_df)
    matched = filter_curve_supported(tagged)
    write_dataframe_csv_atomic(links_df.reindex(columns=LINK_COLUMNS, fill_value=""), links_path, index=False)
    write_dataframe_csv_atomic(tagged.reindex(columns=LISTING_COLUMNS, fill_value=""), all_path, index=False)
    write_dataframe_csv_atomic(matched.reindex(columns=LISTING_COLUMNS, fill_value=""), matched_path, index=False)
    return links_path, all_path, matched_path


def write_scrape_audit(audit_df: pd.DataFrame, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / "external_auction_scrape_audit.csv"
    write_dataframe_csv_atomic(audit_df.reindex(columns=AUDIT_COLUMNS, fill_value=""), audit_path, index=False)
    return audit_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Pickles, Manheim, and Slattery listings into an isolated curve-matched evidence CSV."
    )
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SOURCE_URLS),
        help="Source to scrape. Can be passed multiple times. Defaults to Pickles, Manheim, and Slattery.",
    )
    parser.add_argument("--max-list-pages-per-source", type=int, default=2)
    parser.add_argument(
        "--max-details-per-source",
        type=int,
        default=25,
        help="Maximum selected detail pages to scrape per source. Use 0 for every selected detail URL.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--headed", action="store_true", help="Run Chromium visibly instead of headless.")
    parser.add_argument("--detail-timeout-ms", type=int, default=20_000)
    parser.add_argument("--detail-wait-ms", type=int, default=1_500)
    parser.add_argument(
        "--discovery-browser-recycle-pages",
        type=int,
        default=DEFAULT_DISCOVERY_BROWSER_RECYCLE_PAGES,
        help="Restart Chromium after this many discovery pages to bound long-run memory use.",
    )
    parser.add_argument(
        "--detail-batch-size",
        type=int,
        default=DETAIL_BATCH_SIZE,
        help="Concurrent detail pages per browser batch.",
    )
    parser.add_argument(
        "--detail-browser-recycle-size",
        type=int,
        default=DEFAULT_DETAIL_BROWSER_RECYCLE_SIZE,
        help="Restart Chromium after this many detail pages to bound long-run memory use.",
    )
    parser.add_argument(
        "--no-prefilter-list-to-curves",
        action="store_true",
        help="Detail-scrape every discovered URL instead of prefiltering list titles to saved curves.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sources = tuple(args.source or DEFAULT_SOURCES)
    raw_df, links_df, audit_df = asyncio.run(
        scrape_sources(
            sources,
            max_list_pages_per_source=args.max_list_pages_per_source,
            max_details_per_source=max(0, args.max_details_per_source),
            headless=not args.headed,
            prefilter_list_to_curves=not args.no_prefilter_list_to_curves,
            detail_timeout_ms=max(5_000, args.detail_timeout_ms),
            detail_wait_ms=max(0, args.detail_wait_ms),
            detail_browser_recycle_size=max(1, args.detail_batch_size, args.detail_browser_recycle_size),
            discovery_browser_recycle_pages=max(1, args.discovery_browser_recycle_pages),
            detail_batch_size=max(1, args.detail_batch_size),
        )
    )
    links_path, all_path, matched_path = write_outputs(raw_df, links_df, args.output_dir)
    audit_path = write_scrape_audit(audit_df, args.output_dir)
    matched_df = pd.read_csv(matched_path) if matched_path.exists() else pd.DataFrame()
    links_df = pd.read_csv(links_path) if links_path.exists() else pd.DataFrame()
    print(f"Wrote {len(links_df)} discovered external link row(s): {links_path}", flush=True)
    print(f"Wrote {len(raw_df)} raw external listing row(s): {all_path}", flush=True)
    print(f"Wrote {len(matched_df)} saved-curve match row(s): {matched_path}", flush=True)
    print(f"Wrote {len(audit_df)} source completeness row(s): {audit_path}", flush=True)
    if not matched_df.empty and "source" in matched_df.columns:
        print("Curve matches by source:", flush=True)
        print(matched_df["source"].value_counts().to_string(), flush=True)


if __name__ == "__main__":
    main()
