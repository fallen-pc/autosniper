# Model Proof policy resolution - 2026-07-03

## Status

- Retail-median Model Proof rows now expose current-policy action resolution separately from stored historical action labels.
- Missing policy inputs are shown as `Missing policy inputs` instead of being folded into a blank or fallback action label.
- Buy-selection evaluation now carries `expected_auction_comps_count` into shared policy resolution, so thin-comps rows do not evaluate from stale stored `Buy` labels.
- Buy-selection joins now preserve scored retail outcome policy fields with a `scored_` prefix, so Model Proof artifacts show both current valuation policy resolution and source-output policy provenance.

## Verification

- `venv\Scripts\python.exe -m pytest tests\test_generate_retail_median_outcomes.py tests\test_evaluate_buy_selection.py`
- Result: `16 passed`
- `venv\Scripts\python.exe -m pytest tests\test_generate_retail_median_outcomes.py tests\test_evaluate_buy_selection.py tests\test_decision_policy.py tests\test_ai_listing_valuation.py tests\test_missed_opportunities.py tests\test_valuation_display.py`
- Result after NaN fallback correction: `76 passed`
- `venv\Scripts\python.exe -m pytest tests\test_generate_retail_median_outcomes.py tests\test_evaluate_buy_selection.py`
- Result after scored-policy join wiring: `18 passed`
- `venv\Scripts\python.exe -m pytest tests\test_generate_retail_median_outcomes.py tests\test_evaluate_buy_selection.py tests\test_decision_policy.py tests\test_ai_listing_valuation.py tests\test_missed_opportunities.py tests\test_valuation_display.py`
- Result after scored-policy join wiring: `77 passed`
- Regenerated simulated retail-median proof: `179` rows, `26` with simulated profit, `23` profitable; profitable display split is `Avoid 19`, `Review 5`, `Watch 2`.
- Regenerated simulated buy-selection classification: `26` rows, `0` Buy predictions, `23` profitable actuals, `accuracy=0.1153846153846153`, with `unresolved_policy_rows=0`, `stored_action_fallback_rows=0`, `scored_unresolved_policy_rows=0`, and `scored_stored_action_fallback_rows=0`.
- Regenerated join file now includes `scored_action_label`, `scored_resolved_action_label`, `scored_action_label_display`, `scored_policy_resolution_status`, and `scored_missing_policy_inputs`; all `26` evaluated retail rows resolved under both current policy and scored-output policy.
