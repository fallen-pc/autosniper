# Why the policy says Buy to 2% — counterfactual results, August 16, 2026

## A hypothesis that was tested and refuted

After finding 594 of 989 replayed rows with `max_bid = $0`, and that 271 rows carried a flat
$10,000 repair charge from `HARD_AVOID_BUCKETS["mechanical"]`, the working theory was that
over-triggered repair hard-avoids were suppressing Buy decisions.

77% of those $10,000 charges do come from dashboard warning lights or boilerplate:

    78  \bengine noise\b            71  \bengine light\b
    17  \bother warning light on\b  14  \bairbag light on\b
     9  \bengine idling rough\b      9  \btraction control light on\b
     7  \babs light on\b             3  \bcheck engine\b

`engine noise` and `engine idling rough` (87 rows) are the exact strings
`build_aligned_training_table.py` discards as boilerplate via `ENGINE_DEFECT_PATTERN`. The same
text is filtered as noise in training and priced as a $10,000 catastrophe in decisions.

**But removing all 11 warning-light patterns changed Buy decisions by exactly zero.**

| | baseline | patched | delta |
|---|---|---|---|
| repair_cost == $10,000 | 271 | 198 | −73 |
| max_bid == 0 | 594 | 557 | −37 |
| median repair | $1,350 | $934 | −$416 |
| **Buy** | **20** | **20** | **0** |
| rows that became Buy | — | — | **0** |

Repair over-pricing is real but it is not the binding constraint. The hypothesis was wrong.

## The actual chain

| | rows | |
|---|---|---|
| max_bid = 0 | 594 | refuses to bid |
| max_bid > 0 but <= sold price | 287 | **would have been outbid** |
| max_bid > sold price | 108 | could have won |

Of the 108 winnable rows: **Buy 20, Review 65, Avoid 23**.

### Constraint 1 — outbid on 287 rows (NOT resolvable from this data)

`curve_resale / retail_estimate` has median **0.85**; the curve sits below observed retail on
**83%** of rows (median $9,979 vs $11,490). Since `max_bid = resale − costs − margin`, a
resale estimate 15% low feeds straight through to a bid ceiling below market.

**This cannot be called an error.** `retail_estimate` is a median of ASKING prices, and the
asking-to-sale gap is not measured here — only the ~3.7% public price cut before exit is
visible. A curve 15% below asking may be correctly estimating realised sale price. Distinguishing
"curves are conservative" from "15% is the asking-to-sale gap" needs real sale data, which does
not exist yet.

### Constraint 2 — 65 winnable rows blocked on repair EVIDENCE (resolvable)

Of the 108 winnable rows, 65 go to Review:

    computed_verdict   Review (repair pricing evidence)  59
                       Review (unresolved repairs)        6
    bid_status         Cheap 38   Near ceiling 19   At ceiling 8
    hard_max_safety    Conditional 62   Strong 3
    profitable on independent retail evidence:  65 of 65

All 65 were profitable. 38 were **Cheap** — sold well under the system's own max bid. They are
not blocked by economics or by repair cost; they are blocked because the repair text could not be
confidently priced.

`CSV_data/reports/repair_review_live_queue.csv` holds **292 unreviewed items** against 3,152
decisions already made. That backlog is directly converting winnable, profitable, cheap cars into
Review.

## What to do

1. **Work the 292-item repair review queue.** No change to money logic, no judgement call about
   conservatism — it converts Review into a decision on cars the system already agrees are cheap
   and winnable. Highest value, lowest risk action available.
2. **Do not relax the repair hard-avoids** on the strength of the $10,000 finding alone. It is
   a genuine inconsistency worth fixing for correctness, but the counterfactual shows it buys
   zero additional Buys today.
3. **Leave the curve conservatism alone** until realised sale prices exist. Acting on the 15%
   gap would mean bidding higher on the strength of asking-price evidence.

## Methodological caveat on the counterfactual

`simulated_profit` subtracts `total_costs`, which includes the repair estimate. So changing
repair pricing moves both the decision and the outcome, which is why "profitable" rose from 634
to 690 in the patched run and recall drifted 3.2% -> 2.9%. The Buy count is unaffected by this
coupling and is the number the conclusion rests on.

`shared/repair_pricing.py` was NOT modified. The counterfactual patched `MECH_AVOID_RE` in
memory only.
