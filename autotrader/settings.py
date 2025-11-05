"""
Configuration helpers for the experimental Autotrader scraper.
"""

from pathlib import Path

# Base search endpoint (update filters as we learn more about Autotrader's URL structure).
SEARCH_BASE_URL = "https://www.autotrader.com.au/cars"

# Output locations are kept inside the module so they never clash with production CSVs.
OUTPUT_DIR = Path("autotrader") / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ALL_LINKS_CSV = OUTPUT_DIR / "all_listing_links.csv"
DETAILS_CSV = OUTPUT_DIR / "listing_details.csv"
SKIPPED_LOG = OUTPUT_DIR / "skipped_links.log"
