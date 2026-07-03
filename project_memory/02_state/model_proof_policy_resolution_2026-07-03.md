# Model Proof policy resolution - 2026-07-03

## Status

- Retail-median Model Proof rows now expose current-policy action resolution separately from stored historical action labels.
- Missing policy inputs are shown as `Missing policy inputs` instead of being folded into a blank or fallback action label.
- Buy-selection evaluation now carries `expected_auction_comps_count` into shared policy resolution, so thin-comps rows do not evaluate from stale stored `Buy` labels.

## Verification

- `venv\Scripts\python.exe -m pytest tests\test_generate_retail_median_outcomes.py tests\test_evaluate_buy_selection.py`
- Result: `16 passed`
- `venv\Scripts\python.exe -m pytest tests\test_generate_retail_median_outcomes.py tests\test_evaluate_buy_selection.py tests\test_decision_policy.py tests\test_ai_listing_valuation.py tests\test_missed_opportunities.py tests\test_valuation_display.py`
- Result: `75 passed`
- Regenerated simulated retail-median proof: `181` rows, `26` with simulated profit; profitable display split is `Missing policy inputs 11`, `Avoid 9`, `Review 4`, `Watch 2`.
- Regenerated simulated buy-selection classification: `26` rows, `0` Buy predictions, `26` profitable actuals, with `stored_action_fallback_rows=11`.
