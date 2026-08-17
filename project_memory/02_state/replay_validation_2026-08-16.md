# First real validation of the decision policy — August 16, 2026

## What was blocking this

No cars bought, so `actual_profit` is empty on all 23,179 rows of
`scored_listings_enriched.csv`. Worse, only **732** of those rows carry a verdict at all, and
those use a retired vocabulary — Trap / Bronze / Conditional Flip / Marginal (repairs) /
Strong Flip — not the current **Buy / Watch / Avoid / Review** policy. Scoring against that file
would have measured a system that no longer exists.

## How the circularity was avoided

The naive construction is worthless: if the decision and the outcome both use the same resale
estimate, the test re-derives its own rule and a broken resale model scores perfectly.

`scripts/build_replay_outcomes.py` feeds the two sides from independent sources:

| side | source |
|---|---|
| PREDICTION | curve resale via `interpolate_base_by_year` — what the live page had at decision time |
| OUTCOME | observed retail exit median, from listings whose removal was verified by direct URL poll |

Curves are hand-built from Carsales evidence; exits are scraped market observations. Genuinely
independent, so agreement is informative.

Retail matching is `+/-2 years`, `+/-30% odometer`, minimum 5 matches — a flat per-lane median
would price a 100k car off a 250k one.

## Result (989 replayed rows, 49 lanes with >=10 exit observations)

    action labels assigned by the CURRENT policy
      Avoid   904
      Review   65
      Buy      20

    selection quality at a $1,500 profit threshold
      would have bought    20
      actually profitable  634
      true positive        20
      false positive        0
      false negative      614
      precision          100.0%
      recall               3.2%

**The policy says Buy to 20 of 989 candidates.** Precision is perfect but meaningless at n=20 —
it is the trivially-safe subset. Recall of 3.2% is the finding.

## Root cause: repair pricing, not price anchoring

**594 of 989 rows (60%) get `max_bid = $0`** — the system refuses to bid at all, before any
price anchor matters.

| | n | median repair | p90 repair |
|---|---|---|---|
| max_bid = 0 | 594 | $2,250 | $10,000 |
| max_bid > 0 | 395 | $450 | $2,250 |

Signs the repair estimate is saturating rather than estimating:

* **271 rows (27%) have `repair_cost` of exactly $10,000** — a cap being hit, not a per-vehicle figure
* **260 rows have repair_cost >= the entire sold price**
* **192 rows have repair_cost >= 2x the sold price**
* zeroed rows have a median sold price of **$4,400**, against a $10,000 p90 repair estimate

Of the 594 zeroed rows, **273 looked profitable** on the independent retail evidence.

This confirms and quantifies the earlier live-data observation that 29 of 44 rows had
`recommended_max_bid = $0`, with 18 hard_avoid from `assess_repairs` and 11 zeroed by
`apply_repairs_to_max_bid`.

**The whole CatBoost / curve-anchor investigation was optimising the wrong term.** The auction
price anchor barely reaches the decision, because repairs have already zeroed the bid on most
candidates.

## Honest limits on these numbers

* `retail_estimate` is a median of **asking** prices. Reconditioning a Grays car to dealer-retail
  condition is real work that `assess_repairs` prices from stated defects only, so "634
  profitable" is certainly inflated. The recall figure overstates the miss.
* Even heavily discounted, 20 Buys from 989 candidates is extreme.
* Precision of 100% on n=20 carries no information.
* This measures **selection quality**, not realised profit.

## Bug found while building

`compute_decision_metrics` reads the close price from `price_numeric`, not `price`. Passing a
raw sold row leaves `sold_price` as None, which silently skips the entire cost and verdict block:
every row returned `Review` with `total_costs = 0`, and 230 of 231 looked profitable. A first
pass reported that as a result before the cause was found. Fixed by setting `price_numeric`
before the call.

## Next

1. **Audit repair pricing.** Specifically why 271 rows land on exactly $10,000 and why 192 exceed
   twice the purchase price. That single gate decides more than every anchor discussed this month.
2. Re-run this replay after any repair-pricing change — it is now a regression harness for the
   whole decision policy.
3. Only then revisit lane coverage. 520 rows were skipped for thin retail matches, and more
   lanes would widen the sample, but the repair gate dominates the outcome either way.
