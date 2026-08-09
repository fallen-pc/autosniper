---
date: 2026-06-30
topic: Retail-median simulated outcome pipeline built (Task #8 partial)
status: complete
---

New script `scripts/generate_retail_median_outcomes.py` produces simulated
resale profits for scored listings using current Autotrader/Carsales asking
prices as a proxy resale price, since no real trades have occurred yet.

**How it works:**
- Joins `ai_listing_valuations.csv` with `vehicle_static_details.csv` to get
  body/fuel/transmission/odometer for lane-key matching.
- Builds the same `lane_key` as `generate_opportunity_lanes.py` (make/model/
  variant_family/body/fuel/trans).
- Matches retail listings from `CSV_data/quality/carsales_apify_listings.csv`
  and `autotrader_isolated/output/autotrader_recent_market_tagged.csv` within
  ±2yr and ±25% or ±20,000km odometer tolerance.
- Requires ≥5 matches before trusting the median — thin samples dropped, not guessed.
- `simulated_profit = retail_median - buy_price_basis - fees - repair_estimate_high`

**Output:** `CSV_data/model_audit/simulated_retail_median_outcomes.csv`
**Evaluation:** run with `evaluate_buy_selection.py --scored ... --profit-column simulated_profit`
**UI:** `pages/17_MODEL_PROOF.py` has a new "Retail-Median Proxy Benchmark" section.

**Current results (2026-06-30):** 180 scored listings, 11 with retail matches.
Mostly "Avoid" verdicts showing positive simulated margin — model is currently
very conservative; no BUY verdicts exist yet to test precision.
