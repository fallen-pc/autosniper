# External-auction completeness contract - 2026-08-03

- Scheduled Pickles and Manheim collection must discover through natural pagination exhaustion and detail-scrape every curve-covered or ambiguous discovered lot. A page or detail safety ceiling is not proof of completeness.
- `external_auction_scrape_audit.csv` records pages planned/visited, exhaustion or cap state, blocked pages, discovered and selected totals, missing selected details, detail errors, and overall completeness. Scraper Operations must show incomplete/blocked runs as degraded or blocked rather than healthy.
- Manheim live proof: 15 of 40 interleaved Sydney/Melbourne list pages reached natural exhaustion; 269 unique lots were discovered, all 124 selected lots returned `parsed_http_200`, zero selected details were missing, and five rows matched saved curves.
- Pickles live proof reached natural pagination exhaustion after 80 of 100 safety pages with 2,239 unique detail URLs and 536 curve-covered or ambiguous lots selected. The exhaustive detail pass was still running when this note was first written and must be reconciled before audit closeout.
- The DigitalOcean VPS remains the production runtime. These changes must not be treated as deployed until the VPS deployed-commit marker changes through the guarded deployment workflow.
