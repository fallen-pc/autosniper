# AI Analysis proxy bid accuracy - 2026-07-16

- Tightened AI Analysis around proxy-bid workflow: `recommended_max_bid` is now presented as the auction-site proxy max bid / ceiling, with card and Telegram wording changed from generic max-bid labels to proxy-max labels.
- Added repair-rule cache invalidation to the AI valuation hash so changes to `shared/repair_pricing.py` or `config/condition_dictionary_v2.yaml` force fresh valuation math instead of reusing stale repair/max-bid outputs.
- Added `Marginal (expected finish)` so rows whose proxy-max math is viable but expected-finish worst profit is weak no longer appear as ordinary `Conditional Flip` rows.
- Verification for this slice: `python -m py_compile pages/6_AI_ANALYSIS.py scripts/ai_listing_valuation.py shared/valuation_display.py shared/decision_policy.py` and `pytest tests/test_valuation_display.py tests/test_ai_listing_valuation.py tests/test_decision_policy.py -q`.
