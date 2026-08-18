# Attribution of the 594 zero-bid rows — August 19, 2026

## Method

Instrumented `calculate_curve_decision_economics` directly (not the two inner functions —
a first pass tracing `_solve_max_bid` and `apply_repairs_to_max_bid` separately produced 234
mismatches against the real output, because a fourth path applies after both of them). Traced
calls matched the real replay's `max_bid` column with **0 mismatches** across all 989 rows before
trusting the attribution below.

## Result: four distinct paths zero a bid, not one

| cause | rows | share |
|---|---|---|
| **D — `policy_blocked` (interstate)** | **415** | **69.9%** |
| B — `hard_avoid` (mechanical/structural) | 140 | 23.6% |
| C — repair deduction ate a positive solved bid | 39 | 6.6% |
| A — resale too thin even before repairs | 0 | 0% |

`calculate_curve_decision_economics` applies, in order: solve max_bid on resale_low ->
subtract repairs via `apply_repairs_to_max_bid` -> **then** force `proxy_max_bid = 0.0`
unconditionally if `policy_blocked or hard_avoid`. `policy_blocked` comes from
`_interstate_purchase_blocked(listing)`, which is invisible unless the outer function is traced.

## Root cause of path D

`AUTOSNIPER_ALLOW_INTERSTATE_BUYING` defaults to unset, and unset is in `_INTERSTATE_FALSE_TOKENS`,
so `INTERSTATE_BUYING_ALLOWED = False` by default. Any listing whose state differs from
`OPERATING_STATE` (default VIC) is blocked **unconditionally** — before economics, before repairs,
regardless of profit margin.

Of 989 replayed rows: VIC 556, WA 262, NSW 78, QLD 69, SA 24. **433 of 989 (43.8%) are outside
VIC**, and essentially all of them hit path D.

## VIC-only selection quality (the true addressable pool today)

| | blended (989) | VIC-only (556) |
|---|---|---|
| Buy | 79 | 79 |
| recall | 12.5% | **20.5%** |
| precision | 100.0% | 100.0% |
| max_bid == 0 | 60.1% | 30.2% |

The blended 12.5% recall understates how the policy performs on the population it actually
acts on. Mixing in 433 categorically-excluded interstate rows as false negatives was
misleading the headline number.

## Interstate counterfactual — REAL solver, not an approximation

A first attempt used a hand-rolled formula (sold_price - retail - flat transport) and produced
an implausible 98.6% "profitable" figure — a red flag, and it omitted repair costs entirely.
Discarded.

Redone by patching `_interstate_purchase_blocked` to always return `False` and re-running the
actual pipeline, so the existing state-aware transport lookup (`_estimate_transport_cost`,
already wired into `_estimate_costs`) and the real repair-cost deduction both apply exactly as
production would compute them.

| | interstate blocked (today) | interstate priced, not blocked |
|---|---|---|
| Buy | 79 | **129** |
| false positives | 0 | **0** |
| recall | 12.5% | **20.3%** |

**50 rows became Buy. All 50 (100%) were profitable on independent retail evidence.**
Median sold price $23,400, median simulated profit $11,224, median total_costs (transport
included) $4,875.

By state: WA 29, NSW 15, SA 4, QLD 2. WA dominates — also the state furthest away and hardest
to physically inspect before bidding.

## This is NOT the same kind of finding as the repair-pricing gap

The schedule gap was unambiguously a data-completeness bug — nothing about pricing a scratch on
an SUV was a deliberate choice. Blocking interstate purchases plausibly IS deliberate: buying a
car sight-unseen from Perth carries real risk a spreadsheet does not price — condition-report
reliability, no pre-purchase inspection, logistics coordination, longer settlement risk. No code
change was made here. This needs the operator's call, not mine.

## Open question for the operator

Does the $11,224 median profit and 100% hit-rate on this sample justify the operational risk of
buying unseen interstate, at least as a bounded experiment (e.g. NSW/SA/QLD first, WA held back
given distance)? Or is the current blanket block intentional and correct as-is?

## Not yet touched

Paths B (140, hard_avoid) and C (39, repair deduction) remain unexamined. B is a plausible next
target — same shape as the repair-schedule work, worth checking whether the mechanical
hard-avoid triggers on these 140 rows are proportionate the way the warning-light patterns
were not.
