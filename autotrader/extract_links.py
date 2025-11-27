"""
Autotrader link discovery (WIP).

This mirrors the structure of `scripts/extract_links.py` but keeps everything self-contained
so we can experiment without touching the live Grays workflow.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError, async_playwright

if __package__ in (None, ""):
    # Support execution via `python autotrader/extract_links.py`
    import sys

    sys.path.append(str(Path(__file__).resolve().parent))
    from settings import ALL_LINKS_CSV, SEARCH_BASE_URL
else:
    from .settings import ALL_LINKS_CSV, SEARCH_BASE_URL

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


class AutotraderRequestBlocked(RuntimeError):
    """Raised when Autotrader blocks plain HTTP scraping."""


def _parse_cookie_header(raw_cookie: str) -> dict[str, str]:
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


def _cookie_domain() -> str:
    parsed = urlparse(SEARCH_BASE_URL)
    hostname = parsed.hostname or "www.autotrader.com.au"
    return hostname


RAW_COOKIE = os.getenv("AUTOTRADER_COOKIE", "").strip()
COOKIE_DICT = _parse_cookie_header(RAW_COOKIE) if RAW_COOKIE else {}
STORAGE_STATE_PATH = os.getenv("AUTOTRADER_STORAGE_STATE", "").strip()
COOKIE_DOMAIN = _cookie_domain()


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


def _persist_links(urls: Iterable[str]) -> pd.DataFrame:
    unique_urls = sorted({u for u in urls if isinstance(u, str)})
    df = pd.DataFrame(unique_urls, columns=["url"])
    df.to_csv(ALL_LINKS_CSV, index=False)
    logger.info("Saved %s URLs to %s", len(df), ALL_LINKS_CSV)
    return df


def _crawl_via_requests(max_pages: int | None) -> set[str]:
    """
    Attempt to crawl listing URLs with plain HTTP requests.

    Returns the set of discovered URLs, or raises `AutotraderRequestBlocked`
    if the site rejects our requests (currently a 403 with Peakhour).
    """
    discovered: set[str] = set()
    page = 1
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if COOKIE_DICT:
        session.cookies.update(COOKIE_DICT)

    while True:
        if max_pages is not None and page > max_pages:
            logger.info("Reached max_pages=%s; stopping.", max_pages)
            break

        url = f"{SEARCH_BASE_URL}?page={page}"
        logger.info("Fetching %s via requests", url)
        response = session.get(url, timeout=30)

        if response.status_code == 403:
            raise AutotraderRequestBlocked(
                "Autotrader returned 403 (Peakhour) for listing search."
            )
        if response.status_code != 200:
            logger.warning("Stopping on non-200 status %s for %s", response.status_code, url)
            break

        before_count = len(discovered)
        for listing_url in _iter_listing_urls(response.text):
            discovered.add(listing_url)
        after_count = len(discovered)
        logger.info("Page %s added %s new URLs (total %s)", page, after_count - before_count, after_count)

        if before_count == after_count:
            logger.info("No new URLs found on page %s; assuming end of pagination.", page)
            break

        page += 1

    return discovered


async def _crawl_via_playwright(max_pages: int | None) -> set[str]:
    """
    Use Playwright to mimic a browser when Autotrader blocks plain requests.
    """
    discovered: set[str] = set()
    async with async_playwright() as p:
        launch_kwargs = {"headless": True}
        browser = await p.chromium.launch(**launch_kwargs)

        context_kwargs: dict[str, object] = {
            "user_agent": DEFAULT_HEADERS["User-Agent"],
            "locale": "en-US",
            "viewport": {"width": 1280, "height": 720},
        }
        storage_state: str | None = None
        if STORAGE_STATE_PATH:
            state_path = Path(STORAGE_STATE_PATH)
            if state_path.exists():
                storage_state = str(state_path)
                context_kwargs["storage_state"] = storage_state
            else:
                logger.warning(
                    "AUTOTRADER_STORAGE_STATE=%s does not exist; ignoring.", STORAGE_STATE_PATH
                )

        context = await browser.new_context(**context_kwargs)
        if COOKIE_DICT and not storage_state:
            cookies_for_context = [
                {
                    "name": key,
                    "value": value,
                    "domain": COOKIE_DOMAIN,
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                }
                for key, value in COOKIE_DICT.items()
            ]
            await context.add_cookies(cookies_for_context)

        page = await context.new_page()

        current_page = 1
        while True:
            if max_pages is not None and current_page > max_pages:
                logger.info("Reached max_pages=%s with Playwright; stopping.", max_pages)
                break

            url = f"{SEARCH_BASE_URL}?page={current_page}"
            logger.info("Fetching %s via Playwright", url)
            try:
                response = await page.goto(url, wait_until="networkidle", timeout=60000)
            except PlaywrightError as exc:
                logger.warning("Stopping Playwright crawl on %s for %s", exc, url)
                break
            if response and response.status == 403:
                raise AutotraderRequestBlocked(
                    "Autotrader returned 403 to Playwright navigation; a browser cookie or storage state is required."
                )

            await page.wait_for_timeout(1500)

            hrefs = await page.eval_on_selector_all(
                "a[href]",
                "elements => elements.map(el => el.href)",
            )

            before_count = len(discovered)
            for href in hrefs:
                if not isinstance(href, str):
                    continue
                if "/car/" not in href and "/cars/details/" not in href:
                    continue
                discovered.add(href)

            after_count = len(discovered)
            logger.info(
                "Page %s added %s new URLs (total %s)",
                current_page,
                after_count - before_count,
                after_count,
            )

            if before_count == after_count:
                logger.info("No new URLs found on page %s; assuming end of pagination.", current_page)
                break

            current_page += 1

        await context.close()
        await browser.close()

    return discovered


def _run_playwright_crawl(max_pages: int | None) -> set[str]:
    try:
        return asyncio.run(_crawl_via_playwright(max_pages))
    except RuntimeError as runtime_exc:
        if "asyncio.run()" in str(runtime_exc):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_crawl_via_playwright(max_pages))
            finally:
                loop.close()
        raise


def crawl_autotrader_links(max_pages: int | None = None) -> pd.DataFrame:
    """
    Attempt to paginate through Autotrader search results and save unique listing URLs.

    Parameters
    ----------
    max_pages:
        Optional safety limit so we do not hammer the site while experimenting.
    """
    try:
        discovered = _crawl_via_requests(max_pages)
    except AutotraderRequestBlocked as blocked_exc:
        logger.warning(
            "%s Falling back to Playwright to mimic a real browser.", blocked_exc
        )
        try:
            discovered = _run_playwright_crawl(max_pages)
        except PlaywrightError as playwright_exc:
            logger.error(
                "Playwright fallback failed: %s",
                playwright_exc,
            )
            logger.error(
                "Run `playwright install` and ensure system dependencies "
                "(libnss3, libnspr4, libasound2) are available."
            )
            if not COOKIE_DICT:
                logger.error(
                    "If Autotrader still responds with 403, export a browser session cookie "
                    "and set AUTOTRADER_COOKIE (e.g. \"PEAKHOUR_VISIT=...\") or a Playwright "
                    "storage state via AUTOTRADER_STORAGE_STATE."
                )
            raise
        except AutotraderRequestBlocked as cookie_exc:
            logger.error(
                "%s Set AUTOTRADER_COOKIE (copy the browser `Cookie` header) or "
                "AUTOTRADER_STORAGE_STATE (Playwright JSON) so the scraper can authenticate.",
                cookie_exc,
            )
            return _persist_links([])

    if not discovered:
        logger.warning("No URLs discovered; nothing to persist.")
        return _persist_links([])

    return _persist_links(discovered)


async def main() -> None:
    # Keep the entry point symmetrical with other scripts so we can invoke via `python autotrader/extract_links.py`.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, crawl_autotrader_links)


if __name__ == "__main__":
    asyncio.run(main())
