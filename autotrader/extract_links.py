"""
Autotrader link discovery (WIP).

This mirrors the structure of `scripts/extract_links.py` but keeps everything self-contained
so we can experiment without touching the live Grays workflow.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .settings import ALL_LINKS_CSV, SEARCH_BASE_URL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _iter_listing_urls(html: str) -> Iterable[str]:
    """
    Guess listing URLs from a single Autotrader results page.

    The exact selectors will need refinement once we confirm the markup, so this
    function intentionally errs on the side of verbosity with logging.
    """
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = anchor.get_text(strip=True)
        if not href or not text:
            continue
        if "/car/" in href or "/cars/details/" in href:
            yield href if href.startswith("http") else f"https://www.autotrader.com.au{href}"


def crawl_autotrader_links(max_pages: int | None = None) -> pd.DataFrame:
    """
    Attempt to paginate through Autotrader search results and save unique listing URLs.

    Parameters
    ----------
    max_pages:
        Optional safety limit so we do not hammer the site while experimenting.
    """
    discovered: set[str] = set()
    page = 1

    while True:
        if max_pages is not None and page > max_pages:
            logger.info("Reached max_pages=%s; stopping.", max_pages)
            break

        url = f"{SEARCH_BASE_URL}?page={page}"
        logger.info("Fetching %s", url)
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            logger.warning("Stopping on non-200 status %s for %s", response.status_code, url)
            break

        before_count = len(discovered)
        for listing_url in _iter_listing_urls(response.text):
            discovered.add(listing_url)
        after_count = len(discovered)
        logger.info("Page %s added %s new URLs (total %s)", page, after_count - before_count, after_count)

        # Autotrader stops paginating when there are no results; break if nothing new arrived.
        if before_count == after_count:
            logger.info("No new URLs found on page %s; assuming end of pagination.", page)
            break

        page += 1

    df = pd.DataFrame(sorted(discovered), columns=["url"])
    df.to_csv(ALL_LINKS_CSV, index=False)
    logger.info("Saved %s URLs to %s", len(df), ALL_LINKS_CSV)
    return df


async def main() -> None:
    # Keep the entry point symmetrical with other scripts so we can invoke via `python autotrader/extract_links.py`.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, crawl_autotrader_links)


if __name__ == "__main__":
    asyncio.run(main())
