from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.active_snapshot_retention import compact_active_snapshots
    from scripts.atomic_csv import append_dict_rows_csv_atomic, write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
    from shared.state_machine import ListingObservation, ensure_state_schema, upsert_state_row
else:  # pragma: no cover
    from scripts.active_snapshot_retention import compact_active_snapshots
    from scripts.atomic_csv import append_dict_rows_csv_atomic, write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
    from shared.state_machine import ListingObservation, ensure_state_schema, upsert_state_row

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CSV_FILE = str(dataset_path("active_vehicle_details.csv"))
STATIC_SEED_FILE = dataset_path("vehicle_static_details.csv")
ACTIVE_LINKS_FILE = dataset_path("active_vehicle_links.csv")
STATE_FILE = dataset_path("vehicle_state.csv")
SNAPSHOT_FILE = dataset_path("active_snapshots.csv")
SNAPSHOT_COLUMNS = [
    "snapshot_ts",
    "url",
    "price_text",
    "price_numeric",
    "bids_numeric",
    "time_remaining_text",
    "time_remaining_hours",
    "status",
    "location",
    "location_state",
    "auction_site",
]
SKIPPED_LOG = "logs/skipped_links.txt"
PROGRESS_FILE = "logs/update_progress.txt"
RESUME_FILE = "logs/update_resume.json"
HOME_URL = "https://www.grays.com/"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

BATCH_SAVE_INTERVAL = max(1, int(os.getenv("ACTIVE_LISTING_BATCH_SIZE", "50")))
STATE_DEAD_URL_THRESHOLD = max(1, int(os.getenv("AUTOSNIPER_DEAD_URL_THRESHOLD", "3")))

TIME_PATTERN = re.compile(
    r"(\d+)\s*(d|day|days|h|hour|hours|m|min|minute|minutes|s|sec|second|seconds)",
    re.IGNORECASE,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def parse_currency_value(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value)
    digits = re.sub(r"[^0-9.]", "", text)
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def parse_time_remaining_to_hours(value: str | None) -> float | None:
    if not value:
        return None
    lowered = value.strip().lower()
    if not lowered or lowered in {"n/a", "na", "closed"}:
        return None
    total_hours = 0.0
    for amount, unit in TIME_PATTERN.findall(lowered):
        try:
            qty = float(amount)
        except ValueError:
            continue
        unit_lower = unit.lower()
        if unit_lower.startswith("d"):
            total_hours += qty * 24
        elif unit_lower.startswith("h"):
            total_hours += qty
        elif unit_lower.startswith("m"):
            total_hours += qty / 60.0
        elif unit_lower.startswith("s"):
            total_hours += qty / 3600.0
    return round(total_hours, 3) if total_hours > 0 else None


def derive_location_state(location: str | None) -> str:
    if not location:
        return ""
    tokens = [token.strip().upper() for token in re.split(r"[,/]", str(location)) if token.strip()]
    for token in reversed(tokens):
        if len(token) == 3 and token.isalpha():
            return token
    return tokens[-1] if tokens else ""


def derive_auction_site(url: str | None) -> str:
    if not url:
        return ""
    try:
        parts = url.split("/")
        return parts[3] if len(parts) > 3 else ""
    except Exception:
        return ""


def append_snapshot_row(record: dict[str, object]) -> None:
    append_dict_rows_csv_atomic(SNAPSHOT_FILE, SNAPSHOT_COLUMNS, [record])


def record_snapshot(
    df: pd.DataFrame,
    url: str,
    price_text: str | None,
    bids_text: str | None,
    time_remaining_text: str | None,
) -> None:
    try:
        row = df.loc[df["url"] == url].iloc[0].to_dict()
    except Exception:
        row = {}
    price_numeric = parse_currency_value(price_text)
    try:
        bids_numeric = int(bids_text)
    except Exception:
        bids_numeric = None
    time_hours = parse_time_remaining_to_hours(time_remaining_text)
    record = {
        "snapshot_ts": _utc_now_iso(),
        "url": url,
        "price_text": price_text or "",
        "price_numeric": price_numeric,
        "bids_numeric": bids_numeric,
        "time_remaining_text": time_remaining_text or "",
        "time_remaining_hours": time_hours,
        "status": row.get("status", ""),
        "location": row.get("location", ""),
        "location_state": derive_location_state(row.get("location", "")),
        "auction_site": derive_auction_site(url),
    }
    append_snapshot_row(record)


def load_resume_queue(all_urls: list[str]) -> list[str]:
    """Return the queue stored on disk (if any), filtered against current URLs."""
    resume_path = Path(RESUME_FILE)
    if not resume_path.exists():
        return all_urls
    try:
        data = json.loads(resume_path.read_text(encoding="utf-8"))
        queued = data.get("remaining_urls", [])
    except Exception:
        return all_urls
    if not queued:
        return all_urls
    allowed = set(all_urls)
    filtered = [url for url in queued if url in allowed]
    if filtered:
        print(f"Resuming from previous session ({len(filtered)} URLs remaining).")
        return filtered
    return all_urls


def save_resume_queue(remaining_urls: list[str]) -> None:
    """Persist the remaining queue so we can resume after interruptions."""
    resume_path = Path(RESUME_FILE)
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    resume_path.write_text(
        json.dumps(
            {
                "remaining_urls": remaining_urls,
                "updated_at": _utc_now_iso(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def clear_resume_queue() -> None:
    resume_path = Path(RESUME_FILE)
    if resume_path.exists():
        resume_path.unlink()


def persist_dataframe(df: pd.DataFrame, note: str) -> None:
    """Write the current dataframe state to disk atomically for resume safety."""
    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
    snapshot = df.copy()
    if "drivetrain_source" in snapshot.columns:
        snapshot = snapshot.drop(columns=["drivetrain_source"])
    snapshot["url"] = snapshot["url"].apply(clean_url)
    write_dataframe_csv_atomic(snapshot, CSV_FILE, index=False)
    print(f"{note}: wrote {len(snapshot)} rows to {CSV_FILE}")


def _load_state_dataframe() -> pd.DataFrame:
    if not STATE_FILE.exists():
        return ensure_state_schema(pd.DataFrame())
    try:
        df = pd.read_csv(STATE_FILE, low_memory=False)
    except Exception:
        df = pd.DataFrame()
    return ensure_state_schema(df)


def persist_state_dataframe(df: pd.DataFrame, note: str) -> None:
    snapshot = ensure_state_schema(df)
    snapshot["url"] = snapshot["url"].astype(str).str.strip()
    write_dataframe_csv_atomic(snapshot, STATE_FILE, index=False)
    print(f"{note}: wrote {len(snapshot)} rows to {STATE_FILE}")


def _state_observation_from_row(
    row: pd.Series,
    *,
    run_id: str,
    observed_at: str,
    evidence: str,
    fetch_failed: bool = False,
    fetch_error: str = "",
) -> ListingObservation:
    status = str(row.get("status", "") or "").strip().lower()
    price_raw = str(row.get("price", "") or "").strip()
    bids_raw = str(row.get("bids", "") or "").strip()
    time_raw = str(row.get("time_remaining_or_date_sold", "") or "").strip()
    is_active = status == "active"
    is_referred = status in {"referred", "canceled", "cancelled", "closed"}
    has_sale_price = status == "sold"
    is_withdrawn = status in {"withdrawn", "no_price"}
    return ListingObservation(
        url=str(row.get("url", "") or ""),
        observed_at=observed_at,
        run_id=run_id,
        is_live=is_active,
        has_sale_price=has_sale_price,
        is_referred=is_referred,
        is_withdrawn=is_withdrawn,
        fetch_failed=fetch_failed,
        current_price="" if price_raw.lower() in {"", "n/a", "nan"} else price_raw,
        bid_count="" if bids_raw.lower() in {"", "n/a", "nan"} else bids_raw,
        time_remaining="" if time_raw.lower() in {"", "n/a", "nan"} else time_raw,
        evidence=evidence,
        fetch_error=fetch_error,
    )


def _load_active_queue_urls() -> set[str]:
    if not ACTIVE_LINKS_FILE.exists():
        return set()
    try:
        links_df = pd.read_csv(ACTIVE_LINKS_FILE)
    except Exception:
        return set()
    if "url" not in links_df.columns:
        return set()
    queue_urls: set[str] = set()
    for url in links_df["url"].dropna().astype(str).tolist():
        cleaned = clean_url(url).strip().lower()
        if cleaned:
            queue_urls.add(cleaned)
    return queue_urls


def _load_active_seed_dataframe() -> pd.DataFrame:
    active_df = pd.DataFrame()
    if os.path.exists(CSV_FILE):
        active_df = pd.read_csv(CSV_FILE)

    queue_urls = _load_active_queue_urls()
    pruned_existing = 0
    if not active_df.empty and "url" in active_df.columns:
        active_df = active_df.copy()
        active_df["url"] = active_df["url"].apply(clean_url)
        if queue_urls:
            before_count = len(active_df)
            active_df = active_df[
                active_df["url"].fillna("").astype(str).str.strip().str.lower().isin(queue_urls)
            ].copy()
            pruned_existing = before_count - len(active_df)

    if not STATIC_SEED_FILE.exists():
        if pruned_existing > 0:
            persist_dataframe(
                active_df,
                f"Pruned {pruned_existing} stale active listing(s) not present in active link queue",
            )
        return active_df

    static_df = pd.read_csv(STATIC_SEED_FILE)
    if static_df.empty:
        if pruned_existing > 0:
            persist_dataframe(
                active_df,
                f"Pruned {pruned_existing} stale active listing(s) not present in active link queue",
            )
        return active_df

    seed_df = static_df.copy()
    if "drivetrain_source" in seed_df.columns:
        seed_df = seed_df.drop(columns=["drivetrain_source"])
    if "url" in seed_df.columns:
        seed_df["url"] = seed_df["url"].apply(clean_url)
        if queue_urls:
            seed_df = seed_df[
                seed_df["url"].fillna("").astype(str).str.strip().str.lower().isin(queue_urls)
            ].copy()
    for column, default in (
        ("status", "Active"),
        ("time_remaining_or_date_sold", ""),
        ("price", ""),
        ("bids", 0),
    ):
        if column not in seed_df.columns:
            seed_df[column] = default
        else:
            seed_df[column] = seed_df[column].fillna(default)

    if active_df.empty:
        note = "Seeded active listings from static details"
        if pruned_existing > 0:
            note = (
                f"Pruned {pruned_existing} stale active listing(s) not present in active link queue "
                "and reseeded active listings from static details"
            )
        persist_dataframe(seed_df, note)
        return seed_df

    if "url" not in active_df.columns or "url" not in seed_df.columns:
        if pruned_existing > 0:
            persist_dataframe(
                active_df,
                f"Pruned {pruned_existing} stale active listing(s) not present in active link queue",
            )
        return active_df

    active_urls = set(active_df["url"].dropna().astype(str).str.strip().str.lower())
    missing_seed = seed_df[
        ~seed_df["url"].fillna("").astype(str).str.strip().str.lower().isin(active_urls)
    ].copy()
    if missing_seed.empty:
        if pruned_existing > 0:
            persist_dataframe(
                active_df,
                f"Pruned {pruned_existing} stale active listing(s) not present in active link queue",
            )
        return active_df

    combined = pd.concat([active_df, missing_seed], ignore_index=True, sort=False)
    combined["url"] = combined["url"].apply(clean_url)
    combined = combined.drop_duplicates(subset=["url"], keep="first")
    note_parts: list[str] = []
    if pruned_existing > 0:
        note_parts.append(
            f"Pruned {pruned_existing} stale active listing(s) not present in active link queue"
        )
    note_parts.append(f"Seeded {len(missing_seed)} missing active listing(s) from static details")
    persist_dataframe(combined, " and ".join(note_parts))
    return combined

# ─── Clean URL from HTML anchor tag ─────────────────────────────
def clean_url(url):
    if not isinstance(url, str):
        return ""
    match = re.search(r'href="([^"]+)"', url)
    return match.group(1) if match else url


def select_snapshot_retention_urls(
    df: pd.DataFrame,
    scope_urls: list[str] | None = None,
) -> list[str]:
    """Return active URLs whose latest snapshots should stay in the live file."""
    if df.empty or "url" not in df.columns:
        return []

    working = df.copy()
    if "status" in working.columns:
        active_mask = (
            working["status"].fillna("").astype(str).str.strip().str.lower().eq("active")
        )
        working = working[active_mask].copy()

    if scope_urls is not None:
        scope_keys = {
            clean_url(str(url)).strip().lower()
            for url in scope_urls
            if str(url or "").strip()
        }
        working = working[
            working["url"]
            .fillna("")
            .astype(str)
            .map(clean_url)
            .str.strip()
            .str.lower()
            .isin(scope_keys)
        ].copy()

    return working["url"].dropna().astype(str).map(clean_url).tolist()


def parse_price_text(text: str) -> str:
    """Return digits from a price-like string or empty string when not found."""
    if not text:
        return ""
    numbers = re.findall(r"\d[\d,\.]*", text)
    for candidate in numbers:
        cleaned = candidate.replace(",", "")
        if re.match(r"^\d+(\.\d+)?$", cleaned):
            return cleaned
    return ""

# ─── Extract auction info ──────────────────────────────────────
def extract_bid_info(soup):
    try:
        # Price extraction using itemprop="price"
        price = "N/A"
        price_elem = soup.find("span", attrs={"itemprop": "price"})
        if price_elem:
            parsed_price = parse_price_text(price_elem.get_text(strip=True))
            if parsed_price:
                price = parsed_price
        if price == "N/A":
            alt_price = soup.find("div", class_=re.compile("current-bid", re.IGNORECASE))
            if alt_price:
                parsed_price = parse_price_text(alt_price.get_text(strip=True))
                if parsed_price:
                    price = parsed_price
        print(f"  Price element: {price_elem}")
        print(f"  Extracted price: {price}")

        # Time remaining for active listings
        time_elem = soup.find("span", id="lot-closing-countdown")
        time_remaining = time_elem.get_text(strip=True) if time_elem and re.search(r"\d+\s*(d|day|days|h|hour|hours|m|min|minutes|s|sec|seconds)", time_elem.get_text(strip=True).lower(), re.IGNORECASE) else None
        print(f"  Time element: {time_elem}")
        print(f"  Extracted time remaining: {time_remaining if time_remaining else 'None'}")

        # Date sold for sold listings
        date_sold_elem = soup.find("abbr", class_="endtime")
        date_sold = date_sold_elem.get_text(strip=True) if date_sold_elem else None
        print(f"  Date sold element: {date_sold_elem}")
        print(f"  Extracted date sold: {date_sold if date_sold else 'None'}")

        # Bid extraction using regex for number of bids
        bid_elem = soup.find("a", string=re.compile(r"\d+\s+bids", re.IGNORECASE))
        bids_text = bid_elem.get_text(strip=True) if bid_elem else "0 bids"
        bids_match = re.search(r'\d+', bids_text)
        bids = bids_match.group() if bids_match else "0"
        print(f"  Bid element: {bid_elem}")
        print(f"  Extracted bids: {bids}")

        # Check for Referred or Canceled status
        referred_elem = soup.find("div", class_="dls-heading-3")
        is_referred = referred_elem and "Referred" in referred_elem.get_text(strip=True) if referred_elem else False
        canceled_elem = soup.find("p", class_="large-stamp large-stamp-sale-closed")
        is_canceled = canceled_elem and "Sale closed" in canceled_elem.get_text(strip=True) if canceled_elem else False
        is_referred = is_referred or is_canceled  # Treat canceled as Referred
        print(f"  Referred/Canceled element: {referred_elem or canceled_elem}")
        print(f"  Is Referred or Canceled: {is_referred}")

        # Check for Active status based on time remaining
        is_active = bool(time_remaining and re.search(r"\d+\s*(d|day|days|h|hour|hours|m|min|minutes|s|sec|seconds)", time_remaining.lower(), re.IGNORECASE))
        print(f"  Is Active: {is_active}")

        return price, bids, time_remaining, date_sold, is_referred, is_active
    except Exception as e:
        print(f"Warning: error extracting auction info: {e}")
        return "N/A", "0", None, None, False, False

# ─── Fetch one listing ─────────────────────────────────────────
async def safe_goto(page, url, timeout=60000, retries=2):
    for attempt in range(retries + 1):
        try:
            await page.set_extra_http_headers({"User-Agent": random.choice(USER_AGENTS)})
            await page.goto(url, wait_until="load", timeout=timeout)
            await page.wait_for_timeout(5000)
            return True
        except Exception as e:
            print(f"Warning: attempt {attempt + 1} failed for {url}: {e}")
            if attempt == retries:
                print(f"Warning: all retries failed for {url}")
                return False
            await page.wait_for_timeout(3000)

# ─── Process one listing ───────────────────────────────────────
async def fetch_listing_data(url, page, browser, playwright):
    try:
        if await safe_goto(page, url):
            actual_url = page.url.rstrip("/")
            expected_url = url.rstrip("/")
            if actual_url != expected_url:
                print(f"  Redirected from {url} to {page.url}.")
                lowered = actual_url.lower()
                if "/sale/" in lowered and "cancelled" in lowered:
                    print("  Cancellation page detected; treating listing as referred.")
                    content = await page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    price, bids, time_remaining, date_sold, is_referred, is_active = extract_bid_info(soup)
                    return price, bids, time_remaining, date_sold, True, False, browser, page
                print("  Skipping due to unexpected redirect.")
                return "N/A", "0", None, None, False, False, browser, page
            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            price, bids, time_remaining, date_sold, is_referred, is_active = extract_bid_info(soup)
            return price, bids, time_remaining, date_sold, is_referred, is_active, browser, page
        else:
            print(f"  Failed to load {url}; marking as skipped.")
            return "N/A", "0", None, None, False, False, browser, page
    except Exception as e:
        print(f"Critical fetch error for {url}: {e}. Restarting browser.")
        try:
            await page.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        return "N/A", "0", None, None, False, False, browser, page

# ─── Main update loop ──────────────────────────────────────────
async def update_bids(
    input_links: list[str] | None = None,
    limit: int | None = None,
    batch_interval: int | None = None,
    *,
    skip_master: bool = False,
):
    skipped_urls = []
    try:
        run_id = _utc_now().strftime("bids_%Y%m%dT%H%M%SZ")
        df = _load_active_seed_dataframe()
        if df.empty:
            print("No active seed dataset found. Expected active or static listings CSV.")
            return [], skipped_urls
        state_df = _load_state_dataframe()

        df["url"] = df["url"].apply(clean_url)
        if df.empty:
            print("No listings available to update.")
            return df, skipped_urls

        # Use input_links if provided, else use URLs from CSV
        if input_links:
            urls = [clean_url(url) for url in input_links if url and url.startswith("http")]
            if limit is not None and limit > 0:
                urls = urls[:limit]
                print(f"Limiting run to {len(urls)} provided listing(s) based on batch size {limit}.")
        else:
            urls = [
                url
                for url in df["url"].dropna().drop_duplicates().tolist()
                if isinstance(url, str) and url.startswith("http")
            ]

        # Ensure columns have correct dtypes
        if "price" in df.columns:
            df["price"] = df["price"].astype(str)
        if "time_remaining_or_date_sold" in df.columns:
            df["time_remaining_or_date_sold"] = df["time_remaining_or_date_sold"].astype(str)
        if "status" not in df.columns:
            df["status"] = "Unknown"
        if "bids" not in df.columns:
            df["bids"] = 0

        # Load progress if exists
        os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
        processed = set()
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, 'r') as f:
                processed = set(line.strip() for line in f if line.strip())
            print(f"Resuming: Skipping {len(processed)} processed URLs.")
            urls = [u for u in urls if u not in processed]

        use_resume_queue = limit is None or limit <= 0
        if limit is not None and limit > 0 and not input_links:
            urls = urls[:limit]
            print(f"Limiting run to {len(urls)} listings based on batch size {limit}.")

        if use_resume_queue:
            urls = load_resume_queue(urls)
            if not urls:
                print("No URLs left to process.")
                if os.path.exists(PROGRESS_FILE):
                    os.remove(PROGRESS_FILE)
                clear_resume_queue()
                return df, skipped_urls

        save_interval = max(1, batch_interval or BATCH_SAVE_INTERVAL)
        remaining_urls = list(urls)
        if use_resume_queue:
            save_resume_queue(remaining_urls)
        processed_since_last_save = 0

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()

            for idx, url in enumerate(urls):
                if not url or not url.startswith("http"):
                    print(f"  Skipped: Invalid URL {url}")
                    skipped_urls.append(url)
                    state_df, _ = upsert_state_row(
                        state_df,
                        ListingObservation(
                            url=str(url or ""),
                            observed_at=_utc_now_iso(),
                            run_id=run_id,
                            fetch_failed=True,
                            evidence="invalid_url",
                            fetch_error="invalid_url",
                        ),
                        fetch_fail_dead_threshold=STATE_DEAD_URL_THRESHOLD,
                    )
                    if remaining_urls:
                        remaining_urls.pop(0)
                        if use_resume_queue:
                            save_resume_queue(remaining_urls)
                    continue

                print(f"Updating [{idx+1}/{len(urls)}]: {url}")
                price = bids = time_remaining = date_sold = None
                is_referred = is_active = False
                try:
                    price, bids, time_remaining, date_sold, is_referred, is_active, browser, page = await fetch_listing_data(
                        url, page, browser, playwright
                    )

                    # Skip updates only if all fields are default and no status indicators
                    if price == "N/A" and bids == "0" and time_remaining is None and date_sold is None and not is_active and not is_referred:
                        print(f"  Skipped: Fetch failed, retaining status {df.loc[df['url'] == url, 'status'].iloc[0] if not df.loc[df['url'] == url].empty else 'N/A'}")
                        skipped_urls.append(url)
                        row_frame = df.loc[df["url"] == url]
                        if not row_frame.empty:
                            obs = _state_observation_from_row(
                                row_frame.iloc[0],
                                run_id=run_id,
                                observed_at=_utc_now_iso(),
                                evidence="fetch_failed_no_signals",
                                fetch_failed=True,
                                fetch_error="no_status_signals",
                            )
                        else:
                            obs = ListingObservation(
                                url=url,
                                observed_at=_utc_now_iso(),
                                run_id=run_id,
                                fetch_failed=True,
                                evidence="fetch_failed_no_signals",
                                fetch_error="no_status_signals",
                            )
                        state_df, _ = upsert_state_row(
                            state_df,
                            obs,
                            fetch_fail_dead_threshold=STATE_DEAD_URL_THRESHOLD,
                        )
                        continue

                    # Update fields
                    df.loc[df["url"] == url, "price"] = price
                    try:
                        df.loc[df["url"] == url, "bids"] = int(bids)
                    except:
                        df.loc[df["url"] == url, "bids"] = 0

                    print(f"  Time remaining: {time_remaining if time_remaining else 'None'}")
                    print(f"  Date sold: {date_sold if date_sold else 'None'}")
                    print(f"  Price: {price}")
                    print(f"  Bids: {bids}")
                    print(f"  Is Referred: {is_referred}")
                    print(f"  Is Active: {is_active}")

                    # Improved status logic based on new selectors
                    if is_active:
                        print("  Condition: Active countdown found - Set to Active")
                        df.loc[df["url"] == url, "time_remaining_or_date_sold"] = time_remaining if time_remaining else "N/A"
                        df.loc[df["url"] == url, "status"] = "Active"
                        evidence = "live_countdown_present"
                    elif is_referred:
                        print("  Condition: Referred or Canceled indicator found - Set to Referred")
                        df.loc[df["url"] == url, "time_remaining_or_date_sold"] = "N/A"
                        df.loc[df["url"] == url, "status"] = "Referred"
                        evidence = "referred_or_cancelled_indicator"
                    elif date_sold and int(bids) > 0:  # Prioritize date_sold and bids for Sold
                        print("  Condition: Date sold and bids found - Set to Sold")
                        df.loc[df["url"] == url, "time_remaining_or_date_sold"] = date_sold
                        df.loc[df["url"] == url, "status"] = "Sold"
                        evidence = "date_sold_and_bids"
                    elif price != "N/A" and int(bids) > 0:
                        print("  Condition: Price and bids present, no date sold - Set to Sold with current date")
                        df.loc[df["url"] == url, "time_remaining_or_date_sold"] = datetime.now().strftime("%Y-%m-%d")
                        df.loc[df["url"] == url, "status"] = "Sold"
                        evidence = "price_and_bids_present"
                    else:
                        print("  Condition: No active, referred, or valid sold criteria - Set to Referred")
                        df.loc[df["url"] == url, "time_remaining_or_date_sold"] = "N/A"
                        df.loc[df["url"] == url, "status"] = "Referred"
                        evidence = "fallback_referred"

                    row_frame = df.loc[df["url"] == url]
                    if not row_frame.empty:
                        obs = _state_observation_from_row(
                            row_frame.iloc[0],
                            run_id=run_id,
                            observed_at=_utc_now_iso(),
                            evidence=evidence,
                            fetch_failed=False,
                        )
                        state_df, _ = upsert_state_row(
                            state_df,
                            obs,
                            fetch_fail_dead_threshold=STATE_DEAD_URL_THRESHOLD,
                        )

                    record_snapshot(df, url, price, bids, time_remaining)

                    # Mark as processed
                    with open(PROGRESS_FILE, 'a') as f:
                        f.write(url + '\n')
                    processed_since_last_save += 1
                    if processed_since_last_save >= save_interval:
                        persist_dataframe(df, f"Checkpoint after {idx + 1} listings")
                        persist_state_dataframe(state_df, f"State checkpoint after {idx + 1} listings")
                        processed_since_last_save = 0
                finally:
                    if remaining_urls:
                        remaining_urls.pop(0)
                        save_resume_queue(remaining_urls)

            await browser.close()

        # Save updated DataFrame
        persist_dataframe(df, "Final save")
        persist_state_dataframe(state_df, "Final state save")
        retention_scope_urls = urls if input_links else None
        retention_urls = select_snapshot_retention_urls(df, retention_scope_urls)
        retention_result = compact_active_snapshots(active_urls=retention_urls)
        print(
            "active_snapshots.csv compacted "
            f"({retention_result.current_rows} live latest rows, "
            f"{retention_result.archived_rows} archived history rows)."
        )
        touched_count = len(urls) if input_links else len(df)
        print(f"active_vehicle_details.csv refreshed ({touched_count} listings touched, {len(df)} total records).")

        # Save skipped URLs to file
        if skipped_urls:
            os.makedirs(os.path.dirname(SKIPPED_LOG), exist_ok=True)
            with open(SKIPPED_LOG, 'a') as f:
                for url in skipped_urls:
                    f.write(url + "\n")
            print(f"Saved {len(skipped_urls)} skipped URLs to {SKIPPED_LOG}")

        # Clear progress file on successful completion
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print(f"Cleared progress file {PROGRESS_FILE}")
        clear_resume_queue()

        if not skip_master:
            try:
                from scripts import update_master

                update_master.update_master_database()
            except Exception as exc:
                logger.error(f"Failed to run update_master after update_bids: {exc}")

        return df, skipped_urls
    except Exception as e:
        logger.error(f"Unexpected error in update_bids: {e}")
        if "df" in locals():
            try:
                persist_dataframe(df, "Emergency save")
                if "state_df" in locals():
                    persist_state_dataframe(state_df, "Emergency state save")
            except Exception as save_error:  # noqa: BLE001
                logger.error(f"Failed to persist emergency snapshot: {save_error}")
        return df, skipped_urls

# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Update active listing bids/status.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of listings to update.")
    parser.add_argument(
        "--batch-interval",
        type=int,
        default=None,
        help="Checkpoint save interval override.",
    )
    parser.add_argument(
        "--skip-master",
        action="store_true",
        help="Skip running update_master after bids update completes.",
    )
    args = parser.parse_args()

    asyncio.run(
        update_bids(
            limit=args.limit,
            batch_interval=args.batch_interval,
            skip_master=args.skip_master,
        )
    )
