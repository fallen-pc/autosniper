# Autotrader daily validation - 2026-07-24

- Re-enabled the persistent Windows user flag `AUTOSNIPER_AUTOTRADER_SCRAPE_ENABLED=1`.
- Changed `autotrader_isolated/seed_urls.txt` from five make-specific searches to one complete Melbourne/VIC used-car scope. A single complete scope allows the scraper to mark disappeared listings safely; multi-seed runs intentionally suppress that transition.
- A full headful scrape completed successfully: 372 pages, 7,555 current listings, 3,370 newly tracked listings, 497 relisted listings, 1,510 price changes, and 8,832 delayed active-to-sold transitions.
- All 29 curve tags changed since the prior pause are inside the refreshed scrape scope. Twenty-three have recent matching Autotrader evidence; six had no matching market listing after the full scrape.
- Every newly delayed sold transition had a `sold_date - last_seen` gap above five days (range 5.38-47.67 days; median 31.65). These rows remain preserved in lifecycle state/history, but the resale validation excludes disappearance gaps above five days as incomplete outcomes.
- The clean validation retained 544 matched cars across 40 tags and produced a median final-advertised/curve-mid ratio of 1.079. This remains independent end-state evidence, not confirmed transaction-price evidence.
- Scheduled and manual Autotrader commands now block images/media/fonts to reduce full-scrape runtime. `tests/test_scheduled_jobs.py` passed 32 tests.
