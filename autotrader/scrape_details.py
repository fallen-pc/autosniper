"""
Autotrader listing detail scraper (WIP).

This uses Playwright similarly to `scripts/update_bids.py`, but it only touches CSVs
inside the `autotrader/` sandbox.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Iterable, Tuple

import pandas as pd
from playwright.async_api import async_playwright

if __package__ in (None, ""):
    # Allow running the script directly: `python autotrader/scrape_details.py`
    import sys
    from pathlib import Path

    sys.path.append(str(Path(__file__).resolve().parent))
    from settings import ALL_LINKS_CSV, DETAILS_CSV, SKIPPED_LOG
else:
    from .settings import ALL_LINKS_CSV, DETAILS_CSV, SKIPPED_LOG

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def _scrape_listing(page, url: str) -> Tuple[str, str, str, str]:
    """
    Placeholder extraction logic.

    Replace the selectors once we inspect Autotrader's DOM.
    """
    await page.goto(url, wait_until="load", timeout=60000)
    await page.wait_for_timeout(2000)

    title = await page.locator("h1").inner_text(timeout=3000)
    price = await page.locator("[data-cy='advert-price']").inner_text(timeout=3000)
    odometer = await page.locator("text=km").first.inner_text(timeout=3000)
    location = await page.locator("text=Location").first.inner_text(timeout=3000)
    return title, price, odometer, location


async def refresh_autotrader_details(urls: Iterable[str] | None = None) -> pd.DataFrame:
    """
    Fetch or update vehicle details for the supplied URLs.
    """
    df = pd.DataFrame(columns=["url", "title", "price", "odometer", "location", "last_checked"])
    source_urls: list[str]

    if urls is not None:
        source_urls = [u for u in urls if isinstance(u, str) and u.startswith("http")]
    elif ALL_LINKS_CSV.exists():
        existing_links = pd.read_csv(ALL_LINKS_CSV)
        source_urls = existing_links["url"].dropna().unique().tolist()
    else:
        logger.warning("No URLs supplied and %s not found.", ALL_LINKS_CSV)
        return df

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        skipped: list[str] = []
        rows = []
        for idx, url in enumerate(source_urls, start=1):
            logger.info("(%s/%s) Scraping %s", idx, len(source_urls), url)
            try:
                title, price, odometer, location = await _scrape_listing(page, url)
                rows.append(
                    {
                        "url": url,
                        "title": title,
                        "price": price,
                        "odometer": odometer,
                        "location": location,
                        "last_checked": datetime.utcnow().isoformat(),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to scrape %s: %s", url, exc)
                skipped.append(url)

        await browser.close()

    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(DETAILS_CSV, index=False)
        logger.info("Saved %s rows to %s", len(df), DETAILS_CSV)

    if skipped:
        with open(SKIPPED_LOG, "a", encoding="utf-8") as handle:
            for url in skipped:
                handle.write(f"{url}\n")
        logger.info("Logged %s skipped URLs to %s", len(skipped), SKIPPED_LOG)

    return df


async def main() -> None:
    await refresh_autotrader_details()


if __name__ == "__main__":
    asyncio.run(main())
