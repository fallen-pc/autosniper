# Autotrader Isolated First-Page Scraper

This folder is intentionally isolated from the rest of the codebase.
It does not import shared modules and merges new listings into existing CSVs by default (deduped).

## Run

```bash
python autotrader_isolated/scrape_first_page.py
```

If Autotrader blocks the request, export a browser cookie:

```bash
set AUTOTRADER_COOKIE=PEAKHOUR_VISIT=...; other_cookie=...
python autotrader_isolated/scrape_first_page.py
```

Or use a Playwright storage state (from a logged-in browser session):

```bash
set AUTOTRADER_STORAGE_STATE=C:\path\to\storage_state.json
python autotrader_isolated/scrape_first_page.py
```

If the cookie is large, store it in a file and pass --cookie-file:

```bash
python autotrader_isolated/scrape_first_page.py --cookie-file autotrader_isolated\output\autotrader_cookie.txt
```

Notes for cookie files:
- Paste only the raw cookie value (no leading "Cookie:" label).
- Keep it on a single line.

To create a storage state file:

```bash
python autotrader_isolated/create_storage_state.py --output autotrader_isolated/output/storage_state.json
set AUTOTRADER_STORAGE_STATE=autotrader_isolated\output\storage_state.json
python autotrader_isolated/scrape_first_page.py
```

If navigation errors (e.g. network changed) occur, retry with:

```bash
python autotrader_isolated/create_storage_state.py --browser chrome --wait load --timeout 120 --retries 5 --retry-delay 3
```

Override the search URL or output path:

```bash
python autotrader_isolated/scrape_first_page.py --url "https://www.autotrader.com.au/for-sale" --output autotrader_isolated/output/first_page_results.csv
```

By default, new listings are merged into the output file and duplicates are removed.
To overwrite an existing output file instead:

```bash
python autotrader_isolated/scrape_first_page.py --overwrite
```

If you want to see the Playwright fallback browser window:

```bash
python autotrader_isolated/scrape_first_page.py --playwright-headful --playwright-browser chrome
```

Scrape all result pages (with optional limit and delay):

```bash
python autotrader_isolated/scrape_first_page.py --all-pages --sleep-seconds 0.5
python autotrader_isolated/scrape_first_page.py --all-pages --max-pages 5
```

Resume a long --all-pages run (uses output + .resume.json by default):

```bash
python autotrader_isolated/scrape_first_page.py --all-pages --resume
```

Write checkpoints every 100 listings (default) or disable (checkpoints merge into the output file):

```bash
python autotrader_isolated/scrape_first_page.py --all-pages --checkpoint-every 100
python autotrader_isolated/scrape_first_page.py --all-pages --checkpoint-every 0
```
