from __future__ import annotations

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
    from shared.data_loader import DATA_DIR
else:
    from shared.data_loader import DATA_DIR

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
INPUT_FILE = DATA_DIR / "all_vehicle_links.csv"
OUTPUT_FILE = DATA_DIR / "vehicle_static_details.csv"
SKIPPED_LOG = ROOT_DIR / "logs" / "skipped_links.txt"

SCHEMA_FIELDS = [
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "no_of_seats",
    "build_date",
    "compliance_date",
    "vin",
    "rego_no",
    "rego_state",
    "rego_expiry",
    "no_of_plates",
    "no_of_cylinders",
    "engine_capacity",
    "fuel_type",
    "transmission",
    "odometer_reading",
    "odometer_unit",
    "exterior_colour",
    "interior_colour",
    "key",
    "spare_key",
    "owners_manual",
    "service_history",
    "engine_turns_over",
    "location",
    "url",
    "general_condition",
    "features_list",
    "bids",
    "price",
    "time_remaining_or_date_sold",
    "status",
]

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
PROXY_PREFIX = "https://r.jina.ai/https://"

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


def clean_joined_fields(text: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1, \2", text)


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


def extract_title_parts(soup: BeautifulSoup) -> tuple[str, str, str, str]:
    title_elem = soup.find("h1", class_="dls-heading-3")
    title = safe_get_text(title_elem)
    if not title:
        return ("", "", "", "")

    parts = title.split()
    year = parts[0] if parts and YEAR_RE.match(parts[0]) else ""
    make = parts[1] if len(parts) > 1 else ""
    model = parts[2] if len(parts) > 2 else ""
    variant = " ".join(parts[3:]) if len(parts) > 3 else ""
    return year, make, model, variant


def read_general_condition(soup: BeautifulSoup) -> str:
    section = soup.find(attrs={"id": re.compile("ConditionAssessment", re.IGNORECASE)})
    if section:
        bullet_items = filter_condition_entries(safe_get_text(li) for li in section.find_all("li"))
        if bullet_items:
            return "\n".join(bullet_items)

        paragraphs = filter_condition_entries(safe_get_text(p) for p in section.find_all("p"))
        if paragraphs:
            return "\n".join(paragraphs)

    condition = extract_bullets(soup, "condition")
    if condition:
        filtered_condition = filter_condition_entries(condition.splitlines())
        if filtered_condition:
            return "\n".join(filtered_condition)
    return ""


def read_features_list(soup: BeautifulSoup) -> str:
    features = extract_bullets(soup, "^features")
    if features:
        return features.replace("\n", ", ")
    return ""


def assemble_details(soup: BeautifulSoup, url: str) -> dict[str, Any]:
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

    details["general_condition"] = read_general_condition(soup)
    details["features_list"] = read_features_list(soup)
    details["location"] = normalize_state(details.get("location", "") or extract_location(soup))
    details["bids"] = details.get("bids", "")
    details["price"] = details.get("price", "")
    details["time_remaining_or_date_sold"] = details.get("time_remaining_or_date_sold", "")
    status_value = str(details.get("status", "")).strip().lower()
    details["status"] = status_value or "active"

    return details


def fetch_html(session: requests.Session, url: str) -> str:
    last_error: str | None = None
    for attempt in range(1, MAX_FETCH_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 403 and not url.startswith(PROXY_PREFIX):
                proxy_url = f"{PROXY_PREFIX}{url.replace('https://', '')}"
                response = session.get(proxy_url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200 and len(response.text) > 2000:
                return response.text
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
        details = assemble_details(soup, url)
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


def main() -> None:
    if not INPUT_FILE.exists():
        print(f"Missing input file: {INPUT_FILE}")
        return

    links_df = pd.read_csv(INPUT_FILE)
    all_links = links_df.get("url", pd.Series(dtype=str)).dropna().drop_duplicates().tolist()
    if not all_links:
        print("No URLs found in the links CSV.")
        return

    existing_df = pd.read_csv(OUTPUT_FILE) if OUTPUT_FILE.exists() else pd.DataFrame(columns=SCHEMA_FIELDS)
    processed_urls = set(existing_df.get("url", pd.Series(dtype=str)).dropna().tolist())
    pending_links = [url for url in all_links if url not in processed_urls]

    target_links = pending_links or all_links
    print(f"Processing {len(target_links)} listings (pending: {len(pending_links)}).")

    data, skipped = process_links(target_links)
    new_df = pd.DataFrame(data)
    if new_df.empty:
        print("No listings were scraped.")
        return

    combined = pd.concat([existing_df, new_df], ignore_index=True, sort=False)
    combined.drop_duplicates(subset=["url"], keep="last", inplace=True)
    combined = combined.reindex(columns=SCHEMA_FIELDS)

    atomic_write(combined, OUTPUT_FILE)
    print(f"Saved {len(new_df)} rows (total {len(combined)}). Output: {OUTPUT_FILE}")

    write_skipped(skipped)
    if skipped:
        print(f"{len(skipped)} URLs skipped. See {SKIPPED_LOG}")


if __name__ == "__main__":
    main()
