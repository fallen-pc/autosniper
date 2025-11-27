"""Backfill legacy sold listings with up-to-date condition data."""

from __future__ import annotations

import argparse
import asyncio
import math
import shutil
from pathlib import Path
from typing import Iterable

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import DATA_DIR
    from scripts.extract_vehicle_details import process_links
else:  # pragma: no cover
    from shared.data_loader import DATA_DIR
    from scripts.extract_vehicle_details import process_links


LEGACY_DIR = DATA_DIR / "ai_analysis_ready"
SOLD_PATH = DATA_DIR / "sold_cars.csv"
DEFAULT_PATTERN = "soldcars*.csv"
BACKFILL_FIELDS = [
    "general_condition",
    "features_list",
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
]
PLACEHOLDER_VALUES = {"", "n/a", "na", "nan", "unknown", "none", "?"}


def chunked(seq: Iterable[str], size: int) -> Iterable[list[str]]:
    seq = list(seq)
    for start in range(0, len(seq), size):
        yield seq[start : start + size]


async def _scrape_batches(urls: list[str], batch_size: int) -> list[dict]:
    scraped: list[dict] = []
    for index, batch in enumerate(chunked(urls, batch_size), start=1):
        print(f"Scraping batch {index}/{math.ceil(len(urls) / batch_size)} ({len(batch)} URLs)...")
        batch_results = await process_links(batch)
        scraped.extend(batch_results)
    return scraped


def scrape_urls(urls: list[str], batch_size: int) -> list[dict]:
    if not urls:
        return []
    return asyncio.run(_scrape_batches(urls, batch_size))


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text == "" or text.lower() in PLACEHOLDER_VALUES


def _format_currency(value: object) -> str | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num):
        return None
    return f"${num:,.0f}"


def _load_legacy_sources(pattern: str) -> pd.DataFrame:
    files = sorted(LEGACY_DIR.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No legacy CSVs found under {LEGACY_DIR} matching '{pattern}'.")
    frames = []
    for file in files:
        frame = pd.read_csv(file)
        if "url" not in frame.columns:
            print(f"Skipping {file} (missing 'url' column).")
            continue
        frames.append(frame)
    if not frames:
        raise RuntimeError("Legacy CSVs were found but none contained a 'url' column.")
    legacy = pd.concat(frames, ignore_index=True)
    legacy["url"] = legacy["url"].astype(str).str.strip()
    legacy = legacy[legacy["url"].str.startswith("http", na=False)].copy()
    legacy = legacy.drop_duplicates(subset=["url"])
    legacy = legacy.rename(
        columns={
            "Body Type": "body_type",
            "No. of Seats": "no_of_seats",
            "Build Date": "build_date",
            "Compliance Date": "compliance_date",
            "VIN": "vin",
            "Registration No": "rego_no",
            "Registration State": "rego_state",
            "Registration Expiry Date": "rego_expiry",
            "No. of Plates": "no_of_plates",
            "No. of Cylinders": "no_of_cylinders",
            "Engine Capacity": "engine_capacity",
            "Fuel Type": "fuel_type",
            "Transmission": "transmission",
            "Indicated Odometer Reading": "odometer_reading",
            "Odometer Measurement": "odometer_unit",
            "Exterior Colour": "exterior_colour",
            "Interior Colour": "interior_colour",
            "Owners Manual": "owners_manual",
            "Service History": "service_history",
            "Engine Turns Over": "engine_turns_over",
            "Location": "location",
            "date": "time_remaining_or_date_sold",
        }
    )
    legacy["legacy_price_value"] = pd.to_numeric(legacy.get("price"), errors="coerce")
    legacy["legacy_bid_value"] = pd.to_numeric(legacy.get("bids"), errors="coerce").fillna(0).astype(int)
    return legacy


def _needs_backfill(row: pd.Series) -> bool:
    for field in BACKFILL_FIELDS:
        if field not in row or _is_missing(row[field]):
            return True
    return False


def _backup_file(path: Path) -> Path:
    backup = path.with_name(path.stem + ".pre_backfill" + path.suffix)
    shutil.copy2(path, backup)
    return backup


def update_sold_records(
    sold_df: pd.DataFrame,
    scraped: pd.DataFrame,
    legacy_lookup: dict[str, dict],
) -> tuple[int, int]:
    updated = 0
    appended = 0
    sold_df = sold_df.copy()
    index_by_url = {url: idx for idx, url in sold_df["url"].items()}
    for detail in scraped.to_dict(orient="records"):
        url = detail.get("url")
        if not url:
            continue
        legacy = legacy_lookup.get(url, {})
        if url in index_by_url:
            idx = index_by_url[url]
            for field in BACKFILL_FIELDS:
                new_value = detail.get(field)
                if _is_missing(new_value):
                    continue
                if _is_missing(sold_df.at[idx, field]):
                    sold_df.at[idx, field] = new_value
            if _is_missing(sold_df.at[idx, "price"]):
                price_text = _format_currency(legacy.get("legacy_price_value"))
                if price_text:
                    sold_df.at[idx, "price"] = price_text
                    sold_df.at[idx, "sale_price"] = price_text
            if _is_missing(sold_df.at[idx, "time_remaining_or_date_sold"]):
                sold_df.at[idx, "time_remaining_or_date_sold"] = legacy.get("time_remaining_or_date_sold")
            if _is_missing(sold_df.at[idx, "bids"]):
                bid_value = legacy.get("legacy_bid_value")
                if bid_value:
                    sold_df.at[idx, "bids"] = str(bid_value)
            updated += 1
        else:
            new_row = {column: None for column in sold_df.columns}
            for field in sold_df.columns:
                if field in detail and not _is_missing(detail[field]):
                    new_row[field] = detail[field]
            new_row["status"] = "sold"
            price_text = _format_currency(legacy.get("legacy_price_value"))
            if price_text:
                new_row["price"] = price_text
                new_row["sale_price"] = price_text
            new_row["time_remaining_or_date_sold"] = legacy.get("time_remaining_or_date_sold")
            bid_value = legacy.get("legacy_bid_value")
            if bid_value:
                new_row["bids"] = str(bid_value)
            sold_df = pd.concat([sold_df, pd.DataFrame([new_row])], ignore_index=True)
            appended += 1
    return sold_df, updated, appended


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill legacy sold listings with condition metadata.")
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"Glob pattern inside {LEGACY_DIR} for legacy CSVs (default: {DEFAULT_PATTERN}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=150,
        help="Number of URLs to scrape per Playwright batch.",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Scrape every legacy URL even if the sold record already has condition data.",
    )
    args = parser.parse_args()

    if not SOLD_PATH.exists():
        raise FileNotFoundError(f"Sold dataset not found at {SOLD_PATH}")

    legacy_df = _load_legacy_sources(args.pattern)
    sold_df = pd.read_csv(SOLD_PATH)

    urls = legacy_df["url"].dropna().drop_duplicates().tolist()
    sold_lookup = sold_df.set_index("url")

    def needs_scrape(url: str) -> bool:
        if args.force_all:
            return True
        if url not in sold_lookup.index:
            return True
        row = sold_lookup.loc[url]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return _needs_backfill(row)

    target_urls = [url for url in urls if needs_scrape(url)]
    if not target_urls:
        print("All legacy URLs already have condition data. Nothing to do.")
        return

    scraped_records = scrape_urls(target_urls, args.batch_size)
    if not scraped_records:
        print("No records were scraped; aborting without changes.")
        return

    scraped_df = pd.DataFrame(scraped_records)
    legacy_lookup = legacy_df.set_index("url").to_dict(orient="index")
    updated_df, updated, appended = update_sold_records(sold_df, scraped_df, legacy_lookup)

    backup_path = _backup_file(SOLD_PATH)
    updated_df.to_csv(SOLD_PATH, index=False)
    print(f"Sold records updated ({updated} patched, {appended} appended).")
    print(f"Backup created at {backup_path}")


if __name__ == "__main__":
    main()

