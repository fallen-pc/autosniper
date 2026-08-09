# AI Analysis and Missed Opportunities economic alignment - 2026-08-03

- `shared/decision_economics.py` is the single contract for the auction-site proxy max, current-price profit, downside profit, repair-adjusted max profit, and curve verdict used by AI Analysis and Missed Opportunities.
- The proxy max is solved from the downside resale value, normal purchase/ownership costs, high repair allowance, and required minimum profit. Expected auction finish and sold-comps median are win-likelihood context and must not cap this economic ceiling.
- Missed Opportunities must pass the sold price as the observed/current price and must use downside profit, not resale-mid profit, as the shared action-policy current-profit input.
- Do not restore either retired independent cap: AI Analysis's `expected_auction_price - minimum_profit` cap or Missed Opportunities' `75% of resale - minimum_profit` cap.
- Regression coverage includes a cross-surface vehicle test. A full replay against the 2026-08-02 VPS datasets checked 1,581 covered historical vehicles and produced zero mismatches for proxy max, current downside profit, hard-max safety, or final action.
- Expected-finish values can still differ as informational context: live AI Analysis may use CatBoost, while historical Missed Opportunities uses contemporaneous sold-comps context. That difference must not alter the shared economic max or Buy/Avoid/Review action.
- This change is verified locally but is not production-deployed until the corrected source is intentionally committed and published to the VPS.
