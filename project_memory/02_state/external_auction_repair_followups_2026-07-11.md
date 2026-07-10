# External Auction Intake And Repair Follow-Ups - 2026-07-11

- Added the external auction intake source slice to the repo: `scripts/scrape_external_auction_sources.py` plus regression coverage in `tests/test_external_auction_sources.py`.
- The scraper normalizes Pickles, Manheim, and Slattery detail text into the existing active-detail schema, tags discovered links with canonical coverage, filters to saved curve tags, and writes ignored CSV evidence under `output/external_auction_scrape/`.
- Pickles condition-detail rows now feed repair notes cleanly enough for the shared repair engine to classify missing tyres/wheels, windscreen pitting, flat batteries, and mechanical hard-avoid wording.
- Added repair quote follow-up helpers in `shared/repair_pricing_schedule.py`; follow-ups skip requests that already need photos/inspection/tyre size or have already been followed up.
- Model Accuracy now counts only manually logged sale outcomes, not purchase-history rows, when reporting logged outcomes and hit accuracy.
- Verification before commit: `venv\Scripts\python.exe -m pytest tests/test_outcome_tracking.py tests/test_repair_pricing.py tests/test_repair_pricing_schedule.py tests/test_external_auction_sources.py -q` passed with `69 passed`.
