---
name: comps-gate-logic-change
description: "Changed comps gate from hard block to informational warnings"
metadata:
  type: project
  date: 2026-07-18
  status: implemented
---

# Comps Gate Logic Change

## Problem with Original Design

The comps gate had a **hard MIN_COMPS_FOR_BUY = 3 threshold** that:
- Blocked BUY decisions if comps_count < 3
- Forced profitable deals to WATCH status
- Contradicted the actual risk model: **bid cap (from resale value) protects profit**, not comps

## Key Insight

- **Curves** = resale value (private market) → sets bid cap  
- **Comps** = historical auction prices → indicates what auction might finish at (confidence)
- These are **independent signals**; comps don't validate curve
- If bid cap (from curve + downside buffer) protects resale profit, comps count shouldn't block BUY

## Implementation

### Code Changes
1. **shared/decision_policy.py**
   - Removed `MIN_COMPS_FOR_BUY = 3` constant
   - Removed `thin_comps` hard gate from `derive_action_label()`
   - Comps now **informational only** (no BUY blocking)
   - Updated comment on DecisionPolicyInput.comps_count

2. **scripts/ai_listing_valuation.py**
   - Added risk flags for comps-related warnings:
     - `NO_COMPS`: when comps_count = 0 or None
     - `BIDS_ABOVE_COMPS`: when recommended_max_bid > comps_median (by >5% tolerance)
   - Warnings are **informational**, not blocking

## Result

✅ BUY decisions now based on: profit, bid room, safety (via bid cap)  
✅ Comps data now shows confidence in where auction might finish  
✅ No_COMPS warning when flying blind on auction prices  
✅ BIDS_ABOVE_COMPS warning when bidding above historical results  
✅ Operator sees risks but retains final decision authority

## Expected Impact

The audit showed 28 WATCH rows blocked only by comps gate:
- All 28 were otherwise profitable
- All had positive profit at actual sold price
- Many will now be BUY eligible (if other conditions met)

## Next Steps

- Monitor early results for any auction price surprises
- Adjust BIDS_ABOVE_COMPS tolerance (currently 5%) if needed
- Ensure operators understand comps warnings are informational
