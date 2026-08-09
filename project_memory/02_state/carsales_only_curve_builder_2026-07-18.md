---
name: carsales-only-curve-builder-fix
description: "Fixed curve builder to use Carsales-only evidence, not Autotrader fallback"
metadata:
  type: project
  date: 2026-07-18
  status: implemented
---

# Carsales-Only Curve Builder Fix

## Problem
The automatic curve proposer (`propose_curve_from_evidence()`) was hardcoded to use Autotrader market data. While the existing curves.csv was 99% Carsales-led (per config), the **proposer could silently corrupt curves** if someone:
1. Opened Curve Builder V2
2. Clicked "Propose deterministic"
3. Saved the result

The proposer would build a curve from Autotrader prices, overwriting the correct Carsales-based curve with incorrect Autotrader estimates.

## Root Cause
- `propose_curve_from_evidence()` accepted only `active_market_df` parameter (no source hint)
- Page 15 loaded both Autotrader and Carsales data but always passed Autotrader to proposer
- No warning when Carsales data was unavailable

## Solution Implemented

### Code Changes
1. **scripts/process_curve_candidates.py**
   - Added `load_carsales_apify_market()`: loads CSV_data/quality/carsales_apify_listings.csv, tags via canonical tagging, normalizes to year/price/km numeric columns

2. **shared/curve_builder_v2.py**
   - Made `propose_curve_from_evidence()` data-source agnostic via `evidence_source` parameter
   - Updated proposal metadata notes to reflect the source

3. **pages/15_CURVE_BUILDER_V2.py** (major UI/UX update)
   - Load Carsales Apify data on startup (cached like Autotrader was)
   - Merge manual Carsales + Apify Carsales for proposer input
   - **Only show proposer button when BOTH manual and Apify Carsales are empty** — if any Carsales exists, user must edit manually
   - Pass merged Carsales data to proposer (not Autotrader)
   - Updated all UI labels: "Carsales (Primary)", "Autotrader (Comparison Only)"
   - Add warning when no Carsales data found: "The proposer requires Carsales data. Autotrader is NOT used as fallback."
   - Evidence tabs reordered: Sold → Carsales → Autotrader (comparison only)

### Tests
- Added 2 new tests in test_curve_builder_v2.py asserting `evidence_source` parameter and Carsales in metadata notes

## Initial Implementation Issue
Initial commit had inverted logic bug: proposer was shown only when Carsales 
was ABSENT. This made the Carsales proposer mostly unusable (would pass empty 
dataframe to proposer and fail).

## Fixed (2026-07-18, second commit)
- Inverted proposer visibility logic: now shown when Carsales IS present
- Disabled with clear warning when Carsales is absent
- Cleaned mojibake characters (⚠️ → [WARNING], em-dash → ASCII --)
- All tests pass; proposer now functional

## Result
✅ Curves can only be built from Carsales evidence (manual + Apify)
✅ Proposer is functional when Carsales data exists
✅ Proposer is disabled with clear messaging when Carsales is absent
✅ Autotrader remains visible for validation/confidence only
✅ No silent fallback; no Autotrader fallback possible
✅ UI clearly distinguishes primary (Carsales) vs. support (Autotrader)

## Next Steps
- Backfill any curves that were accidentally corrupted by Autotrader proposals (check git history for proposals > July 2026 without manual evidence)
- Monitor Page 15 for edge cases in proposer behavior
