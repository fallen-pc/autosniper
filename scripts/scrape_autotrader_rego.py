from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from playwright.sync_api import sync_playwright

from scripts.atomic_csv import write_dataframe_csv_atomic

OUTPUT_DIR = Path("autotrader_isolated/output")
LISTING_STATE = OUTPUT_DIR / "listing_state.csv"
STORAGE_STATE = OUTPUT_DIR / "storage_state.json"
PROGRESS_PATH = OUTPUT_DIR / "rego_scrape_progress.json"


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return f"https://www.autotrader.com.au/{url.lstrip('/')}"


def _extract_rego_expiry(html: str) -> Optional[str]:
    if not html:
        return None
    match = re.search(r"dataLayer\\.push\\((\\{.*?\\})\\);", html, flags=re.DOTALL)
    if not match:
        return None
    payload = match.group(1)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    rego = data.get("rego_expiry") or data.get("regoExpiry")
    if isinstance(rego, str) and rego.strip():
        return rego.strip()
    return None


def _scrape_rego_for_urls(urls: list[str], headless: bool, sleep_seconds: float) -> dict[str, str]:
    results: dict[str, str] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            storage_state=str(STORAGE_STATE) if STORAGE_STATE.exists() else None
        )
        page = context.new_page()
        for idx, url in enumerate(urls, start=1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3500)
                html = page.content()
                rego = _extract_rego_expiry(html)
                if rego:
                    results[url] = rego
                print(f"[{idx}/{len(urls)}] {url} -> {rego or 'N/A'}")
            except Exception as exc:
                print(f"[{idx}/{len(urls)}] {url} -> ERROR: {exc}")
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        context.close()
        browser.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape rego_expiry from Autotrader listing pages.")
    parser.add_argument("--model", default="corolla", help="Model substring to filter (default: corolla).")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of URLs (0 = all).")
    parser.add_argument("--headless", action="store_true", help="Run Playwright headless.")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep seconds between requests.")
    parser.add_argument("--resume", action="store_true", help="Resume from last progress file.")
    parser.add_argument("--max-per-run", type=int, default=30, help="Max URLs per run.")
    args = parser.parse_args()

    if not LISTING_STATE.exists():
        raise SystemExit(f"Missing {LISTING_STATE}")

    df = pd.read_csv(LISTING_STATE)
    model_mask = df["model"].astype(str).str.contains(args.model, case=False, na=False)
    rego_series = df.get("rego")
    rego_mask = rego_series.astype(str).str.strip().replace({"nan": "", "None": ""}) == ""
    target = df[model_mask & rego_mask].copy()
    if target.empty:
        print("No listings missing rego for that model.")
        return

    urls = target["url"].dropna().astype(str).tolist()
    urls = [_normalize_url(url) for url in urls if url]
    if args.resume and PROGRESS_PATH.exists():
        try:
            progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
            done = set(progress.get("completed", []))
            urls = [url for url in urls if url not in done]
            print(f"Resuming: {len(done)} already completed, {len(urls)} remaining.")
        except Exception:
            pass
    if args.limit and args.limit > 0:
        urls = urls[: args.limit]
    if args.max_per_run and args.max_per_run > 0:
        urls = urls[: args.max_per_run]

    print(f"Scraping rego for {len(urls)} listing(s).")
    results: dict[str, str] = {}
    completed: list[str] = []
    for url in urls:
        batch_results = _scrape_rego_for_urls([url], headless=args.headless, sleep_seconds=args.sleep)
        results.update(batch_results)
        completed.append(url)
        PROGRESS_PATH.write_text(
            json.dumps({"completed": completed}, indent=2), encoding="utf-8"
        )
    if not results:
        print("No rego values found.")
        return

    updated = df.copy()
    updated["url_norm"] = updated["url"].astype(str).apply(_normalize_url)
    updates = 0
    for url, rego in results.items():
        mask = updated["url_norm"] == url
        if mask.any():
            updated.loc[mask, "rego"] = rego
            updates += int(mask.sum())
    updated.drop(columns=["url_norm"], inplace=True)

    enriched_path = OUTPUT_DIR / "listing_state_rego_enriched.csv"
    write_dataframe_csv_atomic(updated, enriched_path, index=False)
    write_dataframe_csv_atomic(updated, LISTING_STATE, index=False)
    print(f"Updated rego for {updates} row(s).")
    print(f"Wrote {enriched_path}")


if __name__ == "__main__":
    main()
