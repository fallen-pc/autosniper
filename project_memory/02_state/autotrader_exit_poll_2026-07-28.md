# Autotrader exit polling — July 28, 2026

## Why this was built

Validation of the buying system is blocked: `CSV_data/model_audit/scored_listings_enriched.csv`
has 23,179 predicted rows and **zero** populated `actual_profit` values, because no cars have
been bought yet. The plan is to use Autotrader retail listing exits as a resale proxy so the
system can be validated without committing capital.

That plan requires a trustworthy "this listing left the market" signal. The existing one is not.

## What was wrong with the existing signal

`scrape_first_page.py` sets `status="sold"` when a listing is absent from the current scrape
(`mark_sold` block, ~line 1296). Absence is produced by scrape scope changes, pagination and
sort-order churn — not only by real market exits.

Measured from `listing_history.csv`:

- **47.6%** of all `sold` events (26,197 of 55,021) were later contradicted by a relist
- Jul 3–18: `sold` was **0 every single day** while 14–194 listings were added daily
- Jul 24: **13,123** marked sold in one run — the run where scrape coverage jumped from ~300 to ~5,400 URLs
- Jul 25: **6,921** of those relisted the next day
- Scrape coverage swings between 96 and 7,422 URLs per run; max gap between runs is 17 days
- Median "days on market" is **3.1 days**, implausible for a real used-car sale

Conclusion: the `sold` flag currently tracks scraper scope, not the market.

## What was added

`autotrader_isolated/poll_listing_status.py` — polls each listing's own URL and classifies the
response, so the signal does not depend on search scope at all.

Design rules:
- Only definitive evidence yields `gone` (404/410, redirect off the listing id, matched removal
  content). Timeouts, 403/429/5xx and indeterminate 200s are recorded `unknown` and retried.
- An exit needs `--confirm-threshold` consecutive gone verdicts (default 2), so one transient
  404 cannot retire a live listing.
- A later `live` verdict clears a prior confirmation and its captured exit price, so relisted
  vehicles correctly return to live.
- Writes **separate** files (`listing_exit_state.csv`, `listing_exit_log.csv`). The legacy
  `status` column is left untouched so the two signals stay distinguishable.

Wired into `run_daily_pipeline` via `_run_autotrader_exit_poll_if_enabled()`, **off by default**.

33 unit tests in `tests/test_poll_listing_status.py` cover the classifier, the state machine and
target selection. A bug was caught by them during development: the confirmed-exit filter in
`select_listings_to_poll` treated a `NaN` `confirmed_gone_date` as confirmed, which silently
excluded every never-polled listing.

## Environment flags

| flag | effect |
|---|---|
| `AUTOSNIPER_AUTOTRADER_EXIT_POLL` | `1` to enable in the daily pipeline (default off) |
| `AUTOSNIPER_AUTOTRADER_EXIT_POLL_CONCURRENCY` | parallel requests, default 4 |
| `AUTOSNIPER_AUTOTRADER_EXIT_POLL_DELAY` | per-worker pre-request delay, default 0.5s |
| `AUTOSNIPER_AUTOTRADER_EXIT_POLL_MAX` | cap listings per run, default uncapped |
| `AUTOSNIPER_AUTOTRADER_EXIT_POLL_TAGGED_ONLY` | restrict to curve-tagged lanes |

## NOT YET DONE — calibration is required before enabling

The removal-content patterns in `DEFAULT_GONE_PATTERNS` are **unverified guesses**. The exact
markup Autotrader serves for a withdrawn listing has not been observed. The primary signals
(404/410, redirect off listing id) need no calibration and should carry most cases, but the
patterns must be checked before the flag is turned on.

Calibrate with `--probe` against one known-live and one known-gone listing, then refine via
`--gone-patterns-file`. If over half of polls come back `unknown`, the run prints a warning —
that usually means auth is stale and `--cookie-file` is needed.

## Sizing

7,457 active listings; 6,595 at $10k+; 101 distinct curve tags in the tagged feed.
At concurrency 4 with a 0.5s delay, a full pass is roughly 30 minutes.

## Next steps

1. Calibrate the gone patterns with `--probe` (blocking — do this first)
2. Enable the flag and let clean exit data accumulate
3. Build the resale ledger: join confirmed exits to Grays sold rows by spec to produce
   simulated profit, then run `scripts/evaluate_buy_selection.py` against it
4. Remember exit price is an **asking** price, not a realised sale price — cars sell below
   asking by an amount that still needs calibrating. Design the validation to demand a wide
   margin so it stays robust to that error.

## Unrelated pre-existing failure

`tests/test_canonical_tagging_mitsubishi.py::test_assign_canonical_tag_accepts_mitsubishi_pajero_glx_nt_nw_diesel_auto_only`
fails in the working tree. Both that test and `config/allowed_variants.csv` are uncommitted
in-progress curve work; the Pajero NT-NW variant is not yet in the allowlist. Not related to
this change.
