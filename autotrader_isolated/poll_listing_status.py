"""Poll individual Autotrader listing URLs to get a definitive live/gone signal.

Why this exists
---------------
`scrape_first_page.py` infers that a listing sold when it is absent from a search
result page. That inference is unreliable: absence is produced by scrape scope
changes, pagination and sort-order churn just as often as by a real market exit.
In the recorded history 47.6% of `sold` events were later contradicted by the
listing reappearing, and a single run marked 13,123 listings sold purely because
the scrape scope widened that day.

This module asks each listing directly instead. It requests the listing's own URL
and classifies the response, so the signal does not depend on search scope at all.

Design rules
------------
* Never conclude "gone" from an ambiguous response. Timeouts, 403s, 429s and 5xx
  are recorded as ``unknown`` and retried on a later run.
* Require several consecutive definitive-gone observations before confirming an
  exit, so a single transient 404 cannot retire a live listing.
* Write to a separate state file. The legacy `status` column in
  `listing_state.csv` stays untouched so the two signals remain distinguishable
  and the existing pipeline is unaffected.

Calibration
-----------
The exact markup Autotrader serves for a withdrawn listing is not known ahead of
time. Primary signals (404/410, redirect away from the listing id) need no
calibration. The secondary content patterns in ``DEFAULT_GONE_PATTERNS`` do —
use ``--probe <url>`` to dump what the site actually returns for a known-gone and
a known-live listing, then refine the patterns with ``--gone-patterns-file``.

Usage
-----
    python autotrader_isolated/poll_listing_status.py --dry-run
    python autotrader_isolated/poll_listing_status.py --probe car/14810823/toyota/camry/vic/coburg-north/sedan
    python autotrader_isolated/poll_listing_status.py --cookie-file autotrader_isolated/output/autotrader_cookie.txt
    python autotrader_isolated/poll_listing_status.py --tagged-only --max-listings 500
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scripts.atomic_csv import write_dataframe_csv_atomic

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
STATE_INPUT = OUTPUT_DIR / "listing_state.csv"
TAGGED_INPUT = OUTPUT_DIR / "autotrader_recent_market_tagged.csv"
EXIT_STATE_OUTPUT = OUTPUT_DIR / "listing_exit_state.csv"
EXIT_LOG_OUTPUT = OUTPUT_DIR / "listing_exit_log.csv"
DEFAULT_STORAGE_STATE = OUTPUT_DIR / "storage_state.json"

BASE_URL = "https://www.autotrader.com.au"
LISTING_ID_RE = re.compile(r"/?car/(\d+)/", re.IGNORECASE)

# Headers mirror scrape_first_page.DEFAULT_HEADERS. Duplicated rather than imported
# so this module stays importable without pulling in Playwright.
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
    "Referer": f"{BASE_URL}/",
    "Upgrade-Insecure-Requests": "1",
}

# Autotrader announces a removed listing by redirecting to /for-sale?removed=true.
# Confirmed by probe on 2026-07-28: a listing removed back in January redirected to
# "https://www.autotrader.com.au/for-sale?removed=true", while a live listing stayed
# on its own URL. This is the site's own explicit signal and is the primary detector.
REMOVED_REDIRECT_MARKERS: tuple[str, ...] = ("removed=true",)

# Deliberately EMPTY by default.
#
# The redirect signal above is definitive and verified, so content matching is not
# needed for the real case. Enabling unverified phrases is actively harmful here: a
# live listing page carrying text like "has been sold" in a recommendations module
# would be classified gone, which is precisely the failure mode this module exists to
# eliminate. Both calibration probes matched zero content patterns, confirming they
# earn nothing today.
#
# The mechanism is kept for a soft-404 (200 with no redirect) should one ever appear.
# Supply phrases via --gone-patterns-file, and verify with --probe before trusting them.
DEFAULT_GONE_PATTERNS: tuple[str, ...] = ()

VERDICT_LIVE = "live"
VERDICT_GONE = "gone"
VERDICT_UNKNOWN = "unknown"

EXIT_STATE_COLUMNS = [
    "url",
    "first_polled",
    "last_polled",
    "poll_count",
    "last_verdict",
    "last_reason",
    "last_http_status",
    "last_live_date",
    "consecutive_gone",
    "confirmed_gone_date",
    "exit_price",
    "unknown_streak",
]

EXIT_LOG_COLUMNS = [
    "poll_ts",
    "url",
    "http_status",
    "final_url",
    "verdict",
    "reason",
    "elapsed_ms",
]

DEFAULT_CONFIRM_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Pure logic (unit tested — no network)
# ---------------------------------------------------------------------------


def listing_id(url: str) -> str:
    """Extract the numeric listing id from a listing URL, or '' when absent."""
    match = LISTING_ID_RE.search(url or "")
    return match.group(1) if match else ""


def absolute_listing_url(url: str) -> str:
    """Turn a stored relative listing path into a full URL."""
    raw = str(url or "").strip()
    if not raw:
        return ""
    if raw.startswith("http"):
        return raw
    return f"{BASE_URL}/{raw.lstrip('/')}"


def classify_response(
    *,
    url: str,
    status_code: Optional[int],
    final_url: str,
    html: str,
    gone_patterns: Iterable[str] = DEFAULT_GONE_PATTERNS,
    error: str = "",
) -> tuple[str, str]:
    """Classify one poll result as live / gone / unknown.

    Only definitive evidence produces ``gone``. Anything that could be a transient
    failure or an anti-bot response produces ``unknown`` so the listing is retried
    rather than silently retired.
    """
    if error:
        return VERDICT_UNKNOWN, f"request_error:{error[:80]}"

    if status_code is None:
        return VERDICT_UNKNOWN, "no_status"

    # Definitive removal.
    if status_code in (404, 410):
        return VERDICT_GONE, f"http_{status_code}"

    # Blocked / rate limited / server trouble — tells us nothing about the listing.
    if status_code in (401, 403, 407, 429) or status_code >= 500:
        return VERDICT_UNKNOWN, f"http_{status_code}"

    if status_code != 200:
        return VERDICT_UNKNOWN, f"http_{status_code}"

    # Autotrader's own explicit removal signal — highest confidence available.
    lowered_final = (final_url or "").lower()
    for marker in REMOVED_REDIRECT_MARKERS:
        if marker and marker.lower() in lowered_final:
            return VERDICT_GONE, "redirect_removed_flag"

    wanted = listing_id(url)
    landed = listing_id(final_url)

    # Redirected away from the listing (typically to search or home) => removed.
    if wanted and landed and wanted != landed:
        return VERDICT_GONE, "redirected_to_other_listing"
    if wanted and not landed:
        return VERDICT_GONE, "redirected_off_listing"

    lowered = (html or "").lower()
    for pattern in gone_patterns:
        needle = str(pattern).strip().lower()
        if needle and needle in lowered:
            return VERDICT_GONE, f"content:{needle[:40]}"

    if wanted and landed and wanted == landed:
        return VERDICT_LIVE, "listing_id_present"

    # 200 but we cannot tell. Do not guess.
    return VERDICT_UNKNOWN, "indeterminate_200"


def blank_exit_state(url: str) -> dict[str, Any]:
    return {
        "url": url,
        "first_polled": "",
        "last_polled": "",
        "poll_count": 0,
        "last_verdict": "",
        "last_reason": "",
        "last_http_status": "",
        "last_live_date": "",
        "consecutive_gone": 0,
        "confirmed_gone_date": "",
        "exit_price": "",
        "unknown_streak": 0,
    }


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "" or pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def update_exit_state(
    row: dict[str, Any],
    *,
    verdict: str,
    reason: str,
    http_status: Optional[int],
    poll_ts: str,
    confirm_threshold: int = DEFAULT_CONFIRM_THRESHOLD,
    known_price: Any = "",
) -> dict[str, Any]:
    """Fold one poll result into a listing's exit state.

    A confirmed exit requires ``confirm_threshold`` consecutive gone verdicts. A
    live verdict resets the counter and clears any prior confirmation, so a
    relisted vehicle correctly returns to live.
    """
    updated = dict(row)
    updated["last_polled"] = poll_ts
    updated["poll_count"] = _as_int(updated.get("poll_count")) + 1
    updated["last_verdict"] = verdict
    updated["last_reason"] = reason
    updated["last_http_status"] = "" if http_status is None else int(http_status)
    if not updated.get("first_polled"):
        updated["first_polled"] = poll_ts

    if verdict == VERDICT_LIVE:
        updated["consecutive_gone"] = 0
        updated["unknown_streak"] = 0
        updated["last_live_date"] = poll_ts
        # A listing that is live again was not an exit after all.
        updated["confirmed_gone_date"] = ""
        updated["exit_price"] = ""
    elif verdict == VERDICT_GONE:
        updated["unknown_streak"] = 0
        streak = _as_int(updated.get("consecutive_gone")) + 1
        updated["consecutive_gone"] = streak
        if streak >= confirm_threshold and not updated.get("confirmed_gone_date"):
            updated["confirmed_gone_date"] = poll_ts
            updated["exit_price"] = "" if known_price is None else known_price
    else:
        # Unknown leaves the gone streak untouched: we learned nothing either way.
        updated["unknown_streak"] = _as_int(updated.get("unknown_streak")) + 1

    return updated


def select_listings_to_poll(
    state_df: pd.DataFrame,
    exit_df: pd.DataFrame,
    *,
    tagged_urls: set[str] | None = None,
    max_listings: int | None = None,
    recheck_confirmed: bool = False,
    min_hours_between_polls: float = 12.0,
    now: datetime | None = None,
) -> list[str]:
    """Choose which listings to poll this run, least-recently-polled first.

    Confirmed exits are dropped unless ``recheck_confirmed`` is set, and anything
    polled within ``min_hours_between_polls`` is skipped so repeated runs in a day
    do not re-hit the same URLs.
    """
    if state_df.empty or "url" not in state_df.columns:
        return []

    now = now or datetime.now(UTC)
    candidates = state_df[["url"]].copy()
    candidates["url"] = candidates["url"].astype(str).str.strip()
    candidates = candidates[candidates["url"] != ""].drop_duplicates(subset=["url"])

    if tagged_urls is not None:
        candidates = candidates[candidates["url"].isin(tagged_urls)]

    if exit_df is not None and not exit_df.empty and "url" in exit_df.columns:
        prior = exit_df.copy()
        prior["url"] = prior["url"].astype(str).str.strip()
        keep_cols = [c for c in ("url", "last_polled", "confirmed_gone_date") if c in prior.columns]
        candidates = candidates.merge(prior[keep_cols], on="url", how="left")
    else:
        candidates["last_polled"] = pd.NA
        candidates["confirmed_gone_date"] = pd.NA

    if not recheck_confirmed and "confirmed_gone_date" in candidates.columns:
        # Keep rows with no confirmation yet. A never-tracked listing has NaN here,
        # so it must be kept — not treated as confirmed.
        confirmed = candidates["confirmed_gone_date"]
        candidates = candidates[
            confirmed.isna() | confirmed.astype(str).str.strip().isin({"", "nan", "NaT"})
        ]

    last_polled = pd.to_datetime(candidates.get("last_polled"), errors="coerce", utc=True)
    if min_hours_between_polls > 0:
        cutoff = pd.Timestamp(now) - pd.Timedelta(hours=min_hours_between_polls)
        candidates = candidates[last_polled.isna() | (last_polled <= cutoff)]
        last_polled = last_polled.reindex(candidates.index)

    # Never-polled first, then oldest poll first.
    candidates = candidates.assign(_sort=last_polled.fillna(pd.Timestamp("1970-01-01", tz="UTC")))
    candidates = candidates.sort_values("_sort")

    urls = candidates["url"].tolist()
    if max_listings is not None and max_listings > 0:
        urls = urls[:max_listings]
    return urls


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def _parse_cookie_header(raw_cookie: str) -> dict[str, str]:
    raw_cookie = (raw_cookie or "").strip()
    if raw_cookie.lower().startswith("cookie:"):
        raw_cookie = raw_cookie.split(":", 1)[1].strip()
    cookies: dict[str, str] = {}
    for part in raw_cookie.split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


_thread_local = threading.local()


def _session_for_thread(cookie_header: str | None) -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        if cookie_header:
            session.cookies.update(_parse_cookie_header(cookie_header))
        _thread_local.session = session
    return session


def poll_one(
    url: str,
    *,
    cookie_header: str | None,
    timeout: int,
    gone_patterns: Iterable[str],
    delay: float = 0.0,
) -> dict[str, Any]:
    """Fetch a single listing URL and classify it. Never raises."""
    if delay > 0:
        time.sleep(delay)
    target = absolute_listing_url(url)
    started = time.monotonic()
    status_code: Optional[int] = None
    final_url = ""
    html = ""
    error = ""
    try:
        session = _session_for_thread(cookie_header)
        response = session.get(target, timeout=timeout, allow_redirects=True)
        status_code = response.status_code
        final_url = str(response.url or "")
        # Only read the body when it can change the verdict.
        if status_code == 200:
            html = response.text or ""
    except requests.RequestException as exc:
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - a poll must never abort the run
        error = f"{type(exc).__name__}: {exc}"

    verdict, reason = classify_response(
        url=url,
        status_code=status_code,
        final_url=final_url,
        html=html,
        gone_patterns=gone_patterns,
        error=error,
    )
    return {
        "url": url,
        "http_status": status_code,
        "final_url": final_url,
        "verdict": verdict,
        "reason": reason,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


# ---------------------------------------------------------------------------
# Playwright path
#
# Autotrader reliably 403s plain `requests`, exactly as scrape_first_page.py
# already found (it falls back to Playwright on 403, and the scheduler runs it
# headful because headless is blocked too). Polling thousands of listings cannot
# afford a browser launch per URL, so one context is opened for the whole run and
# a small pool of pages works through the queue.
# ---------------------------------------------------------------------------


def _browser_type(playwright: Any, browser_name: str) -> tuple[Any, str | None]:
    name = (browser_name or "").strip().lower()
    if name == "firefox":
        return playwright.firefox, None
    if name == "webkit":
        return playwright.webkit, None
    if name == "chrome":
        return playwright.chromium, "chrome"
    if name == "msedge":
        return playwright.chromium, "msedge"
    return playwright.chromium, None


async def _poll_urls_playwright(
    urls: list[str],
    *,
    storage_state: Path | None,
    cookie_header: str | None,
    timeout: int,
    gone_patterns: Iterable[str],
    browser_name: str,
    headless: bool,
    block_resources: bool,
    concurrency: int,
    delay: float,
    progress_every: int = 250,
    capture_html: bool = False,
    on_checkpoint: Any = None,
    checkpoint_every: int = 0,
) -> list[dict[str, Any]]:
    from playwright.async_api import Error as PlaywrightError, async_playwright

    # The verdict needs only the response status and the redirect target unless
    # content patterns are configured. When none are, stop at "commit" (headers
    # received) instead of waiting for the DOM, and never serialise the page body.
    # On this site that is the difference between ~11s and ~1s per listing.
    need_html = bool(tuple(gone_patterns)) or capture_html
    wait_state = "domcontentloaded" if need_html else "commit"

    results: list[dict[str, Any]] = []
    # Index of the first result not yet handed to on_checkpoint. Long runs must
    # persist as they go: a single write at the end means an interrupted run
    # loses everything, which is exactly what happened to the first backfill.
    flushed = 0

    def _flush_pending(force: bool = False) -> None:
        nonlocal flushed
        if on_checkpoint is None:
            return
        pending = len(results) - flushed
        if pending <= 0:
            return
        if force or (checkpoint_every and pending >= checkpoint_every):
            on_checkpoint(results[flushed:])
            flushed = len(results)

    queue: asyncio.Queue[str] = asyncio.Queue()
    for url in urls:
        queue.put_nowait(url)

    async with async_playwright() as playwright:
        browser_type, channel = _browser_type(playwright, browser_name)
        launch_kwargs: dict[str, Any] = {"headless": headless}
        if channel:
            launch_kwargs["channel"] = channel
        browser = await browser_type.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {
            "user_agent": DEFAULT_HEADERS["User-Agent"],
            "locale": "en-US",
        }
        if storage_state is not None:
            if not storage_state.exists():
                await browser.close()
                raise FileNotFoundError(f"storage state not found: {storage_state}")
            context_kwargs["storage_state"] = str(storage_state)

        context = await browser.new_context(**context_kwargs)
        if block_resources:
            await context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "media", "font", "stylesheet"}
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

        async def worker() -> None:
            page = await context.new_page()
            try:
                while True:
                    try:
                        url = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    if delay > 0:
                        await asyncio.sleep(delay)
                    started = time.monotonic()
                    status_code: Optional[int] = None
                    final_url = ""
                    html = ""
                    error = ""
                    try:
                        response = await page.goto(
                            absolute_listing_url(url),
                            wait_until=wait_state,
                            timeout=timeout * 1000,
                        )
                        final_url = page.url or ""
                        if response is not None:
                            status_code = response.status
                            if status_code == 200 and need_html:
                                html = await page.content()
                        else:
                            error = "no_response"
                    except PlaywrightError as exc:
                        error = f"PlaywrightError: {exc}"
                    except Exception as exc:  # noqa: BLE001 - one bad URL must not kill the run
                        error = f"{type(exc).__name__}: {exc}"

                    verdict, reason = classify_response(
                        url=url,
                        status_code=status_code,
                        final_url=final_url,
                        html=html,
                        gone_patterns=gone_patterns,
                        error=error,
                    )
                    record = {
                        "url": url,
                        "http_status": status_code,
                        "final_url": final_url,
                        "verdict": verdict,
                        "reason": reason,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                    if capture_html:
                        record["_html"] = html
                    results.append(record)
                    if progress_every and len(results) % progress_every == 0:
                        print(f"  polled {len(results):,}/{len(urls):,}", flush=True)
                    _flush_pending()
            finally:
                await page.close()

        try:
            await asyncio.gather(*[worker() for _ in range(max(1, concurrency))])
        finally:
            # Persist whatever completed, including on interrupt or a mid-run failure.
            _flush_pending(force=True)
            try:
                await context.close()
                await browser.close()
            except Exception:  # noqa: BLE001 - teardown must not mask the real error
                pass

    return results


def _run_async(coro: Any) -> Any:
    """Run a coroutine, tolerating an already-running loop (mirrors the scraper)."""
    try:
        return asyncio.run(coro)
    except RuntimeError as exc:
        if "asyncio.run()" not in str(exc):
            raise
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def load_exit_state(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=EXIT_STATE_COLUMNS)
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=EXIT_STATE_COLUMNS)
    return df.reindex(columns=EXIT_STATE_COLUMNS, fill_value="")


def write_exit_state(rows: dict[str, dict[str, Any]], path: Path) -> None:
    frame = pd.DataFrame(list(rows.values()))
    frame = frame.reindex(columns=EXIT_STATE_COLUMNS, fill_value="")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(frame, path, index=False)


def append_exit_log(records: list[dict[str, Any]], path: Path) -> None:
    if not records:
        return
    frame = pd.DataFrame(records).reindex(columns=EXIT_LOG_COLUMNS, fill_value="")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        frame.to_csv(path, mode="a", header=False, index=False)
    else:
        frame.to_csv(path, index=False)


def load_gone_patterns(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return DEFAULT_GONE_PATTERNS
    if not path.exists():
        raise FileNotFoundError(f"gone patterns file not found: {path}")
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    patterns = tuple(line for line in lines if line and not line.startswith("#"))
    return patterns or DEFAULT_GONE_PATTERNS


def _read_cookie(cookie_file: Path | None) -> str | None:
    if cookie_file is None:
        return None
    if not cookie_file.exists():
        raise FileNotFoundError(f"cookie file not found: {cookie_file}")
    return cookie_file.read_text(encoding="utf-8").strip() or None


def relisted_urls(history_path: Path) -> set[str]:
    """URLs the scraper marked sold and then saw again.

    scrape_first_page.py emits a `relisted` event precisely when a URL whose state
    is `sold` reappears in a scrape, so the presence of that event is exactly the
    "this sold flag was later contradicted" signal. 26,197 of 55,021 sold events
    were contradicted this way, which is why these are excluded from the backfill:
    their exit history is known-noisy and a retroactive check would be scored
    against an unreliable baseline.
    """
    if not history_path.exists():
        return set()
    try:
        frame = pd.read_csv(history_path, usecols=["event", "url"], low_memory=False)
    except Exception:
        return set()
    if frame.empty or "event" not in frame.columns:
        return set()
    relisted = frame[frame["event"].astype(str).str.strip() == "relisted"]
    return set(relisted["url"].astype(str).str.strip())


def _tagged_url_set(path: Path) -> set[str] | None:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    if "url" not in df.columns:
        return None
    if "canonical_tag" in df.columns:
        df = df[df["canonical_tag"].notna() & df["canonical_tag"].astype(str).str.strip().ne("")]
    return set(df["url"].astype(str).str.strip())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Poll Autotrader listing URLs directly for a definitive live/gone signal."
    )
    p.add_argument("--state-input", type=Path, default=STATE_INPUT,
                   help="listing_state.csv produced by scrape_first_page.py")
    p.add_argument("--exit-state", type=Path, default=EXIT_STATE_OUTPUT,
                   help="Exit-state CSV to read and update.")
    p.add_argument("--exit-log", type=Path, default=EXIT_LOG_OUTPUT,
                   help="Append-only poll log.")
    p.add_argument("--tagged-input", type=Path, default=TAGGED_INPUT,
                   help="Tagged market CSV used by --tagged-only.")
    p.add_argument("--tagged-only", action="store_true",
                   help="Poll only listings carrying a canonical_tag.")
    p.add_argument("--active-only", action="store_true",
                   help="Poll only listings the legacy scraper still believes are active.")
    p.add_argument("--status", choices=("any", "active", "sold"), default="any",
                   help="Filter by the legacy status column. --active-only is a shorthand "
                        "for --status active. Use --status sold to backfill past exits.")
    p.add_argument("--exclude-relisted", action="store_true",
                   help="Drop listings the scraper ever saw reappear after marking them sold. "
                        "Use with --status sold so the backfill only checks clean exits.")
    p.add_argument("--history-input", type=Path, default=OUTPUT_DIR / "listing_history.csv",
                   help="listing_history.csv, read by --exclude-relisted.")
    p.add_argument("--require-price", action="store_true",
                   help="Skip listings with no recorded last_price. They cannot become resale "
                        "observations, so polling them is wasted work during a backfill.")
    p.add_argument("--checkpoint-every", type=int, default=200,
                   help="Persist state and log every N results (default 200). Long runs must "
                        "checkpoint: an interrupted run otherwise loses everything.")
    p.add_argument("--max-listings", type=int, default=None,
                   help="Cap listings polled this run.")
    p.add_argument("--min-hours-between-polls", type=float, default=12.0,
                   help="Skip listings polled more recently than this (default 12).")
    p.add_argument("--recheck-confirmed", action="store_true",
                   help="Also re-poll listings whose exit is already confirmed.")
    p.add_argument("--confirm-threshold", type=int, default=DEFAULT_CONFIRM_THRESHOLD,
                   help="Consecutive gone verdicts required to confirm an exit (default 2).")
    p.add_argument("--concurrency", type=int, default=4,
                   help="Parallel requests (default 4). Keep this modest.")
    p.add_argument("--delay", type=float, default=0.5,
                   help="Seconds to wait before each request, per worker (default 0.5).")
    p.add_argument("--timeout", type=int, default=20, help="Per-request timeout seconds.")
    p.add_argument("--cookie-file", type=Path, default=None,
                   help="File holding an Autotrader cookie header.")
    p.add_argument("--gone-patterns-file", type=Path, default=None,
                   help="Newline-delimited content patterns that mean 'removed'.")
    p.add_argument("--dry-run", action="store_true",
                   help="Report what would be polled and exit without any network calls.")
    p.add_argument("--probe", type=str, default=None,
                   help="Fetch one listing URL and dump the raw signals, for calibration.")
    p.add_argument("--fetch-mode", choices=("auto", "requests", "playwright"), default="auto",
                   help="auto (default) tries requests once and switches to Playwright on 403.")
    p.add_argument("--storage-state", type=Path, default=DEFAULT_STORAGE_STATE,
                   help="Playwright storage state JSON (Autotrader 403s plain requests).")
    p.add_argument("--playwright-browser", type=str, default=None,
                   help="chromium/chrome/msedge/firefox/webkit (default chrome on Windows).")
    p.add_argument("--playwright-headful", action="store_true",
                   help="Run the browser headful. Autotrader often blocks headless.")
    p.add_argument("--playwright-block-resources", action="store_true", default=True,
                   help="Block images/media/fonts/css for speed (default on).")
    return p.parse_args(argv)


def _default_browser_name(explicit: str | None) -> str:
    if explicit:
        return explicit
    import os

    return "chrome" if os.name == "nt" else "chromium"


def _probe_via_requests(url: str, cookie_header: str | None, timeout: int) -> dict[str, Any]:
    target = absolute_listing_url(url)
    session = _session_for_thread(cookie_header)
    response = session.get(target, timeout=timeout, allow_redirects=True)
    return {
        "status": response.status_code,
        "final_url": str(response.url or ""),
        "body": response.text if response.status_code == 200 else "",
    }


async def _probe_via_playwright(
    url: str,
    *,
    storage_state: Path | None,
    cookie_header: str | None,
    timeout: int,
    browser_name: str,
    headless: bool,
) -> dict[str, Any]:
    results = await _poll_urls_playwright(
        [url],
        storage_state=storage_state,
        cookie_header=cookie_header,
        timeout=timeout,
        gone_patterns=(),  # suppress content verdicts; the probe reports hits itself
        browser_name=browser_name,
        headless=headless,
        block_resources=False,
        concurrency=1,
        delay=0.0,
        progress_every=0,
        capture_html=True,
    )
    return results[0] if results else {}


def _run_probe(url: str, args: argparse.Namespace, cookie_header: str | None,
               gone_patterns: tuple[str, ...]) -> int:
    target = absolute_listing_url(url)
    print(f"probing: {target}")

    status: Optional[int] = None
    final_url = ""
    body = ""
    mode = args.fetch_mode

    if mode in ("auto", "requests"):
        try:
            got = _probe_via_requests(url, cookie_header, args.timeout)
            status, final_url, body = got["status"], got["final_url"], got["body"]
            print(f"  [requests] status {status}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [requests] failed: {type(exc).__name__}: {exc}")
            status = None
        if mode == "auto" and status != 200:
            print("  [requests] not usable, retrying via Playwright ...")
            mode = "playwright"

    if mode == "playwright":
        browser = _default_browser_name(args.playwright_browser)
        try:
            got = _run_async(
                _probe_via_playwright(
                    url,
                    storage_state=args.storage_state,
                    cookie_header=cookie_header,
                    timeout=args.timeout,
                    browser_name=browser,
                    headless=not args.playwright_headful,
                )
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [playwright] failed: {type(exc).__name__}: {exc}")
            return 1
        status = got.get("http_status")
        final_url = got.get("final_url", "")
        body = ""
        print(f"  [playwright] browser={browser} headless={not args.playwright_headful} status {status}")
        # Re-fetch content for pattern inspection when the page loaded.
        if status == 200:
            body = got.get("_html", "") or ""

    lowered = (body or "").lower()
    print(f"  status      : {status}")
    print(f"  final url   : {final_url}")
    print(f"  wanted id   : {listing_id(url) or '(none)'}")
    print(f"  landed id   : {listing_id(final_url) or '(none)'}")
    print(f"  body length : {len(body):,}")
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    print(f"  title       : {title.group(1).strip()[:120] if title else '(none)'}")
    hits = [p for p in gone_patterns if p.lower() in lowered]
    print(f"  gone hits   : {hits or '(none)'}")
    verdict, reason = classify_response(
        url=url,
        status_code=status,
        final_url=final_url,
        html=body,
        gone_patterns=gone_patterns,
    )
    print(f"  VERDICT     : {verdict}  ({reason})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    gone_patterns = load_gone_patterns(args.gone_patterns_file)
    cookie_header = _read_cookie(args.cookie_file)

    if args.probe:
        return _run_probe(args.probe, args, cookie_header, gone_patterns)

    if not args.state_input.exists():
        print(f"ERROR: state input not found: {args.state_input}")
        return 1

    state_df = pd.read_csv(args.state_input, low_memory=False)
    total_rows = len(state_df)

    wanted_status = "active" if args.active_only else args.status
    if wanted_status != "any" and "status" in state_df.columns:
        state_df = state_df[state_df["status"].astype(str).str.strip() == wanted_status]
        print(f"status filter '{wanted_status}': {total_rows:,} -> {len(state_df):,}")

    if args.exclude_relisted:
        before = len(state_df)
        ever_relisted = relisted_urls(args.history_input)
        state_df = state_df[~state_df["url"].astype(str).str.strip().isin(ever_relisted)]
        print(
            f"excluding ever-relisted ({len(ever_relisted):,} urls): "
            f"{before:,} -> {len(state_df):,}"
        )

    if args.require_price and "last_price" in state_df.columns:
        before = len(state_df)
        prices = pd.to_numeric(state_df["last_price"], errors="coerce")
        state_df = state_df[prices.notna() & (prices > 0)]
        print(f"requiring a recorded price: {before:,} -> {len(state_df):,}")

    tagged_urls = None
    if args.tagged_only:
        tagged_urls = _tagged_url_set(args.tagged_input)
        if tagged_urls is None:
            print(f"ERROR: --tagged-only set but no usable tags in {args.tagged_input}")
            return 1

    exit_df = load_exit_state(args.exit_state)
    targets = select_listings_to_poll(
        state_df,
        exit_df,
        tagged_urls=tagged_urls,
        max_listings=args.max_listings,
        recheck_confirmed=args.recheck_confirmed,
        min_hours_between_polls=args.min_hours_between_polls,
    )

    print(f"listings in state    : {len(state_df):,}")
    print(f"already tracked      : {len(exit_df):,}")
    print(f"selected for polling : {len(targets):,}")
    if args.dry_run:
        for url in targets[:10]:
            print(f"  would poll: {absolute_listing_url(url)}")
        if len(targets) > 10:
            print(f"  ... and {len(targets) - 10:,} more")
        print("dry run - no requests made.")
        return 0
    if not targets:
        print("nothing to poll.")
        return 0

    price_by_url = {}
    if "last_price" in state_df.columns:
        price_by_url = dict(
            zip(state_df["url"].astype(str).str.strip(), state_df["last_price"])
        )

    existing = {str(r.get("url", "")).strip(): dict(r) for r in exit_df.to_dict("records")}
    poll_ts = datetime.now(UTC).isoformat(timespec="seconds")
    results: list[dict[str, Any]] = []

    worker_delay = max(0.0, args.delay)
    mode = args.fetch_mode

    if mode == "auto":
        # One cheap probe decides the mode for the whole run.
        try:
            trial = _probe_via_requests(targets[0], cookie_header, args.timeout)
            mode = "requests" if trial["status"] == 200 else "playwright"
            print(f"fetch mode   : {mode} (requests probe returned {trial['status']})")
        except Exception as exc:  # noqa: BLE001
            mode = "playwright"
            print(f"fetch mode   : playwright (requests probe failed: {type(exc).__name__})")
    else:
        print(f"fetch mode   : {mode}")

    counts = {VERDICT_LIVE: 0, VERDICT_GONE: 0, VERDICT_UNKNOWN: 0}
    newly_confirmed = 0
    persisted = 0

    def persist(batch: list[dict[str, Any]]) -> None:
        """Fold a batch into state and write it out. Safe to call repeatedly."""
        nonlocal newly_confirmed, persisted
        if not batch:
            return
        for result in batch:
            url = result["url"]
            counts[result["verdict"]] = counts.get(result["verdict"], 0) + 1
            row = existing.get(url) or blank_exit_state(url)
            was_confirmed = bool(str(row.get("confirmed_gone_date", "")).strip())
            row = update_exit_state(
                row,
                verdict=result["verdict"],
                reason=result["reason"],
                http_status=result["http_status"],
                poll_ts=poll_ts,
                confirm_threshold=args.confirm_threshold,
                known_price=price_by_url.get(url, ""),
            )
            if not was_confirmed and str(row.get("confirmed_gone_date", "")).strip():
                newly_confirmed += 1
            existing[url] = row

        append_exit_log([{"poll_ts": poll_ts, **r} for r in batch], args.exit_log)
        write_exit_state(existing, args.exit_state)
        persisted += len(batch)
        print(f"  checkpoint: {persisted:,}/{len(targets):,} persisted", flush=True)

    checkpoint_every = max(1, args.checkpoint_every)
    try:
        if mode == "requests":
            with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
                futures = [
                    pool.submit(
                        poll_one,
                        url,
                        cookie_header=cookie_header,
                        timeout=args.timeout,
                        gone_patterns=gone_patterns,
                        delay=worker_delay,
                    )
                    for url in targets
                ]
                batch: list[dict[str, Any]] = []
                for future in futures:
                    record = future.result()
                    results.append(record)
                    batch.append(record)
                    if len(batch) >= checkpoint_every:
                        persist(batch)
                        batch = []
                persist(batch)
        else:
            browser = _default_browser_name(args.playwright_browser)
            print(
                f"  browser={browser} headless={not args.playwright_headful} "
                f"concurrency={args.concurrency} checkpoint_every={checkpoint_every}"
            )
            results = _run_async(
                _poll_urls_playwright(
                    targets,
                    storage_state=args.storage_state,
                    cookie_header=cookie_header,
                    timeout=args.timeout,
                    gone_patterns=gone_patterns,
                    browser_name=browser,
                    headless=not args.playwright_headful,
                    block_resources=args.playwright_block_resources,
                    concurrency=args.concurrency,
                    delay=worker_delay,
                    on_checkpoint=persist,
                    checkpoint_every=checkpoint_every,
                )
            )
    except KeyboardInterrupt:
        print(f"\ninterrupted - {persisted:,} results already persisted, rerun to continue")
        return 130

    total = max(1, persisted)
    print(f"\nlive    : {counts[VERDICT_LIVE]:,} ({counts[VERDICT_LIVE]/total*100:.1f}%)")
    print(f"gone    : {counts[VERDICT_GONE]:,} ({counts[VERDICT_GONE]/total*100:.1f}%)")
    print(f"unknown : {counts[VERDICT_UNKNOWN]:,} ({counts[VERDICT_UNKNOWN]/total*100:.1f}%)")
    print(f"newly confirmed exits: {newly_confirmed:,} (threshold {args.confirm_threshold})")
    print(f"\nstate -> {args.exit_state}")
    print(f"log   -> {args.exit_log}")

    if counts[VERDICT_UNKNOWN] > total * 0.5:
        print(
            "\nWARNING: over half of polls were indeterminate. Check auth (--cookie-file) "
            "and calibrate patterns with --probe before trusting this data."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
