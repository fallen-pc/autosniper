"""Rebuild the sold listings dataset by re-scraping legacy URLs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Iterable, List, Tuple

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
    from shared.schema import SOLD_LISTING_SCHEMA, SOLD_RAW_SCRAPE_COLUMNS
    from shared.sold_cleaning import (
        drop_invalid_odometer_rows,
        drop_invalid_years,
        drop_sparse_rows,
        ensure_schema,
    )
    from scripts.extract_vehicle_details import process_links
else:  # pragma: no cover
    from scripts.atomic_csv import write_dataframe_csv_atomic
    from shared.data_loader import dataset_path
    from shared.schema import SOLD_LISTING_SCHEMA, SOLD_RAW_SCRAPE_COLUMNS
    from shared.sold_cleaning import (
        drop_invalid_odometer_rows,
        drop_invalid_years,
        drop_sparse_rows,
        ensure_schema,
    )
    from scripts.extract_vehicle_details import process_links

SCHEMA_FIELDS = SOLD_RAW_SCRAPE_COLUMNS


ROOT_DIR = Path(__file__).resolve().parent.parent
SCRAPE_RULES_PATH = ROOT_DIR / "config" / "scrape_rules.json"
DATE_RE = re.compile(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})")
DEFAULT_SOURCE = dataset_path("sold_cars.csv")
DEFAULT_OUTPUT = dataset_path("sold_cars_rescraped.csv")
MOTORBIKE_KEYWORDS = (
    "motorbike",
    "motor bike",
    "motorcycle",
    "motor cycle",
    "scooter",
    "vespa",
    "harley",
)
BODY_KEYWORD_ALIASES = {
    "hatch": ["hatch", "hatchback"],
    "hatchback": ["hatchback", "hatch"],
    "people mover": ["people mover", "people-mover"],
    "crew cab chassis": ["crew cab chassis", "crew chassis", "crew cab"],
    "bus": ["bus"],
    "cab chassis": ["cab chassis", "cab-chassis", "chassis"],
    "dual cab": ["dual cab", "dual-cab", "dualcab", "dual"],
}
SPARSE_THRESHOLD = 6


def chunked(seq: List[str], size: int) -> Iterable[List[str]]:
    for start in range(0, len(seq), size):
        yield seq[start : start + size]


def looks_like_motorbike(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if not text:
        return False
    return any(keyword in text for keyword in MOTORBIKE_KEYWORDS)


def is_motorbike_row(payload: dict) -> bool:
    for field in ("body_type", "variant", "model", "make"):
        if looks_like_motorbike(payload.get(field)):
            return True
    return False


def has_wovr_flag(payload: dict) -> bool:
    targets = (
        "(wovr",
        "wovr-inspected",
        "wovr - inspected",
        "wovr-repairable",
        "wovr - repairable",
        "wovr - statutory",
        "wovr-statutory",
    )
    for value in payload.values():
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if any(target in lowered for target in targets):
            return True
    return False


def has_rwc_flag(payload: dict) -> bool:
    for value in payload.values():
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if "rwc issued" in lowered or "pinkslip" in lowered:
            return True
    return False


def has_complied_flag(payload: dict) -> bool:
    for value in payload.values():
        if isinstance(value, str) and "(complied" in value.lower():
            return True
    return False


def scrape_in_batches(urls: List[str], batch_size: int) -> Iterable[Tuple[List[dict], List[str], int]]:
    total = len(urls)
    for index, batch in enumerate(chunked(urls, batch_size), start=1):
        print(f"Scraping batch {index}/{(total + batch_size - 1) // batch_size} ({len(batch)} URLs)...")
        data, batch_skipped = process_links(batch)
        yield data, batch_skipped, index


def is_valid_odometer(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip()
    if not text:
        return False
    text_lower = text.lower()
    if (
        "unknown" in text_lower
        or "odometer discrepancy" in text_lower
        or "odometer descrepency" in text_lower
        or "discrepancy detected" in text_lower
    ):
        return False
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return True
    try:
        numeric = int(digits)
    except ValueError:
        return True
    return numeric > 0


def extract_year(value: object) -> int | None:
    if not value:
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    if match:
        try:
            return int(match.group(0))
        except ValueError:
            return None
    return None


def load_rules(config_path: Path = SCRAPE_RULES_PATH) -> dict:
    defaults = {"drop_slug_keywords": [], "require_fields": []}
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
            defaults.update(loaded)
    except FileNotFoundError:
        pass
    return defaults


def slug_matches_rule(url: str, keywords: list[str]) -> bool:
    if not url:
        return False
    slug = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return any(keyword in slug for keyword in keywords if keyword)


def normalize_body_and_variant(row: dict, keywords: list[str]) -> dict:
    body = str(row.get("body_type") or "").strip()
    variant = str(row.get("variant") or "")
    body_lower = body.lower()
    variant_lower = variant.lower()
    matched_keyword: str | None = None

    for keyword in keywords:
        if not keyword:
            continue
        if keyword in body_lower:
            matched_keyword = keyword
            break

    if not body:
        for keyword in keywords:
            if keyword and keyword in variant_lower:
                body = keyword.title()
                matched_keyword = keyword
                body_lower = body.lower()
                break

    if matched_keyword:
        alias_list = BODY_KEYWORD_ALIASES.get(matched_keyword, [matched_keyword])
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(alias) for alias in alias_list) + r")\b",
            re.IGNORECASE,
        )
        variant = pattern.sub("", variant).strip(" ,-/")
        variant = re.sub(r"\s{2,}", " ", variant)

    row["body_type"] = body
    row["variant"] = variant
    return row


def process_and_append_rows(
    rows: List[dict],
    required_fields: List[str],
    body_keywords: List[str],
    output_path: Path,
) -> int:
    sanitized_rows: List[dict] = []
    for row in rows:
        url = row.get("url")
        if not url:
            continue
        if is_motorbike_row(row):
            continue
        if has_wovr_flag(row):
            continue
        if has_rwc_flag(row):
            continue
        if has_complied_flag(row):
            continue
        sanitized_rows.append(row)

    if not sanitized_rows:
        return 0

    if required_fields:
        sanitized_rows = [
            row for row in sanitized_rows if all(str(row.get(field, "")).strip() for field in required_fields)
        ]
    sanitized_rows = [row for row in sanitized_rows if is_valid_odometer(row.get("odometer_reading"))]

    filtered_by_year: List[dict] = []
    for row in sanitized_rows:
        year_value = extract_year(row.get("year"))
        if year_value is not None and year_value <= 1990:
            continue
        filtered_by_year.append(row)
    sanitized_rows = filtered_by_year

    if body_keywords:
        sanitized_rows = [normalize_body_and_variant(row, body_keywords) for row in sanitized_rows]

    if not sanitized_rows:
        return 0

    scraped_df = pd.DataFrame(sanitized_rows)
    scraped_df = ensure_schema(scraped_df)
    scraped_df = drop_sparse_rows(scraped_df, SPARSE_THRESHOLD)
    scraped_df = drop_invalid_years(scraped_df)
    scraped_df = drop_invalid_odometer_rows(scraped_df)
    combined = scraped_df.drop_duplicates(subset=["url"]).reset_index(drop=True)

    if output_path.exists():
        existing = pd.read_csv(output_path, low_memory=False)
        for column in combined.columns:
            if column not in existing.columns:
                existing[column] = None
        existing = existing[combined.columns]
        combined = (
            pd.concat([existing, combined], ignore_index=True)
            .drop_duplicates(subset=["url"], keep="last")
            .reset_index(drop=True)
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(combined, output_path, index=False)
    return len(scraped_df)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the sold listings dataset via fresh scraping.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Existing sold CSV providing URLs.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination CSV for the re-scraped dataset.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max number of sold URLs to scrape this run (0 = all).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of URLs to process per batch (default 500).",
    )
    args = parser.parse_args()

    rules = load_rules()
    drop_slug_keywords = [kw.lower() for kw in rules.get("drop_slug_keywords", []) if kw]
    required_fields = [field for field in rules.get("require_fields", []) if field]
    body_keywords = [kw.lower() for kw in rules.get("body_keywords", []) if kw]

    if not args.source.exists():
        raise FileNotFoundError(f"Source dataset not found: {args.source}")

    sold_df = pd.read_csv(args.source, low_memory=False)
    if "url" not in sold_df.columns:
        raise RuntimeError("Source dataset must include a 'url' column.")

    sold_df["url"] = sold_df["url"].astype(str).str.strip()
    sold_df = sold_df[sold_df["url"].str.startswith("http", na=False)].copy()
    sold_df = sold_df.drop_duplicates(subset=["url"])

    def _non_motorbike(row: pd.Series) -> bool:
        return not any(
            looks_like_motorbike(row.get(field))
            for field in ("body_type", "variant", "model", "make")
        )

    filtered_df = sold_df[sold_df.apply(_non_motorbike, axis=1)].copy()
    if filtered_df.empty:
        print("No eligible sold URLs after filtering motorbikes.")
        return

    if drop_slug_keywords:
        filtered_df = filtered_df[
            ~filtered_df["url"].str.lower().apply(lambda u: slug_matches_rule(u, drop_slug_keywords))
        ].copy()
        if filtered_df.empty:
            print("No URLs remained after applying slug keyword rules.")
            return

    if args.limit and args.limit > 0:
        filtered_df = filtered_df.head(args.limit).copy()

    urls = filtered_df["url"].tolist()
    print(f"Preparing to scrape {len(urls)} sold listings.")

    total_added = 0
    all_skipped: List[str] = []
    for batch_rows, batch_skipped, batch_index in scrape_in_batches(urls, args.batch_size):
        added = process_and_append_rows(batch_rows, required_fields, body_keywords, args.output)
        total_added += added
        all_skipped.extend(batch_skipped)
        print(f"Batch {batch_index}: added {added} rows (running total {total_added}).")

    if total_added == 0:
        print("No listings scraped. Aborting without output.")
        return

    print(f"Finished scraping. {total_added} rows now stored in {args.output}.")
    if all_skipped:
        print(f"{len(all_skipped)} URLs skipped during scraping.")


if __name__ == "__main__":
    main()
