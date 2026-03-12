from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import is_compliance_slug
else:
    from shared.data_loader import dataset_path
    from shared.sold_cleaning import is_compliance_slug

BASE_URL = (
    "https://www.grays.com/search/automotive-trucks-and-marine/"
    "motor-vehiclesmotor-cycles/motor-vehicles"
)
OUTPUT_FILE = dataset_path("all_vehicle_links.csv")
ACTIVE_OUTPUT_FILE = dataset_path("active_vehicle_links.csv")
SUMMARY_FILE = Path("logs") / "link_scrape_summary.json"
SOLD_FILE = dataset_path("sold_cars.csv")
REFERRED_FILE = dataset_path("referred_cars.csv")

PROXY_BASE = "https://r.jina.ai/"
MAX_PAGES = 60
MAX_EMPTY_PAGES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

ABSOLUTE_LOT_PATTERN = re.compile(r"https://www\.grays\.com/lot/[^\s)\"'>]+", re.IGNORECASE)
RELATIVE_LOT_PATTERN = re.compile(r"/lot/[^\s)\"'>]+", re.IGNORECASE)


def _clean_url(url: str) -> str:
    cleaned = url.strip().rstrip(").,")
    return cleaned.split("?")[0] if cleaned.startswith("https://www.grays.com/lot/") else cleaned


def _normalize_url(url: str) -> str:
    return _clean_url(url).strip().lower()


def _load_existing_urls(paths: tuple[Path, ...]) -> set[str]:
    known: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path, usecols=["url"])
        except (ValueError, pd.errors.EmptyDataError):
            df = pd.read_csv(path) if path.exists() else pd.DataFrame()
        if "url" not in df.columns:
            continue
        urls = df["url"].dropna().astype(str).map(_normalize_url)
        known.update(url for url in urls if url)
    return known


def _load_pipeline_urls(path: Path) -> tuple[pd.DataFrame, set[str]]:
    if not path.exists():
        return pd.DataFrame(columns=["url", "discovered_at"]), set()
    try:
        df = pd.read_csv(path)
    except (ValueError, pd.errors.EmptyDataError):
        df = pd.read_csv(path) if path.exists() else pd.DataFrame()
    if "url" not in df.columns:
        return pd.DataFrame(columns=["url", "discovered_at"]), set()
    df = df.copy()
    df["url"] = df["url"].dropna().astype(str).map(_clean_url)
    df = df[df["url"].astype(str).str.strip().ne("")]
    if "discovered_at" not in df.columns:
        df["discovered_at"] = ""
    df["_url_norm"] = df["url"].astype(str).str.strip().str.lower()
    df = df.drop_duplicates(subset=["_url_norm"], keep="first")
    normalized = set(df["_url_norm"].dropna().tolist())
    df = df.drop(columns=["_url_norm"])
    return df.reset_index(drop=True), normalized


def _load_active_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        df = pd.read_csv(path, usecols=["url"])
    except (ValueError, pd.errors.EmptyDataError):
        df = pd.read_csv(path) if path.exists() else pd.DataFrame()
    if "url" not in df.columns:
        return set()
    urls = df["url"].dropna().astype(str).map(_normalize_url)
    return {url for url in urls if url}


def extract_links_from_content(content: str) -> list[str]:
    if not content:
        return []

    results: set[str] = set()
    is_html = "<html" in content.lower() and "</html>" in content.lower()

    if is_html:
        soup = BeautifulSoup(content, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            if not href:
                continue
            if href.startswith("/lot/"):
                results.add("https://www.grays.com" + href)
            elif href.startswith("https://www.grays.com/lot/"):
                results.add(href)
    else:
        for match in ABSOLUTE_LOT_PATTERN.findall(content):
            results.add(match)
        for match in RELATIVE_LOT_PATTERN.findall(content):
            results.add("https://www.grays.com" + match)

    return sorted({ _clean_url(url) for url in results if "/lot/" in url })


def fetch_page(session: requests.Session, url: str, *, force_proxy: bool = False) -> tuple[str | None, bool]:
    if force_proxy:
        return _fetch_via_proxy(session, url)

    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200 and "Request blocked." not in response.text:
            return response.text, False
        print(f"Direct fetch failed ({response.status_code}); falling back to proxy.")
    except requests.RequestException as exc:
        print(f"Direct fetch error: {exc}; trying proxy.")

    return _fetch_via_proxy(session, url)


def _fetch_via_proxy(session: requests.Session, url: str) -> tuple[str | None, bool]:
    proxied_url = f"{PROXY_BASE}{url}"
    try:
        response = session.get(proxied_url, timeout=30)
        if response.status_code == 200:
            return response.text, True
        print(f"Proxy fetch failed ({response.status_code}) for {url}")
    except requests.RequestException as exc:
        print(f"Proxy fetch error: {exc} for {url}")
    return None, False


def extract_all_vehicle_links() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)

    all_links: set[str] = set()
    page = 1
    empty_streak = 0

    while page <= MAX_PAGES:
        url = f"{BASE_URL}?tab=items&isdesktop=1&page={page}"
        print(f"Fetching: {url}")
        content, used_proxy = fetch_page(session, url)
        if not content:
            empty_streak += 1
            if empty_streak >= MAX_EMPTY_PAGES:
                print("Repeated failures; stopping crawler.")
                break
            page += 1
            continue

        links = extract_links_from_content(content)
        if not links and not used_proxy:
            proxy_content, proxy_used = fetch_page(session, url, force_proxy=True)
            if proxy_content:
                content = proxy_content
                used_proxy = proxy_used
                links = extract_links_from_content(content)

        new_links = [link for link in links if link not in all_links]
        if new_links:
            all_links.update(new_links)
            empty_streak = 0
            print(f"  Found {len(new_links)} new listings (total {len(all_links)}).")
        else:
            empty_streak += 1
            print("  No new listings found on this page.")
            if empty_streak >= MAX_EMPTY_PAGES:
                print("Reached consecutive empty pages; stopping.")
                break

        page += 1

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    pipeline_df, pipeline_norm = _load_pipeline_urls(OUTPUT_FILE)
    sold_referred_norm = _load_existing_urls((SOLD_FILE, REFERRED_FILE))

    skipped_existing = 0
    skipped_sold = 0
    skipped_compliance = 0
    skipped_excluded = 0
    new_links: list[str] = []
    discovered_at = datetime.utcnow().isoformat()
    for link in sorted(all_links):
        norm = _normalize_url(link)
        if not norm:
            continue
        if norm in pipeline_norm:
            skipped_existing += 1
            continue
        if norm in sold_referred_norm:
            skipped_sold += 1
            continue
        if is_compliance_slug(link):
            skipped_compliance += 1
            continue
        cleaned = _clean_url(link)
        new_links.append(cleaned)
        pipeline_norm.add(norm)

    if skipped_compliance:
        print(f"Dropped {skipped_compliance} compliance-tagged link(s).")

    new_links = sorted(new_links)
    if new_links:
        new_rows = pd.DataFrame(
            [{"url": link, "discovered_at": discovered_at} for link in new_links]
        )
        pipeline_df = pd.concat([pipeline_df, new_rows], ignore_index=True, sort=False)
    if "url" in pipeline_df.columns:
        pipeline_df["_url_norm"] = pipeline_df["url"].astype(str).str.strip().str.lower()
        pipeline_df = pipeline_df.drop_duplicates(subset=["_url_norm"], keep="first")
        pipeline_df = pipeline_df.drop(columns=["_url_norm"])
    pipeline_df = pipeline_df.reset_index(drop=True)
    pipeline_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(pipeline_df)} vehicle links to {OUTPUT_FILE} ({len(new_links)} new).")

    active_urls: set[str] = set()
    for link in sorted(all_links):
        norm = _normalize_url(link)
        if not norm:
            continue
        if norm in sold_referred_norm:
            continue
        if is_compliance_slug(link):
            continue
        active_urls.add(norm)
    active_df = pd.DataFrame(sorted(active_urls), columns=["url"])
    ACTIVE_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    active_df.to_csv(ACTIVE_OUTPUT_FILE, index=False)

    pipeline_before = len(pipeline_df) - len(new_links)
    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "total_links_found": len(all_links),
        "pipeline_before": pipeline_before if pipeline_before >= 0 else len(pipeline_df),
        "pipeline_after": len(pipeline_df),
        "new_added": len(new_links),
        "skipped_existing": skipped_existing,
        "skipped_sold": skipped_sold,
        "skipped_excluded": skipped_excluded,
        "active_links": len(active_df),
    }
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    extract_all_vehicle_links()


if __name__ == "__main__":
    main()
