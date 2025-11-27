# Autotrader Scraper (WIP)

This folder holds an experimental pipeline for scraping autotrader.com.au without disturbing the existing Grays integration. Nothing in here is imported by the live Streamlit app yet.

## Objectives
- Reproduce the end-to-end flow used for Grays: discover listings, capture detailed information, and store results in lightweight CSVs.
- Keep the new code isolated so it can be iterated on quickly and deleted easily if Autotrader blocks access.
- Once proven reliable, adapt the shared dashboards to accept Autotrader data (either merging or running in parallel tabs).

## Access Requirements

Autotrader is fronted by *Peakhour* and now blocks anonymous scraping with HTTP 403.
To run either script you must supply a real browser session:

- `AUTOTRADER_COOKIE`: paste the raw `Cookie:` header (e.g. `PEAKHOUR_VISIT=...; ...`)
- or `AUTOTRADER_STORAGE_STATE`: path to a Playwright `storage_state.json`

Both variables are read automatically when you execute the scripts.

## Proposed Flow
1. **Link extraction** (`extract_links.py`): hit the relevant Autotrader search endpoints, paginate through results, capture unique listing URLs, and write them to `autotrader/output/all_listing_links.csv`.
2. **Listing details scraper** (`scrape_details.py`): open each URL with Playwright (same async architecture as `scripts/update_bids.py`), extract price, seller info, odometer, etc., and update `autotrader/output/listing_details.csv`.
3. **Data review notebooks** (optional in `autotrader/notebooks/`): allow quick QA before wiring data into Streamlit.

## Rough API Surface
```python
# autotrader/extract_links.py
from autotrader.settings import SEARCH_BASE_URL

def crawl_autotrader_links(max_pages: int | None = None) -> pd.DataFrame:
    """Return a dataframe with one `url` column of unique vehicle listings."""
```

```python
# autotrader/scrape_details.py
async def refresh_autotrader_details(urls: Iterable[str] | None = None) -> pd.DataFrame:
    """Fetch details for the supplied URLs (or everything we know about) and persist them."""
```

## Next Steps
1. Implement `extract_links` to handle Autotrader pagination + filters.
2. Map HTML structure (or JSON payloads) for vehicle attributes and feed them into the detail scraper.
3. Build a converter that outputs normalized columns similar to `vehicle_static_details.csv`.
4. Only after validating data quality, expose the new dataset to Streamlit (likely via a separate page or a toggle).

Feel free to delete or restructure as the spike progresses—this is intentionally decoupled from production code.
