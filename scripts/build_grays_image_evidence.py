from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.extract_vehicle_details import REQUEST_DELAY, REQUEST_HEADERS, REQUEST_TIMEOUT, fetch_html
from shared.csv_utils import read_csv_or_empty
from shared.grays_image_evidence import (
    DEFAULT_IMAGE_CACHE_DIR,
    DEFAULT_INPUTS,
    DEFAULT_LINKS_OUTPUT,
    DEFAULT_MANIFEST_OUTPUT,
    DEFAULT_REPAIR_FRAGMENTS_PATH,
    IMAGE_MANIFEST_COLUMNS,
    build_manifest_rows,
    build_repair_image_links,
    download_manifest_images,
    extract_image_candidates,
    iter_listing_urls,
    merge_manifest,
    read_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a small Grays listing-image manifest and join it to extracted repair condition fragments. "
            "Outputs are generated evidence files; production scraping is not changed."
        )
    )
    parser.add_argument(
        "--input",
        action="append",
        dest="inputs",
        help="CSV containing a url column. Can be supplied multiple times. Defaults to active/static Grays datasets.",
    )
    parser.add_argument("--url", action="append", dest="urls", help="Specific Grays listing URL to inspect.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum listing pages to fetch when reading input CSVs.")
    parser.add_argument("--download", action="store_true", help="Download discovered images into the local cache.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarize but do not write output files.")
    parser.add_argument("--manifest-output", default=str(DEFAULT_MANIFEST_OUTPUT))
    parser.add_argument("--links-output", default=str(DEFAULT_LINKS_OUTPUT))
    parser.add_argument("--image-cache-dir", default=str(DEFAULT_IMAGE_CACHE_DIR))
    parser.add_argument("--repair-fragments", default=str(DEFAULT_REPAIR_FRAGMENTS_PATH))
    return parser.parse_args()


def _target_urls(args: argparse.Namespace) -> list[str]:
    explicit = [url.strip() for url in (args.urls or []) if url and url.strip()]
    if explicit:
        return explicit[: args.limit] if args.limit else explicit
    input_paths = [Path(path) for path in (args.inputs or DEFAULT_INPUTS)]
    return iter_listing_urls(input_paths, limit=args.limit)


def main() -> int:
    args = parse_args()
    urls = _target_urls(args)
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    rows: list[dict[str, object]] = []
    failed: list[str] = []
    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] {url}")
        html = fetch_html(session, url)
        if not html:
            failed.append(url)
            continue
        candidates = extract_image_candidates(html, url)
        print(f"  images discovered: {len(candidates)}")
        rows.extend(build_manifest_rows(url, candidates))
        time.sleep(REQUEST_DELAY)

    existing_manifest = read_manifest(Path(args.manifest_output))
    manifest = merge_manifest(existing_manifest, rows)
    if args.download and not manifest.empty:
        manifest = download_manifest_images(
            manifest,
            cache_dir=Path(args.image_cache_dir),
            session=session,
            timeout=REQUEST_TIMEOUT,
        )

    repair_fragments = read_csv_or_empty(Path(args.repair_fragments), dtype=str, keep_default_na=False)
    links = build_repair_image_links(manifest, repair_fragments)

    summary = {
        "urls_considered": len(urls),
        "urls_failed": len(failed),
        "images_discovered_this_run": len(rows),
        "manifest_rows": int(manifest.shape[0]),
        "downloaded_images": int((manifest.get("download_status", pd.Series(dtype=str)) == "downloaded").sum())
        if not manifest.empty
        else 0,
        "repair_image_links": int(links.shape[0]),
        "outputs": {
            "manifest": args.manifest_output,
            "repair_image_links": args.links_output,
            "image_cache_dir": args.image_cache_dir,
        },
        "failed_urls": failed,
    }

    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0

    manifest_path = Path(args.manifest_output)
    links_path = Path(args.links_output)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    links_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest.empty:
        pd.DataFrame(columns=IMAGE_MANIFEST_COLUMNS).to_csv(manifest_path, index=False)
    else:
        manifest.to_csv(manifest_path, index=False)
    links.to_csv(links_path, index=False)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
