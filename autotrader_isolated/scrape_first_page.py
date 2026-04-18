"""Isolated Autotrader first-page scraper (no shared dependencies)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError, async_playwright


DEFAULT_URL = "https://www.autotrader.com.au/for-sale/used/vic/melbourne"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
DEFAULT_OUTPUT = OUTPUT_DIR / "first_page_results.csv"
HISTORY_OUTPUT = OUTPUT_DIR / "listing_history.csv"
STATE_OUTPUT = OUTPUT_DIR / "listing_state.csv"
SNAPSHOT_OUTPUT = OUTPUT_DIR / "latest_snapshot.csv"
RECENT_MARKET_TAGGED_OUTPUT = OUTPUT_DIR / "autotrader_recent_market_tagged.csv"
RECENT_MARKET_WINDOW_DAYS = 90

OUTPUT_COLUMNS = [
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "odometer",
    "transmission",
    "rego",
    "price",
    "fuel_type",
    "location",
    "url",
    "scrape_date",
    "canonical_tag",
    "canonical_reason",
]
DETAIL_COLUMNS = [
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "odometer",
    "transmission",
    "rego",
    "fuel_type",
    "location",
]
STATE_COLUMNS = [
    "url",
    "status",
    "first_seen",
    "last_seen",
    "last_price",
    "last_price_date",
    "sold_date",
    *DETAIL_COLUMNS,
]
HISTORY_COLUMNS = [
    "event_date",
    "event",
    "url",
    "price",
    "previous_price",
    "price_change",
    *DETAIL_COLUMNS,
]

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Connection": "keep-alive",
    "Referer": "https://www.autotrader.com.au/",
    "Upgrade-Insecure-Requests": "1",
}

YEAR_PATTERN = re.compile(r"\b(19[5-9]\d|20[0-3]\d)\b")
SCRAPE_TIMESTAMP: str | None = None

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

try:
    from shared.canonical_tagging import tag_dataframe
except Exception:
    tag_dataframe = None


def _parse_cookie_header(raw_cookie: str) -> dict[str, str]:
    raw_cookie = raw_cookie.strip()
    if raw_cookie.lower().startswith("cookie:"):
        raw_cookie = raw_cookie.split(":", 1)[1].strip()
    cookies: dict[str, str] = {}
    for part in raw_cookie.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value
    return cookies


def fetch_html(url: str, cookie_header: str | None, timeout: int) -> tuple[str, dict[str, object]]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if cookie_header:
        session.cookies.update(_parse_cookie_header(cookie_header))
    response = session.get(url, timeout=timeout)
    if response.status_code == 403:
        raise RuntimeError(
            "Autotrader returned 403. Supply AUTOTRADER_COOKIE or AUTOTRADER_STORAGE_STATE."
        )
    response.raise_for_status()
    meta = {
        "requested_url": url,
        "final_url": response.url,
        "status_code": response.status_code,
        "fetch_mode": "requests",
    }
    return response.text, meta


async def _fetch_html_playwright(
    url: str,
    cookie_header: str | None,
    storage_state: str | None,
    timeout: int,
    browser_name: str,
    headless: bool,
    slow_mo: int,
    wait_until: str,
    block_resources: bool,
) -> tuple[str, dict[str, object]]:
    async with async_playwright() as p:
        channel: str | None = None
        browser_type = p.chromium
        if browser_name == "firefox":
            browser_type = p.firefox
        elif browser_name == "webkit":
            browser_type = p.webkit
        elif browser_name == "chrome":
            browser_type = p.chromium
            channel = "chrome"
        elif browser_name == "msedge":
            browser_type = p.chromium
            channel = "msedge"

        launch_kwargs = {"headless": headless, "slow_mo": slow_mo or 0}
        if channel:
            launch_kwargs["channel"] = channel
        browser = await browser_type.launch(**launch_kwargs)
        context_kwargs: dict[str, object] = {
            "user_agent": DEFAULT_HEADERS["User-Agent"],
            "locale": "en-US",
        }
        if storage_state:
            state_path = Path(storage_state)
            if state_path.exists():
                context_kwargs["storage_state"] = str(state_path)
            else:
                raise RuntimeError(f"AUTOTRADER_STORAGE_STATE not found: {storage_state}")

        context = await browser.new_context(**context_kwargs)
        if block_resources:
            await context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "media", "font"}
                else route.continue_(),
            )
        if cookie_header and "storage_state" not in context_kwargs:
            cookies = [
                {
                    "name": key,
                    "value": value,
                    "domain": "www.autotrader.com.au",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                }
                for key, value in _parse_cookie_header(cookie_header).items()
            ]
            if cookies:
                await context.add_cookies(cookies)

        page = await context.new_page()
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
        except PlaywrightError as exc:
            if "Timeout" not in str(exc):
                raise
            response = None
        if response and response.status == 403:
            raise RuntimeError(
                "Autotrader returned 403 in Playwright. Supply a valid cookie or storage state "
                "and try --playwright-headful --playwright-browser chrome if headless is blocked."
            )
        html = await page.content()
        meta = {
            "requested_url": url,
            "final_url": page.url,
            "status_code": response.status if response else None,
            "fetch_mode": "playwright",
        }
        await context.close()
        await browser.close()
        return html, meta


def fetch_html_with_fallback(
    url: str,
    cookie_header: str | None,
    storage_state: str | None,
    timeout: int,
    browser_name: str,
    headless: bool,
    slow_mo: int,
    wait_until: str,
    block_resources: bool,
    ) -> tuple[str, dict[str, object]]:
    try:
        return fetch_html(url, cookie_header, timeout)
    except RuntimeError as exc:
        if "403" not in str(exc):
            raise
        if not cookie_header and not storage_state:
            raise RuntimeError(
                "Autotrader returned 403. Set AUTOTRADER_COOKIE or AUTOTRADER_STORAGE_STATE first."
            ) from exc
        try:
            return asyncio.run(
                _fetch_html_playwright(
                    url,
                    cookie_header,
                    storage_state,
                    timeout,
                    browser_name,
                    headless,
                    slow_mo,
                    wait_until,
                    block_resources,
                )
            )
        except RuntimeError as runtime_exc:
            if "asyncio.run()" in str(runtime_exc):
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(
                        _fetch_html_playwright(
                            url,
                            cookie_header,
                            storage_state,
                            timeout,
                            browser_name,
                            headless,
                            slow_mo,
                            wait_until,
                            block_resources,
                        )
                    )
                finally:
                    loop.close()
            raise
        except PlaywrightError as playwright_exc:
            raise RuntimeError(f"Playwright failed: {playwright_exc}") from playwright_exc


def _extract_json(script_text: str) -> Optional[Any]:
    if not script_text:
        return None
    try:
        return json.loads(script_text)
    except json.JSONDecodeError:
        return None


def _looks_like_json(text: str) -> bool:
    snippet = text.lstrip()
    return snippet.startswith("{") or snippet.startswith("[")


def _extract_next_data(soup: BeautifulSoup) -> Optional[dict[str, Any]]:
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None
    payload = _extract_json(script.string)
    return payload if isinstance(payload, dict) else None


def _extract_nuxt_data(soup: BeautifulSoup) -> Optional[Any]:
    script = soup.find("script", id="__NUXT_DATA__")
    if not script or not script.string:
        return None
    return _extract_json(script.string)


def _extract_json_ld(soup: BeautifulSoup) -> List[dict[str, Any]]:
    entries: List[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        payload = _extract_json(script.string or "")
        if not payload:
            continue
        if isinstance(payload, list):
            entries.extend([item for item in payload if isinstance(item, dict)])
        elif isinstance(payload, dict):
            entries.append(payload)
    return entries


def _looks_like_listing(obj: dict[str, Any]) -> bool:
    keys = set(obj.keys())
    if "listingId" in keys and any(key in keys for key in ("price", "odometer", "title", "vehicle")):
        return True
    if any(key in keys for key in ("url", "detailUrl", "seoUrl", "listingUrl")) and any(
        key in keys for key in ("price", "odometer", "title", "vehicle", "listingId")
    ):
        return True
    vehicle = obj.get("vehicle")
    if isinstance(vehicle, dict):
        vehicle_keys = set(vehicle.keys())
        if {"make", "model"} <= vehicle_keys and any(
            key in keys for key in ("price", "odometer", "title")
        ):
            return True
    if {"make", "model"} <= keys and any(
        key in keys for key in ("price", "odometer", "title", "year", "variant", "badge", "series")
    ):
        return True
    return False


def _walk_payload(payload: Any) -> Iterable[dict[str, Any]]:
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if _looks_like_listing(item):
                yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _walk_all(payload: Any) -> Iterable[dict[str, Any]]:
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


class _NuxtResolver:
    def __init__(self, payload: list[Any]) -> None:
        self._payload = payload
        self._cache: dict[int, Any] = {}

    def resolve_ref(self, idx: int) -> Any:
        if idx < 0 or idx >= len(self._payload):
            return idx
        if idx in self._cache:
            return self._cache[idx]
        value = self._payload[idx]
        resolved = self._resolve_value(value)
        self._cache[idx] = resolved
        return resolved

    def resolve_value(self, value: Any) -> Any:
        return self._resolve_value(value)

    def _resolve_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve_ref_or_value(val) for key, val in value.items()}
        if isinstance(value, list):
            if len(value) == 2 and value[0] in ("ShallowReactive", "Reactive"):
                target = value[1]
                if isinstance(target, int):
                    return self.resolve_ref(target)
            return [self._resolve_ref_or_value(item) for item in value]
        return value

    def _resolve_ref_or_value(self, value: Any) -> Any:
        if isinstance(value, int) and value >= 0:
            return self.resolve_ref(value)
        return self._resolve_value(value)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("display", "label", "name", "value", "amount", "price", "text"):
            if key in value and value[key] not in (None, ""):
                return _stringify(value[key])
        return ""
    if isinstance(value, list):
        for item in value:
            text = _stringify(item)
            if text:
                return text
        return ""
    return str(value).strip()


def _clean_text_or_blank(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value:
            return ""
        text = str(int(value)) if isinstance(value, float) else str(value)
    else:
        text = str(value).strip()
    if text in {"", "-1", "None", "nan"}:
        return ""
    return text


def _to_int_or_blank(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if text in {"", "-1", "None", "nan"}:
        return ""
    text = text.replace(",", "").replace("$", "")
    text = re.sub(r"[^0-9.]", "", text)
    if not text:
        return ""
    try:
        return int(float(text))
    except ValueError:
        return ""


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return f"https://www.autotrader.com.au{url}"
    return url


def _hostname(url: str) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _page_from_url(url: str) -> Optional[int]:
    if not url:
        return None
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "page" not in query or not query["page"]:
        return None
    return _coerce_int(query["page"][0])


def _extract_price(value: Any) -> str:
    text = _stringify(value)
    if not text:
        return ""
    match = re.search(r"\d[\d,]*", text)
    return match.group(0).replace(",", "") if match else text


def _extract_odometer(value: Any) -> str:
    text = _stringify(value)
    if not text:
        return ""
    match = re.search(r"\d[\d,]*", text)
    return match.group(0).replace(",", "") if match else text


def _extract_year_value(value: Any) -> Optional[int]:
    text = _stringify(value)
    if not text:
        return None
    match = YEAR_PATTERN.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _extract_year(obj: dict[str, Any], vehicle: dict[str, Any], title: str) -> Optional[int]:
    year_keys = (
        "year",
        "yearModel",
        "modelYear",
        "manufactureYear",
        "productionYear",
        "buildYear",
    )
    for key in year_keys:
        year = _extract_year_value(obj.get(key) or vehicle.get(key))
        if year:
            return year
    return _extract_year_value(title)


def _get_scrape_timestamp() -> str:
    global SCRAPE_TIMESTAMP
    if not SCRAPE_TIMESTAMP:
        SCRAPE_TIMESTAMP = datetime.now().isoformat(timespec="seconds")
    return SCRAPE_TIMESTAMP


def _extract_location(obj: dict[str, Any]) -> str:
    location_value = obj.get("location") or obj.get("locationState") or obj.get("state")
    if isinstance(location_value, dict):
        parts = [
            _stringify(location_value.get(key))
            for key in ("suburb", "city", "state", "region", "postcode")
        ]
        return " ".join(part for part in parts if part)
    if location_value:
        return _stringify(location_value)
    suburb = _stringify(obj.get("suburb"))
    state = _stringify(obj.get("state"))
    if suburb or state:
        return " ".join(part for part in (suburb, state) if part)
    return ""


def _split_title(title: str) -> tuple[str, str, str]:
    if not title:
        return "", "", ""
    parts = title.split()
    if len(parts) < 3:
        return "", "", title
    make = parts[1]
    model = parts[2]
    variant = " ".join(parts[3:]) if len(parts) > 3 else ""
    return make, model, variant


def _normalize_listing(obj: dict[str, Any], source: str) -> dict[str, Any]:
    vehicle = obj.get("vehicle") if isinstance(obj.get("vehicle"), dict) else {}
    url = _normalize_url(
        _stringify(
            obj.get("url")
            or obj.get("detailUrl")
            or obj.get("seoUrl")
            or obj.get("listingUrl")
            or vehicle.get("url")
            or vehicle.get("detailUrl")
        )
    )
    title = _stringify(obj.get("title") or obj.get("name") or vehicle.get("title"))
    year = _extract_year(obj, vehicle, title)

    make = _stringify(
        obj.get("make")
        or obj.get("makeName")
        or obj.get("vehicleMake")
        or vehicle.get("make")
        or vehicle.get("makeName")
    )
    model = _stringify(
        obj.get("model")
        or obj.get("modelName")
        or obj.get("vehicleModel")
        or vehicle.get("model")
        or vehicle.get("modelName")
    )
    variant = _stringify(
        obj.get("variant") or obj.get("badge") or obj.get("series") or vehicle.get("variant")
    )

    if not make or not model:
        inferred_make, inferred_model, inferred_variant = _split_title(title)
        make = make or inferred_make
        model = model or inferred_model
        variant = variant or inferred_variant

    body_type = _stringify(
        obj.get("bodyType")
        or obj.get("body_type")
        or obj.get("body_type_style")
        or obj.get("bodytype")
        or obj.get("bodyTypeGroup")
        or obj.get("body_type_group")
        or vehicle.get("bodyType")
        or vehicle.get("body_type")
        or vehicle.get("body_type_style")
        or vehicle.get("bodytype")
        or vehicle.get("bodyTypeGroup")
        or vehicle.get("body_type_group")
    )

    odometer = _extract_odometer(
        obj.get("odometer")
        or obj.get("odometerReading")
        or obj.get("mileage")
        or obj.get("mileageFromOdometer")
        or vehicle.get("odometer")
        or vehicle.get("odometerReading")
        or vehicle.get("mileage")
    )
    transmission = _stringify(
        obj.get("transmission")
        or obj.get("vehicleTransmission")
        or vehicle.get("transmission")
        or vehicle.get("vehicleTransmission")
    )
    rego = _stringify(
        obj.get("rego")
        or obj.get("registration")
        or obj.get("registrationExpiry")
        or obj.get("registration_expiry")
        or obj.get("regoExpiry")
        or obj.get("rego_expiry")
        or vehicle.get("rego")
        or vehicle.get("registration")
        or vehicle.get("registrationExpiry")
        or vehicle.get("regoExpiry")
    )
    price = _extract_price(
        obj.get("advertisedPrice")
        or obj.get("advertised_price")
        or obj.get("price")
        or obj.get("priceValue")
        or obj.get("offers")
        or obj.get("displayPrice")
        or obj.get("display_price")
        or vehicle.get("price")
    )
    fuel_type = _stringify(obj.get("fuelType") or obj.get("fuel") or vehicle.get("fuelType"))
    location = _extract_location(obj) or _extract_location(vehicle)

    return {
        "url": url,
        "year": year,
        "make": make,
        "model": model,
        "variant": variant,
        "body_type": body_type,
        "odometer": odometer,
        "transmission": transmission,
        "rego": rego,
        "price": price,
        "fuel_type": fuel_type,
        "location": location,
        "title": title,
        "source": source,
        "scrape_date": _get_scrape_timestamp(),
    }


def _extract_from_next_data(payload: dict[str, Any]) -> List[dict[str, Any]]:
    rows: List[dict[str, Any]] = []
    for candidate in _walk_payload(payload):
        rows.append(_normalize_listing(candidate, "next_data"))
    return rows


def _extract_from_nuxt_data(payload: Any) -> List[dict[str, Any]]:
    rows: List[dict[str, Any]] = []
    resolver = _NuxtResolver(payload) if isinstance(payload, list) else None
    for candidate in _walk_payload(payload):
        resolved = resolver.resolve_value(candidate) if resolver else candidate
        rows.append(_normalize_listing(resolved, "nuxt_data"))
    return rows


def _extract_search_results(payload: Any) -> Optional[dict[str, Any]]:
    if not isinstance(payload, list):
        return None
    resolver = _NuxtResolver(payload)
    for candidate in _walk_all(payload):
        resolved = resolver.resolve_value(candidate)
        if not isinstance(resolved, dict):
            continue
        keys = set(resolved.keys())
        if {"current_page", "data", "last_page"} <= keys:
            if not resolved.get("next_page_url"):
                derived_next = _derive_next_page_url(resolved)
                if derived_next:
                    resolved["next_page_url"] = derived_next
            return resolved
    return None


def _extract_from_json_ld(payloads: List[dict[str, Any]]) -> List[dict[str, Any]]:
    rows: List[dict[str, Any]] = []
    for payload in payloads:
        if payload.get("@type") == "ItemList":
            elements = payload.get("itemListElement") or []
            for element in elements:
                item = element.get("item") if isinstance(element, dict) else None
                if not isinstance(item, dict):
                    continue
                rows.append(_normalize_listing(item, "json_ld"))
        else:
            rows.append(_normalize_listing(payload, "json_ld"))
    return rows


def _replace_query_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["page"] = [str(page)]
    new_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _prefer_web_next_url(
    next_url: Optional[str],
    seed_url: str,
    debug: dict[str, object],
) -> Optional[str]:
    if not next_url or not seed_url:
        return next_url
    seed_host = _hostname(seed_url)
    next_host = _hostname(next_url)
    if not seed_host or not next_host:
        return next_url
    if seed_host == next_host:
        return next_url
    if not seed_host.endswith("autotrader.com.au"):
        return next_url
    page_number = _page_from_url(next_url)
    if page_number is None:
        current_page = _coerce_int(debug.get("current_page"))
        last_page = _coerce_int(debug.get("last_page"))
        if current_page is not None and (last_page is None or current_page < last_page):
            page_number = current_page + 1
    if page_number is None:
        return next_url
    return _replace_query_page(seed_url, page_number)


def _derive_next_page_url(payload: dict[str, Any]) -> Optional[str]:
    next_url = payload.get("next_page_url")
    if next_url:
        return str(next_url)
    links = payload.get("links")
    if isinstance(links, list):
        for link in links:
            if not isinstance(link, dict):
                continue
            label = str(link.get("label", "")).lower()
            if "next" in label and link.get("url"):
                return str(link["url"])
    if isinstance(links, dict) and links.get("next"):
        return str(links["next"])
    current_page = payload.get("current_page")
    last_page = payload.get("last_page")
    if isinstance(current_page, int) and isinstance(last_page, int) and current_page < last_page:
        seed = payload.get("first_page_url") or payload.get("last_page_url") or payload.get("path")
        if seed:
            seed = str(seed)
            if "page=" in seed:
                return _replace_query_page(seed, current_page + 1)
            if seed.endswith("?") or seed.endswith("&"):
                return f"{seed}page={current_page + 1}"
            if "?" in seed:
                return f"{seed}&page={current_page + 1}"
            return f"{seed}?page={current_page + 1}"
    return None


def _extract_from_api_payload(payload: Any) -> tuple[pd.DataFrame, dict[str, object]]:
    rows: List[dict[str, Any]] = []
    debug: dict[str, object] = {}
    if not isinstance(payload, dict):
        return pd.DataFrame(), debug
    data = payload.get("data") or payload.get("results") or payload.get("items")
    if isinstance(data, list):
        for item in data:
            candidate = item
            if isinstance(item, dict) and isinstance(item.get("_source"), dict):
                candidate = item["_source"]
            if isinstance(candidate, dict):
                rows.append(_normalize_listing(candidate, "api"))
    for key in ("current_page", "last_page", "total", "next_page_url", "prev_page_url"):
        if key in payload:
            debug[key] = payload.get(key)
    if "next_page_url" not in debug:
        derived_next = _derive_next_page_url(payload)
        if derived_next:
            debug["next_page_url"] = derived_next
    df = pd.DataFrame(rows)
    debug["api_rows"] = len(df)
    return df, debug


def _dedupe(rows: List[dict[str, Any]]) -> List[dict[str, Any]]:
    seen: set[str] = set()
    unique: List[dict[str, Any]] = []
    for row in rows:
        key = row.get("url") or f"{row.get('title')}|{row.get('price')}"
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _is_useful_row(row: dict[str, Any]) -> bool:
    if not row.get("url"):
        return False
    if any(row.get(key) for key in ("make", "model", "price", "odometer", "transmission", "fuel_type")):
        return True
    return False


def _parse_first_page(html: str) -> tuple[pd.DataFrame, dict[str, int]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[dict[str, Any]] = []
    debug = {"next_data_rows": 0, "nuxt_data_rows": 0, "json_ld_rows": 0}
    if "Page not found:" in html or "You've gone off road" in html:
        debug["error"] = "not_found"
        return pd.DataFrame(), debug

    next_data = _extract_next_data(soup)
    if next_data:
        next_rows = _extract_from_next_data(next_data)
        rows.extend(next_rows)
        debug["next_data_rows"] = len(next_rows)

    nuxt_data = _extract_nuxt_data(soup)
    if nuxt_data:
        nuxt_rows = _extract_from_nuxt_data(nuxt_data)
        rows.extend(nuxt_rows)
        debug["nuxt_data_rows"] = len(nuxt_rows)
        search_results = _extract_search_results(nuxt_data)
        if search_results:
            debug["current_page"] = search_results.get("current_page")
            debug["last_page"] = search_results.get("last_page")
            debug["total"] = search_results.get("total")
            debug["next_page_url"] = search_results.get("next_page_url")
            debug["prev_page_url"] = search_results.get("prev_page_url")

    json_ld = _extract_json_ld(soup)
    if json_ld:
        ld_rows = _extract_from_json_ld(json_ld)
        rows.extend(ld_rows)
        debug["json_ld_rows"] = len(ld_rows)

    rows = _dedupe([row for row in rows if _is_useful_row(row)])
    df = pd.DataFrame(rows)
    debug["deduped_rows"] = len(df)
    return df, debug


def _format_output(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    trimmed = df.copy()
    for col in OUTPUT_COLUMNS:
        if col not in trimmed.columns:
            trimmed[col] = ""
    trimmed = trimmed[OUTPUT_COLUMNS]
    trimmed["year"] = trimmed["year"].apply(_to_int_or_blank)
    trimmed["variant"] = trimmed["variant"].apply(_clean_text_or_blank)
    trimmed["body_type"] = trimmed["body_type"].apply(_clean_text_or_blank)
    trimmed["odometer"] = trimmed["odometer"].apply(_to_int_or_blank)
    trimmed["price"] = trimmed["price"].apply(_to_int_or_blank)
    trimmed["rego"] = trimmed["rego"].apply(_clean_text_or_blank)
    trimmed["make"] = trimmed["make"].apply(_clean_text_or_blank)
    trimmed["model"] = trimmed["model"].apply(_clean_text_or_blank)
    trimmed["transmission"] = trimmed["transmission"].apply(_clean_text_or_blank)
    trimmed["fuel_type"] = trimmed["fuel_type"].apply(_clean_text_or_blank)
    trimmed["location"] = trimmed["location"].apply(_clean_text_or_blank)
    trimmed["url"] = trimmed["url"].apply(_clean_text_or_blank)
    trimmed["scrape_date"] = trimmed["scrape_date"].apply(_clean_text_or_blank)
    trimmed["canonical_tag"] = trimmed["canonical_tag"].apply(_clean_text_or_blank)
    trimmed["canonical_reason"] = trimmed["canonical_reason"].apply(_clean_text_or_blank)
    return trimmed


def _apply_canonical_tagging(df: pd.DataFrame) -> pd.DataFrame:
    if tag_dataframe is None or df is None or df.empty:
        return df
    return tag_dataframe(
        df,
        source="autotrader",
        require_price=True,
        filter_unclassified=False,
        append_log=True,
    )


def _merge_existing_output(
    new_df: pd.DataFrame, output_path: Path
) -> tuple[pd.DataFrame, int, int]:
    if new_df.empty:
        return new_df, 0, 0
    if not output_path.exists():
        formatted = _format_output(new_df)
        return formatted, len(formatted), 0
    existing_rows = _load_existing_rows(output_path)
    existing_keys: set[str] = set()
    deduped_existing: List[dict[str, Any]] = []
    for row in existing_rows:
        keys = _row_keys(row)
        if not keys or any(key in existing_keys for key in keys):
            continue
        existing_keys.update(keys)
        deduped_existing.append(row)
    new_rows = new_df.fillna("").to_dict("records")
    seen_keys = set(existing_keys)
    merged_rows = list(deduped_existing)
    for row in new_rows:
        keys = _row_keys(row)
        if not keys or any(key in seen_keys for key in keys):
            continue
        seen_keys.update(keys)
        merged_rows.append(row)
    merged_df = _format_output(pd.DataFrame(merged_rows))
    added = max(len(merged_df) - len(deduped_existing), 0)
    return merged_df, added, len(deduped_existing)


def _load_resume_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_resume_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=True, indent=2)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(path)


def _write_checkpoint(
    rows: List[dict[str, Any]], output_path: Path, merge_existing: bool
) -> None:
    if not rows:
        return
    df = _format_output(pd.DataFrame(rows))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if merge_existing and output_path.exists():
        merged_df, _, _ = _merge_existing_output(df, output_path)
        merged_df.to_csv(output_path, index=False)
        return
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    df.to_csv(temp_path, index=False)
    temp_path.replace(output_path)


def _row_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    url = _clean_text_or_blank(row.get("url"))
    if url:
        keys.append(f"url:{url}")
    base_parts = [
        _clean_text_or_blank(row.get("make")),
        _clean_text_or_blank(row.get("model")),
        _clean_text_or_blank(row.get("variant")),
        _clean_text_or_blank(row.get("odometer")),
        _clean_text_or_blank(row.get("price")),
        _clean_text_or_blank(row.get("location")),
    ]
    if any(base_parts):
        base_key = "row:" + "|".join(base_parts)
        keys.append(base_key)
        year_value = _clean_text_or_blank(row.get("year"))
        if year_value:
            year_key = "row:" + "|".join([year_value, *base_parts])
            if year_key not in keys:
                keys.append(year_key)
    return keys


def _matches_priority_state(location: Any, state: str) -> bool:
    if not location or not state:
        return False
    loc = str(location).upper()
    state_token = state.strip().upper()
    if not state_token:
        return False
    state_map = {
        "VIC": {"VIC", "VICTORIA"},
        "VICTORIA": {"VIC", "VICTORIA"},
        "NSW": {"NSW", "NEW SOUTH WALES"},
        "NEW SOUTH WALES": {"NSW", "NEW SOUTH WALES"},
        "QLD": {"QLD", "QUEENSLAND"},
        "QUEENSLAND": {"QLD", "QUEENSLAND"},
        "SA": {"SA", "SOUTH AUSTRALIA"},
        "SOUTH AUSTRALIA": {"SA", "SOUTH AUSTRALIA"},
        "WA": {"WA", "WESTERN AUSTRALIA"},
        "WESTERN AUSTRALIA": {"WA", "WESTERN AUSTRALIA"},
        "TAS": {"TAS", "TASMANIA"},
        "TASMANIA": {"TAS", "TASMANIA"},
        "ACT": {"ACT", "AUSTRALIAN CAPITAL TERRITORY"},
        "AUSTRALIAN CAPITAL TERRITORY": {"ACT", "AUSTRALIAN CAPITAL TERRITORY"},
        "NT": {"NT", "NORTHERN TERRITORY"},
        "NORTHERN TERRITORY": {"NT", "NORTHERN TERRITORY"},
    }
    tokens = state_map.get(state_token, {state_token})
    for token in tokens:
        if re.search(rf"\\b{re.escape(token)}\\b", loc):
            return True
    return False


def _load_existing_rows(output_path: Path) -> List[dict[str, Any]]:
    if not output_path.exists():
        return []
    try:
        df = pd.read_csv(output_path)
    except Exception:
        return []
    if df.empty:
        return []
    return df.fillna("").to_dict("records")


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return text == "" or text.lower() == "nan"


def _coerce_price_value(value: Any) -> Optional[int]:
    if _is_blank(value):
        return None
    if isinstance(value, int):
        return int(value)
    text = str(value).strip().replace(",", "").replace("$", "")
    text = re.sub(r"[^\d.]", "", text)
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _normalize_snapshot_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    trimmed = _format_output(df)
    if "scrape_date" not in trimmed.columns:
        trimmed["scrape_date"] = _get_scrape_timestamp()
    trimmed["scrape_date"] = trimmed["scrape_date"].apply(_clean_text_or_blank)
    default_ts = _get_scrape_timestamp()
    trimmed.loc[trimmed["scrape_date"] == "", "scrape_date"] = default_ts
    trimmed["url"] = trimmed["url"].apply(_clean_text_or_blank)
    trimmed = trimmed[trimmed["url"] != ""].drop_duplicates("url", keep="last")
    trimmed["price_value"] = trimmed["price"].apply(_coerce_price_value)
    return trimmed


def _load_state_rows(state_path: Path) -> dict[str, dict[str, Any]]:
    if not state_path.exists():
        return {}
    try:
        df = pd.read_csv(state_path)
    except Exception:
        return {}
    if df.empty:
        return {}
    df = df.fillna("")
    state_rows: dict[str, dict[str, Any]] = {}
    for row in df.to_dict("records"):
        url = str(row.get("url", "")).strip()
        if not url:
            continue
        state_rows[url] = row
    return state_rows


def _update_state_details(state_row: dict[str, Any], row: dict[str, Any]) -> None:
    for field in DETAIL_COLUMNS:
        value = row.get(field)
        if _is_blank(value):
            continue
        state_row[field] = value


def _build_history_event(
    event_date: str,
    event: str,
    url: str,
    price: Optional[int],
    previous_price: Optional[int],
    details: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_date": event_date,
        "event": event,
        "url": url,
        "price": price if price is not None else "",
        "previous_price": previous_price if previous_price is not None else "",
        "price_change": "",
    }
    if price is not None and previous_price is not None and price != previous_price:
        payload["price_change"] = price - previous_price
    for field in DETAIL_COLUMNS:
        payload[field] = details.get(field, "")
    return payload


def _write_history_events(events: list[dict[str, Any]], history_path: Path) -> None:
    if not events:
        return
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_df = pd.DataFrame(events)
    history_df = history_df.reindex(columns=HISTORY_COLUMNS, fill_value="")
    if history_path.exists():
        history_df.to_csv(history_path, mode="a", header=False, index=False)
    else:
        history_df.to_csv(history_path, index=False)


def _write_state_rows(state_rows: dict[str, dict[str, Any]], state_path: Path) -> None:
    ordered_rows: list[dict[str, Any]] = []
    for url, row in state_rows.items():
        row["url"] = url
        ordered_rows.append({col: row.get(col, "") for col in STATE_COLUMNS})
    state_df = pd.DataFrame(ordered_rows)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_df.to_csv(state_path, index=False)


def _write_recent_market_tagged_rows(state_rows: dict[str, dict[str, Any]], output_path: Path) -> int:
    recent_rows: list[dict[str, Any]] = []
    cutoff_ts = datetime.now(UTC) - timedelta(days=RECENT_MARKET_WINDOW_DAYS)
    for url, row in state_rows.items():
        event_candidates: list[datetime] = []
        for field in ["sold_date", "last_seen", "last_price_date", "first_seen"]:
            raw_value = row.get(field)
            if _is_blank(raw_value):
                continue
            try:
                parsed = pd.to_datetime(raw_value, errors="coerce", utc=True)
            except Exception:
                parsed = pd.NaT
            if pd.isna(parsed):
                continue
            event_candidates.append(parsed.to_pydatetime())
        if not event_candidates:
            continue
        latest_event = max(event_candidates)
        if latest_event < cutoff_ts:
            continue
        recent_rows.append(
            {
                "year": row.get("year", ""),
                "make": row.get("make", ""),
                "model": row.get("model", ""),
                "variant": row.get("variant", ""),
                "body_type": row.get("body_type", ""),
                "odometer": row.get("odometer", ""),
                "transmission": row.get("transmission", ""),
                "rego": row.get("rego", ""),
                "price": row.get("last_price", ""),
                "fuel_type": row.get("fuel_type", ""),
                "location": row.get("location", ""),
                "url": url,
                "scrape_date": latest_event.isoformat(),
                "canonical_tag": "",
                "canonical_reason": "",
            }
        )
    recent_df = _format_output(pd.DataFrame(recent_rows, columns=OUTPUT_COLUMNS))
    recent_df = _apply_canonical_tagging(recent_df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    recent_df.to_csv(output_path, index=False)
    return len(recent_df)


def _update_listing_history(
    snapshot_df: pd.DataFrame,
    state_path: Path,
    history_path: Path,
    snapshot_path: Path,
    *,
    mark_sold: bool = True,
) -> dict[str, int]:
    snapshot = _normalize_snapshot_df(snapshot_df)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot.drop(columns=["price_value"], errors="ignore").to_csv(snapshot_path, index=False)
    if snapshot.empty:
        return {"listed": 0, "price_changes": 0, "sold": 0, "relisted": 0}

    run_ts = _get_scrape_timestamp()
    scrape_values = snapshot["scrape_date"].dropna().astype(str)
    scrape_values = scrape_values[scrape_values.str.strip() != ""]
    if not scrape_values.empty:
        run_ts = scrape_values.max()

    state_rows = _load_state_rows(state_path)
    events: list[dict[str, Any]] = []
    counts = {"listed": 0, "price_changes": 0, "sold": 0, "relisted": 0}

    current_urls = set(snapshot["url"].tolist())

    for row in snapshot.to_dict("records"):
        url = row.get("url", "")
        if not url:
            continue
        price_value = row.get("price_value")
        state_row = state_rows.get(url)
        if state_row is None:
            new_state = {
                "url": url,
                "status": "active",
                "first_seen": run_ts,
                "last_seen": run_ts,
                "last_price": price_value if price_value is not None else "",
                "last_price_date": run_ts if price_value is not None else "",
                "sold_date": "",
            }
            _update_state_details(new_state, row)
            state_rows[url] = new_state
            events.append(_build_history_event(run_ts, "listed", url, price_value, None, row))
            counts["listed"] += 1
            continue

        previous_price = _coerce_price_value(state_row.get("last_price"))
        if state_row.get("status") == "sold":
            counts["relisted"] += 1
            events.append(_build_history_event(run_ts, "relisted", url, price_value, previous_price, row))
            state_row["sold_date"] = ""
            state_row["first_seen"] = state_row.get("first_seen") or run_ts

        if price_value is not None and previous_price is not None and price_value != previous_price:
            events.append(_build_history_event(run_ts, "price_change", url, price_value, previous_price, row))
            counts["price_changes"] += 1
            state_row["last_price"] = price_value
            state_row["last_price_date"] = run_ts
        elif price_value is not None and previous_price is None:
            state_row["last_price"] = price_value
            state_row["last_price_date"] = run_ts

        state_row["status"] = "active"
        state_row["last_seen"] = run_ts
        _update_state_details(state_row, row)

    if mark_sold and current_urls:
        for url, state_row in state_rows.items():
            if url in current_urls:
                continue
            if state_row.get("status") == "sold":
                continue
            sold_price = _coerce_price_value(state_row.get("last_price"))
            events.append(
                _build_history_event(run_ts, "sold", url, sold_price, sold_price, state_row)
            )
            counts["sold"] += 1
            state_row["status"] = "sold"
            state_row["sold_date"] = run_ts

    _write_history_events(events, history_path)
    _write_state_rows(state_rows, state_path)
    recent_count = _write_recent_market_tagged_rows(state_rows, RECENT_MARKET_TAGGED_OUTPUT)
    counts["recent_market"] = recent_count
    return counts


def scrape_all_pages(
    url: str,
    cookie_header: str | None,
    storage_state: str | None,
    timeout: int,
    browser_name: str,
    headless: bool,
    slow_mo: int,
    wait_until: str,
    block_resources: bool,
    max_pages: int,
    sleep_seconds: float,
    output_path: Path | None = None,
    checkpoint_every: int = 0,
    priority_state: str | None = None,
    skip_existing: bool = False,
    merge_existing_output: bool = False,
    resume_path: Path | None = None,
    page_retries: int = 3,
    page_retry_delay: float = 5.0,
) -> tuple[pd.DataFrame, dict[str, object], pd.DataFrame]:
    priority_rows: List[dict[str, Any]] = []
    other_rows: List[dict[str, Any]] = []
    seen_keys: set[str] = set()
    current_rows: List[dict[str, Any]] = []
    current_urls: set[str] = set()
    page = 0
    next_url: Optional[str] = url
    last_debug: dict[str, object] = {}
    seed_url = url
    priority_state = (priority_state or "").strip()
    next_checkpoint = checkpoint_every if checkpoint_every > 0 else None
    completed = True

    if skip_existing and output_path:
        for row in _load_existing_rows(output_path):
            keys = _row_keys(row)
            if not keys or any(key in seen_keys for key in keys):
                continue
            seen_keys.update(keys)
            if priority_state and _matches_priority_state(row.get("location"), priority_state):
                priority_rows.append(row)
            else:
                other_rows.append(row)

    while next_url:
        current_url = next_url
        page += 1
        attempt = 0
        df = pd.DataFrame()
        debug: dict[str, object] = {}
        while attempt <= page_retries:
            try:
                df, debug = scrape_first_page(
                    current_url,
                    cookie_header,
                    storage_state,
                    timeout,
                    browser_name,
                    headless,
                    slow_mo,
                    wait_until,
                    block_resources,
                    None,
                    None,
                    False,
                )
                break
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                debug = {"error": str(exc), "error_type": type(exc).__name__}
                if attempt > page_retries:
                    completed = False
                    last_debug = debug
                    if resume_path:
                        resume_state = {
                            "seed_url": seed_url,
                            "current_url": current_url,
                            "next_url": current_url,
                            "page": page,
                            "pages_fetched": page,
                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                            "error": debug.get("error"),
                        }
                        _write_resume_state(resume_path, resume_state)
                    next_url = None
                    break
                if page_retry_delay > 0:
                    import time

                    time.sleep(page_retry_delay * attempt)
        last_debug = debug
        if not completed and df.empty:
            break
        if not df.empty:
            for row in df.to_dict("records"):
                url_value = _clean_text_or_blank(row.get("url"))
                if url_value and url_value not in current_urls:
                    current_urls.add(url_value)
                    current_rows.append(row)
                keys = _row_keys(row)
                if not keys or any(key in seen_keys for key in keys):
                    continue
                seen_keys.update(keys)
                if priority_state and _matches_priority_state(row.get("location"), priority_state):
                    priority_rows.append(row)
                else:
                    other_rows.append(row)
                if (
                    output_path
                    and next_checkpoint
                    and (len(priority_rows) + len(other_rows)) >= next_checkpoint
                ):
                    _write_checkpoint(
                        priority_rows + other_rows,
                        output_path,
                        merge_existing_output,
                    )
                    next_checkpoint += checkpoint_every

        next_url_value = debug.get("next_page_url")
        next_url = _normalize_url(str(next_url_value)) if next_url_value else None
        next_url = _prefer_web_next_url(next_url, seed_url, debug)
        if resume_path:
            resume_state = {
                "seed_url": seed_url,
                "current_url": current_url,
                "next_url": next_url,
                "page": page,
                "pages_fetched": page,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            _write_resume_state(resume_path, resume_state)
        if max_pages > 0 and page >= max_pages:
            break
        if sleep_seconds > 0 and next_url:
            import time

            time.sleep(sleep_seconds)

    combined = pd.DataFrame(priority_rows + other_rows)
    combined = _format_output(combined)
    snapshot_df = _format_output(pd.DataFrame(current_rows))
    if resume_path and not next_url and resume_path.exists():
        resume_path.unlink()
    summary = {
        "pages_fetched": page,
        "rows_deduped": len(priority_rows) + len(other_rows),
        "completed": completed,
    }
    for key in ("current_page", "last_page", "total"):
        if key in last_debug:
            summary[key] = last_debug[key]
    return combined, summary, snapshot_df


def scrape_first_page(
    url: str,
    cookie_header: str | None,
    storage_state: str | None,
    timeout: int,
    browser_name: str,
    headless: bool,
    slow_mo: int,
    wait_until: str,
    block_resources: bool,
    dump_html: Path | None = None,
    dump_next_data: Path | None = None,
    format_output: bool = True,
) -> tuple[pd.DataFrame, dict[str, object]]:
    html, fetch_meta = fetch_html_with_fallback(
        url,
        cookie_header,
        storage_state,
        timeout,
        browser_name,
        headless,
        slow_mo,
        wait_until,
        block_resources,
    )
    if _looks_like_json(html):
        payload = _extract_json(html)
        df, api_debug = _extract_from_api_payload(payload)
        api_debug.update(fetch_meta)
        if format_output:
            df = _format_output(df)
        return df, api_debug
    if dump_html:
        dump_html.parent.mkdir(parents=True, exist_ok=True)
        dump_html.write_text(html, encoding="utf-8")
    df, debug = _parse_first_page(html)
    debug.update(fetch_meta)
    if dump_next_data:
        soup = BeautifulSoup(html, "html.parser")
        next_data = _extract_next_data(soup)
        if not next_data:
            next_data = _extract_nuxt_data(soup)
        if next_data is not None:
            dump_next_data.parent.mkdir(parents=True, exist_ok=True)
            dump_next_data.write_text(json.dumps(next_data, ensure_ascii=False), encoding="utf-8")
    if format_output:
        df = _format_output(df)
    return df, debug


def _load_cookie_file(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    raw = raw.replace("\r", "").replace("\n", "")
    return raw.strip()


def _cookie_summary(cookie_header: str) -> dict[str, int]:
    raw = cookie_header.strip()
    if raw.lower().startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()
    parts = [part.strip() for part in raw.split(";") if "=" in part]
    return {
        "length": len(raw),
        "pair_count": len(parts),
    }


def _load_seed_urls(url: str, urls_file: Path | None) -> list[str]:
    urls: list[str] = []
    if urls_file is not None:
        raw_lines = urls_file.read_text(encoding="utf-8").splitlines()
        for line in raw_lines:
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            urls.append(candidate)
    else:
        urls.append(url)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in urls:
        normalized = _normalize_url(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _dedupe_output_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    rows = df.fillna("").to_dict("records")
    seen: set[str] = set()
    merged_rows: list[dict[str, Any]] = []
    for row in rows:
        keys = _row_keys(row)
        if not keys or any(key in seen for key in keys):
            continue
        seen.update(keys)
        merged_rows.append(row)
    return _format_output(pd.DataFrame(merged_rows))


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape the first Autotrader results page.")
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="Autotrader search URL (first page).",
    )
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=None,
        help="Optional file of seed URLs (one per line). Overrides --url when provided.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output CSV path.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Request timeout in seconds.",
    )
    parser.add_argument(
        "--cookie",
        default=os.getenv("AUTOTRADER_COOKIE", "").strip(),
        help="Raw Cookie header value (or set AUTOTRADER_COOKIE).",
    )
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=None,
        help="Path to a file containing the raw Cookie header value.",
    )
    parser.add_argument(
        "--storage-state",
        default=os.getenv("AUTOTRADER_STORAGE_STATE", "").strip(),
        help="Path to Playwright storage_state.json (or set AUTOTRADER_STORAGE_STATE).",
    )
    parser.add_argument(
        "--playwright-browser",
        choices=["chromium", "chrome", "msedge", "firefox", "webkit"],
        default="chromium",
        help="Browser engine/channel to use for Playwright fallback.",
    )
    parser.add_argument(
        "--playwright-headful",
        action="store_true",
        help="Launch Playwright with a visible browser window.",
    )
    parser.add_argument(
        "--playwright-slowmo",
        type=int,
        default=0,
        help="Slow down Playwright actions (ms).",
    )
    parser.add_argument(
        "--playwright-timeout",
        type=int,
        default=45,
        help="Playwright navigation timeout in seconds.",
    )
    parser.add_argument(
        "--playwright-wait",
        choices=["domcontentloaded", "load", "networkidle"],
        default="domcontentloaded",
        help="Playwright wait_until mode.",
    )
    parser.add_argument(
        "--playwright-block-resources",
        action="store_true",
        help="Block images/media/fonts to speed up page load.",
    )
    parser.add_argument(
        "--dump-html",
        type=Path,
        default=None,
        help="Optional path to save the fetched HTML for debugging.",
    )
    parser.add_argument(
        "--dump-next-data",
        type=Path,
        default=None,
        help="Optional path to save the __NEXT_DATA__ JSON payload.",
    )
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="Follow next_page_url and scrape all pages.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Maximum pages to scrape when --all-pages is set (0 = no limit).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Delay between page fetches when --all-pages is set.",
    )
    parser.add_argument(
        "--page-retries",
        type=int,
        default=3,
        help="Retry count per page when a fetch fails.",
    )
    parser.add_argument(
        "--page-retry-delay",
        type=float,
        default=5.0,
        help="Delay (seconds) between per-page retries.",
    )
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=100,
        help="Write output every N listings when --all-pages is set (0 = disable).",
    )
    parser.add_argument(
        "--priority-state",
        default="",
        help="Prioritize listings from a state (e.g. VIC) when writing output.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Seed from the existing output file and skip duplicate listings.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an --all-pages run from the last resume file.",
    )
    parser.add_argument(
        "--resume-file",
        type=Path,
        default=None,
        help="Path to the resume file (default: output + .resume.json).",
    )
    args = parser.parse_args()

    cookie_header = args.cookie or None
    if args.cookie_file:
        try:
            cookie_header = _load_cookie_file(args.cookie_file)
        except OSError as exc:
            raise RuntimeError(f"Failed to read cookie file: {args.cookie_file}") from exc
        if not cookie_header:
            raise RuntimeError(f"Cookie file is empty: {args.cookie_file}")
    if cookie_header:
        summary = _cookie_summary(cookie_header)
        print(f"Cookie summary: length={summary['length']} pairs={summary['pair_count']}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output
    if args.urls_file and not args.urls_file.exists():
        raise RuntimeError(f"URLs file not found: {args.urls_file}")
    seed_urls = _load_seed_urls(args.url, args.urls_file)
    if not seed_urls:
        raise RuntimeError("No valid seed URLs found. Check --url/--urls-file.")
    if args.resume and len(seed_urls) > 1:
        raise RuntimeError("--resume is only supported when scraping a single seed URL.")

    combined_frames: list[pd.DataFrame] = []
    combined_snapshots: list[pd.DataFrame] = []
    debug_rows: list[dict[str, object]] = []

    for idx, seed_url in enumerate(seed_urls, start=1):
        print(f"[Seed {idx}/{len(seed_urls)}] {seed_url}")
        if args.all_pages:
            resume_path = None
            if len(seed_urls) == 1:
                resume_path = args.resume_file or args.output.with_suffix(
                    args.output.suffix + ".resume.json"
                )
                if args.resume:
                    resume_state = _load_resume_state(resume_path)
                    if resume_state:
                        resume_url = resume_state.get("next_url") or resume_state.get("current_url")
                        if resume_url:
                            seed_url = str(resume_url)
                            print(f"Resuming from {seed_url} using {resume_path}")
            checkpoint_path = output_path if len(seed_urls) == 1 else None
            df_part, debug, snapshot_part = scrape_all_pages(
                seed_url,
                cookie_header,
                args.storage_state or None,
                args.playwright_timeout,
                args.playwright_browser,
                not args.playwright_headful,
                args.playwright_slowmo,
                args.playwright_wait,
                args.playwright_block_resources,
                args.max_pages,
                args.sleep_seconds,
                checkpoint_path,
                args.checkpoint_every,
                args.priority_state,
                args.skip_existing,
                not args.overwrite,
                resume_path,
                args.page_retries,
                args.page_retry_delay,
            )
        else:
            df_part, debug = scrape_first_page(
                seed_url,
                cookie_header,
                args.storage_state or None,
                args.playwright_timeout,
                args.playwright_browser,
                not args.playwright_headful,
                args.playwright_slowmo,
                args.playwright_wait,
                args.playwright_block_resources,
                args.dump_html,
                args.dump_next_data,
            )
            snapshot_part = df_part

        debug_rows.append(
            {
                "seed_url": seed_url,
                "rows": len(df_part),
                "pages_fetched": debug.get("pages_fetched"),
                "rows_deduped": debug.get("rows_deduped"),
                "completed": debug.get("completed"),
                "fetch_mode": debug.get("fetch_mode"),
                "status_code": debug.get("status_code"),
                "final_url": debug.get("final_url"),
                "next_data_rows": debug.get("next_data_rows", 0),
                "nuxt_data_rows": debug.get("nuxt_data_rows", 0),
                "json_ld_rows": debug.get("json_ld_rows", 0),
                "error": debug.get("error", ""),
            }
        )
        if not df_part.empty:
            combined_frames.append(df_part)
        if snapshot_part is not None and not snapshot_part.empty:
            combined_snapshots.append(snapshot_part)

    if not combined_frames:
        print("No listings extracted from any seed URL.")
        debug_df = pd.DataFrame(debug_rows)
        if not debug_df.empty:
            print(debug_df.to_string(index=False))
        print("Check URL coverage and supply AUTOTRADER_COOKIE/AUTOTRADER_STORAGE_STATE.")
        return

    df = _dedupe_output_df(pd.concat(combined_frames, ignore_index=True))
    snapshot_df = _dedupe_output_df(pd.concat(combined_snapshots, ignore_index=True))
    df = _apply_canonical_tagging(df)
    snapshot_df = _apply_canonical_tagging(snapshot_df)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.overwrite:
        df.to_csv(output_path, index=False)
        print(f"Saved {len(df)} rows to {output_path}")
    else:
        merged_df, added, existing_count = _merge_existing_output(df, output_path)
        merged_df.to_csv(output_path, index=False)
        if existing_count:
            print(
                f"Added {added} new rows (existing {existing_count}, total {len(merged_df)}) "
                f"to {output_path}"
            )
        else:
            print(f"Saved {len(merged_df)} rows to {output_path}")
    debug_df = pd.DataFrame(debug_rows)
    if not debug_df.empty:
        print("Seed summary:")
        print(debug_df.to_string(index=False))

    all_completed = True if debug_df.empty else bool(debug_df["completed"].fillna(True).all())
    mark_sold = args.all_pages and args.max_pages == 0 and len(seed_urls) == 1 and all_completed
    history_counts = _update_listing_history(
        snapshot_df,
        STATE_OUTPUT,
        HISTORY_OUTPUT,
        SNAPSHOT_OUTPUT,
        mark_sold=mark_sold,
    )
    if any(history_counts.values()):
        print(
            "Listing history updated: "
            f"listed={history_counts['listed']} "
            f"relisted={history_counts['relisted']} "
            f"price_changes={history_counts['price_changes']} "
            f"sold={history_counts['sold']}"
        )


if __name__ == "__main__":
    main()
