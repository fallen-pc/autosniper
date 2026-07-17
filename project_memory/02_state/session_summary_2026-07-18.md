---
name: session-summary-2026-07-18
description: "Session summary: curves fixed to use Carsales-only, comps gate removed, decision policy refactored"
metadata:
  type: project
  date: 2026-07-18
  status: complete
---

# Session Summary – 2026-07-18

## Major Architectural Changes

This session addressed three critical issues in the curve and decision policy architecture.

### 1. Curve Builder: Carsales-Only Enforcement

**Problem:** Automatic curve proposer defaulted to Autotrader data, risking silent corruption of Carsales-led curves (99/115 curves are Carsales-based per config).

**Solution Implemented:**
- Added `load_carsales_apify_market()` to load/normalize Carsales Apify listings
- Made `propose_curve_from_evidence()` data-source agnostic via `evidence_source` parameter
- Page 15 now:
  - Loads Carsales Apify data alongside manual evidence
  - Merges both sources for proposer input
  - Only shows proposer when Carsales data exists (else disabled with clear warning)
  - Labels Autotrader as "Comparison Only"
- Fixed UI mojibake characters (⚠️ → [WARNING], em-dashes → ASCII)
- Fixed inverted proposer button logic (was showing when Carsales was absent)

**Commits:**
- `0a6802f`: Fix curve builder to use Carsales-only (not Autotrader fallback)
- `1508386`: Fix inverted proposer logic and clean mojibake characters

**Result:** Curves can only be built from Carsales; Autotrader is comparison/confidence only.

### 2. Comps Gate: Hard Block → Informational Warnings

**Problem:** MIN_COMPS_FOR_BUY = 3 was a hard gate blocking 28 profitable WATCH rows. But it contradicted the risk model: bid cap (from resale value) protects profit, not comps count.

**Solution Implemented:**
- Removed `MIN_COMPS_FOR_BUY` constant entirely
- Removed `thin_comps` hard gate from `derive_action_label()`
- Comps now informational only; no impact on BUY vs WATCH
- Added risk flags for warnings:
  - `NO_COMPS`: when comps_count = 0 or None
  - `BIDS_ABOVE_COMPS`: when recommended_max_bid > comps_median

**Why This Works:**
- Curves → resale value → sets bid cap
- Comps → historical auction prices → shows where auction finishes (confidence)
- These are independent; comps don't validate curve
- Bid cap (from resale) already protects profit

**Commit:**
- `fa44ce7`: Remove hard comps gate; add informational comps warnings

**Result:** 
- BUY decisions now based on profit, bid room, safety (via bid cap)
- Operators see comps risks (warnings) but retain decision authority
- Audit's 28 blocked WATCH rows now BUY-eligible (if other conditions met)

### 3. Repair Pricing & Identification (Prior Session, Summary)

**Previous session fixes (commit 8e1b092):**
- Extended mechanical hard-avoid regex patterns (caught 19 missed rows)
- Fixed v2 dictionary false positives (warning_light, pillar_trim)
- Implemented schedule-driven cost overrides
- Hail damage bypasses caps (can reach ~$5k)
- All 92 repair tests pass

## Related Documentation

See state memory files for detailed technical context:
- `carsales_only_curve_builder_2026-07-18.md` — curve builder fix details
- `comps_gate_logic_change_2026-07-18.md` — comps gate refactoring details

## Testing

- ✅ All 57 decision policy + repair tests pass
- ✅ All 6 curve builder tests pass
- ✅ No regressions in valuation logic

## Next Steps

1. Monitor early auction results for comps warnings accuracy
2. Track whether removed comps gate affects deal quality (if any surprises)
3. Consider adjusting BIDS_ABOVE_COMPS tolerance (currently 5%) based on results
4. Ensure operators understand comps warnings are informational
