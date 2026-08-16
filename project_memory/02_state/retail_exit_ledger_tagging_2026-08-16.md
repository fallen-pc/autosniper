# Retail exit ledger — tagging fix and corrected counts, August 16, 2026

## A reported figure was wrong by 22x

The ledger was first reported as **7,838 usable curve-tagged observations**. The true figure at
that point was **353**.

`--tagged-only` filtered with `curve_tag.astype(str).str.strip().ne("")`. A missing tag becomes
the string `"nan"`, and an unclassifiable vehicle is tagged `"UNCLASSIFIED"` — both are
non-empty, so both passed. Breakdown of the 7,838:

| | rows |
|---|---|
| `nan` (not in the tagged feed at all) | 3,649 |
| `UNCLASSIFIED` (in the feed, tagger could not classify) | 3,836 |
| **real curve_tag** | **353** |

Fixed with `is_real_tag()`, which rejects `""`, `nan`, `NaT`, `None` and `UNCLASSIFIED`
case-insensitively. Five tests lock it in.

## Root cause of the low coverage, and the fix

Tags were only ever joined from `autotrader_recent_market_tagged.csv`, which spans the recent
market window. Backfilled exits are mostly months old, so ~47% were absent from it entirely.

Those rows already carry year/make/model/variant/body/transmission/fuel — everything the tagger
needs. `_tag_from_spec()` now runs `tag_dataframe()` over the untagged remainder, recovering
**790** rows the join alone would have discarded. A `tag_source` column records `feed` vs `spec`.

## Corrected ledger (backfill 71% complete)

    1,138 curve-tagged observations
      >= $10k: 924
      >= $15k: 703
    141 distinct lanes
      91 lanes with >= 3 obs  (1,066 rows)
      58 lanes with >= 5 obs    (951 rows)
      34 lanes with >=10 obs    (786 rows)
    median final asking price $18,990
    236 cut price before exiting, median $1,000 / 3.6%

For context, the Grays-side anchor work had **23 rows** at $15k+ in total. This has **703**, and
91 lanes deep enough to support a per-lane retail median.

## `days_on_market` renamed to `days_visible_in_scrape`

It was derived from `first_seen`/`last_seen`, which record presence in the legacy scrape's
search results — that churns with scope and pagination. Observed median was ~4 days, impossible
for real used-car sales. The name now says what it measures. **Do not use it as time-to-sell.**

## Column trust levels

| column | trust | why |
|---|---|---|
| `final_asking_price` | good | from the listing record |
| `exit_confirmed_date`, `exit_reason` | good | direct URL poll, `removed=true` |
| `initial_asking_price`, `total_reduction`, `price_change_count` | good | directly observed price events |
| `curve_tag`, `tag_source` | good | now validated by `is_real_tag` |
| `days_visible_in_scrape` | **poor** | measures scrape presence, not market time |

Still true of every row: `final_asking_price` is an **asking** price. Not a sale price.

## Backfill status

12,762 of 17,957 polled (71%), 7,942 confirmed exits, 5,207 remaining. Verdict split across the
full run so far: gone 62.2%, live 35.2%, unknown 2.5%.

The 35.2% live rate is higher than the 26.2% seen in early samples — so on the cleanest subset,
better than a third of legacy `sold` flags are wrong.

Median 3,126 ms per poll, faster than the 6.6s sampled earlier; the remainder is roughly 35
minutes at concurrency 8.

## Next

1. Finish the backfill (rerun the same command; it resumes).
2. Rebuild the ledger — coverage grows with it.
3. Join to Grays sold rows on `curve_tag` to build simulated profit, then run
   `scripts/evaluate_buy_selection.py`. Restrict to the 91 lanes with >=3 observations.
4. Untouched problem: 3,836 rows are `UNCLASSIFIED` despite being in the tagged feed. That is a
   canonical-tagging coverage gap, likely the `allowed_variants` gate. Closing it would roughly
   quadruple usable observations.
