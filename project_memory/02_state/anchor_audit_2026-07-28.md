# Auction anchor audit — July 28, 2026

## Summary
Ran a comprehensive test of whether the curve-at-odometer anchor (retail Carsales/Apify prices) beats the status-quo flat-median Grays close price. Test spanned three independent implementations with different methodological priorities, adversarial attacks on the result, and final decision.

**Verdict:** Keep status quo, fix self-inclusion leak, accept that $15k+ band is untestable.

## Key findings

### Self-inclusion bug (correctness issue, independent of curves)
- **Shipped baseline includes the row being scored** in its own median calculation
- Inflates apparent accuracy by ~2.0 WAPE points (replicated 3 times)
- Status quo accuracy is actually 34.3% WAPE not 36.4% when scored honestly
- **Fix:** Restrict baseline pool to train-only period (before 2025-12-17 cutoff)
- **Applied:** build_aligned_training_table.py now has --train-cutoff-date flag; rebuilt training table with 3,076 rows vs original 3,109

### Curve-at-odometer anchor result
- **Overall:** Wins by ~2.1 WAPE (A5 32.3% vs A2 34.4%)
- **But:** Only on hindsight. On frozen-corpus forward tests, curve ties or loses.
- **15k+ band:** Curve WORSE by 2.6 WAPE (26.4% vs 18.9%), n=21-28 (too small to conclude)
- **Coverage:** 80.5% of rows (one in five have year outside curve anchors)
- **Retail/auction gap:** Raw curve is 2x too high; train-fitted scale factor 0.50-0.51

### CatBoost auction model
- **Usage:** Called on 23.1% of live rows (48 of 208)
- **Impact:** Flips 0 decision labels at ±10%, only 5 of 44 at -25%
- **Verdict:** Inert. Can delete or keep; doesn't change outcomes.
- **Root cause:** 29 of 44 live rows already hard-Avoid from repair assessment; decision doesn't reach price anchor.

## What's staying as-is
- Status quo flat-median anchor
- CatBoost model (inert but harmless)
- MIN_COMPS_FOR_BUY = 3 gate (not a driver of decisions)

## What's changed
- `scripts/build_aligned_training_table.py`: added --train-cutoff-date parameter
- Rebuilt training table with honest baseline (train-only pool)

## Next steps (deferred)
1. **Freeze curves.csv** with a commit hash, then pre-register forward-only tests (the current curves were edited after seeing the outcome rows)
2. **Power analysis:** 15k+ band needs ~269 rows at 80% power; current is 23/month → 22-month wait to get meaningful signal
3. **Architectural reconsider:** _discounted_bid_cap binds in 42/54 rows while _solve_max_bid sits slack; decision logic may be inverted
4. **Repair assessment:** Priority — it zeros 29 of 44 live rows and decides two-thirds of Avoids before any price anchor is read
5. **Price data quality:** Investigate repeat VINs closing at $6k then $1k with same odometer (is "price" always a true close?)

## Technical notes
- Split date: 2025-12-17 (3,207 train / 910 eval rows in this analysis)
- Test coverage: 731 common eval rows (all six anchors available)
- Bootstrap: 4,000 resamples for paired tests
- Time-based split to prevent information leakage
