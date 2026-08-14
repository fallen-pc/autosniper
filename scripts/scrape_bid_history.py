from __future__ import annotations

import argparse
import asyncio
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import append_dict_rows_csv_atomic
    from shared.csv_utils import CSV_READ_ERRORS
    from shared.data_loader import dataset_path
else:  # pragma: no cover
    from scripts.atomic_csv import append_dict_rows_csv_atomic
    from shared.csv_utils import CSV_READ_ERRORS
    from shared.data_loader import dataset_path


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

DEFAULT_INPUT = dataset_path("active_vehicle_details.csv")
DEFAULT_OUTPUT = dataset_path("bid_history.csv")

PRIMARY_BID_SELECTOR = "a[data-target=\"#dvBidHistoryPop\"]"
FALLBACK_SELECTORS = [
    "#biddableLot > form > div > div.dls-text-medium.position-relative > a",
    "a[href=\"#dvBidHistoryPop\"]",
]


def _load_urls(
    input_path: Path,
    limit: int | None,
    *,
    skip_existing: bool,
    output_path: Path,
) -> list[str]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")
    df = pd.read_csv(input_path)
    if "url" not in df.columns:
        raise ValueError("Input CSV must include a 'url' column.")
    urls = df["url"].dropna().astype(str).str.strip()
    urls = urls[urls.str.startswith("http")]
    if skip_existing and output_path.exists():
        try:
            existing = pd.read_csv(output_path, usecols=["url"])
            existing_urls = set(existing["url"].dropna().astype(str).str.strip())
            urls = urls[~urls.isin(existing_urls)]
        except CSV_READ_ERRORS as exc:
            print(
                f"WARNING: could not read existing bid history {output_path} "
                f"({type(exc).__name__}: {exc}); re-scraping every URL."
            )
    if limit is not None and limit > 0:
        urls = urls.head(limit)
    return urls.tolist()


def _normalize_header(header: str) -> str:
    cleaned = " ".join(header.strip().lower().split())
    cleaned = cleaned.replace("#", "number")
    cleaned = "".join(ch if ch.isalnum() or ch == " " else " " for ch in cleaned)
    cleaned = "_".join(part for part in cleaned.split() if part)
    return cleaned


def _extract_table_rows(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    modal = soup.select_one("#dvBidHistoryPop")
    table = None
    if modal is not None:
        table = modal.select_one("#tblBiddingHistory") or modal.find("table")
    if table is None:
        table = soup.select_one("#tblBiddingHistory") or soup.find("table")
    if table is None:
        return []

    headers: list[str] = []
    header_row = table.find("thead")
    if header_row:
        headers = [cell.get_text(" ", strip=True) for cell in header_row.find_all(["th", "td"])]
    if not headers:
        first_row = table.find("tr")
        if first_row:
            headers = [cell.get_text(" ", strip=True) for cell in first_row.find_all(["th", "td"])]
    header_keys = [_normalize_header(header) for header in headers] if headers else []

    body_rows = table.find("tbody")
    rows = body_rows.find_all("tr") if body_rows else table.find_all("tr")
    records: list[dict[str, str]] = []
    for row in rows:
        cells = row.find_all("td")
        if not cells:
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells]
        if header_keys and len(header_keys) == len(values):
            record = dict(zip(header_keys, values))
        else:
            record = {f"col_{idx + 1}": value for idx, value in enumerate(values)}
        records.append(record)
    return records


def _extract_reserve_met(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.find(
            string=lambda text: isinstance(text, str) and "reserve met" in text.lower()
        )
    )


async def _scrape_bid_history(page, url: str) -> tuple[list[dict[str, str]], bool]:
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(random.randint(600, 1200))

    clicked = False
    for selector in [PRIMARY_BID_SELECTOR] + FALLBACK_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            await page.locator(selector).first.scroll_into_view_if_needed()
            await page.click(selector, timeout=5000)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        try:
            bids_link = page.locator("a.dls-bluelink").filter(
                has_text=re.compile(r"\b\d+\s+bids?\b", re.IGNORECASE)
            )
            if await bids_link.count() > 0:
                await bids_link.first.scroll_into_view_if_needed()
                await bids_link.first.click(timeout=5000)
                clicked = True
        except Exception:
            clicked = False
    if not clicked:
        html = await page.content()
        return [], _extract_reserve_met(html)

    try:
        await page.wait_for_selector("#dvBidHistoryPop", timeout=8000)
        await page.wait_for_timeout(600)
    except Exception:
        html = await page.content()
        return [], _extract_reserve_met(html)

    html = await page.content()
    return _extract_table_rows(html), _extract_reserve_met(html)


def _write_rows(path: Path, rows: Iterable[dict[str, object]]) -> None:
    fieldnames = [
        "scraped_at",
        "url",
        "row_index",
        "bidding_details",
        "bidder_name",
        "bid_time",
        "bid_price",
        "bid_qty",
        "win_qty",
        "reserve_met",
    ]
    append_dict_rows_csv_atomic(path, fieldnames, rows)


async def run_scrape(
    input_path: Path,
    output_path: Path,
    limit: int | None,
    per_url_timeout: int,
    skip_existing: bool,
) -> None:
    urls = _load_urls(input_path, limit, skip_existing=skip_existing, output_path=output_path)
    if not urls:
        print("No URLs to scrape.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
        page = await context.new_page()

        for idx, url in enumerate(urls, start=1):
            print(f"[{idx}/{len(urls)}] {url}")
            try:
                rows, reserve_met = await asyncio.wait_for(
                    _scrape_bid_history(page, url),
                    timeout=per_url_timeout,
                )
            except Exception as exc:
                print(f"  Error: {exc}")
                rows = []
                reserve_met = False
            payload = []
            timestamp = datetime.now(timezone.utc).isoformat()
            for row_index, row in enumerate(rows, start=1):
                if "col_1" in row and not row.get("bidding_details"):
                    fallback = [row.get(f"col_{i}", "") for i in range(1, 6)]
                    row = {
                        "bidding_details": fallback[0],
                        "bid_time": fallback[1],
                        "bid_price": fallback[2],
                        "bid_qty": fallback[3],
                        "win_qty": fallback[4],
                    }
                bidder_name = row.get("bidding_details", "")
                payload.append(
                    {
                        "scraped_at": timestamp,
                        "url": url,
                        "row_index": row_index,
                        "bidding_details": row.get("bidding_details", ""),
                        "bidder_name": bidder_name,
                        "bid_time": row.get("bid_time", ""),
                        "bid_price": row.get("bid_price", ""),
                        "bid_qty": row.get("bid_qty", ""),
                        "win_qty": row.get("win_qty", ""),
                        "reserve_met": reserve_met,
                    }
                )
            if payload:
                _write_rows(output_path, payload)
                print(f"  -> {len(payload)} bid rows")
            else:
                print("  -> no bid history table found")

        await context.close()
        await browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape bid history tables from Grays listing pages.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="CSV containing listing URLs.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output CSV path.")
    parser.add_argument("--limit", type=int, default=0, help="Max number of URLs to scrape (0 = all).")
    parser.add_argument(
        "--per-url-timeout",
        type=int,
        default=60,
        help="Timeout in seconds per listing scrape.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip URLs already present in the output CSV.",
    )
    args = parser.parse_args()
    limit = args.limit if args.limit and args.limit > 0 else None
    asyncio.run(
        run_scrape(
            args.input,
            args.output,
            limit,
            args.per_url_timeout,
            args.skip_existing,
        )
    )


if __name__ == "__main__":
    main()
