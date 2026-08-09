# Retail Lifecycle Confidence Signal

Date: 2026-07-18

AI Analysis now keeps Carsales curve resale as the pricing source while using Autotrader lifecycle data as a confidence layer.

Implementation notes:
- `pages/6_AI_ANALYSIS.py` merges Autotrader `listing_state.csv` lifecycle columns into recent-market matches.
- Matched Autotrader rows now carry `status`, `first_seen`, `last_seen`, `last_price_date`, and `sold_date` into the curve confirmation view.
- Near-curve matched listings removed quickly are treated as a retail liquidity signal, not guaranteed proof of sale.
- Multiple stale near-curve active listings add a warning signal because they imply the curve may be high or the market may be slow.
- `scripts/ai_listing_valuation.py` keeps the Carsales curve resale value for sale-cost, profit, and proxy-max-bid calculations.
- Autotrader mismatch and lifecycle signals affect confidence notes/risk flags only; they do not overwrite curve prices.

Current thresholds:
- `AUTOTRADER_CURVE_WARNING_THRESHOLD = 0.10`
- `FAST_MARKET_CLEAR_DAYS = 5`
- `FAST_MARKET_CLEAR_MIN_COUNT = 2`
- `STALE_MARKET_DAYS = 30`
- `STALE_MARKET_MIN_COUNT = 3`
- Fast near-curve removals boost confidence by `0.08`.
- Stale near-curve active listings reduce confidence by `0.08` and add `STALE_RETAIL_MARKET`.

Verification:
- `venv\Scripts\python.exe -m pytest tests\test_ai_listing_valuation.py tests\test_missed_opportunities.py tests\test_top_buy.py -q`
- `venv\Scripts\python.exe -m py_compile scripts\ai_listing_valuation.py pages\6_AI_ANALYSIS.py shared\top_buy.py`
