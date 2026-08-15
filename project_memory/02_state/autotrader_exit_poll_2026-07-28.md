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

## Calibration — DONE 2026-07-28, verified against the live site

**Autotrader announces removal explicitly.** A listing removed back in January redirected to
`https://www.autotrader.com.au/for-sale?removed=true`, while a live listing stayed on its own
URL and returned its real title. That `removed=true` flag is the site's own signal and is now
the primary detector (`REMOVED_REDIRECT_MARKERS` -> reason `redirect_removed_flag`).

| probe | result |
|---|---|
| `car/14810075/toyota/landcruiser/...` (active) | `live` — title "2016 Toyota Landcruiser Sahara (4X4) for sale $63,777" |
| `car/14928703/toyota/corolla-cross-hybrid/...` (removed Jan) | `gone` — redirect to `/for-sale?removed=true` |

**`DEFAULT_GONE_PATTERNS` is now deliberately empty.** Both probes matched zero content
patterns, so the guesses earned nothing — while carrying real downside: a live page containing
"has been sold" in a recommendations module would have been classified gone, exactly the failure
this module exists to prevent. The mechanism stays available via `--gone-patterns-file` if a
soft-404 ever appears.

**Plain `requests` is not viable.** Autotrader 403s it regardless of cookie, matching what
`scrape_first_page.py` already worked around. The poller now tries requests once, then switches
the whole run to Playwright. Headless Chrome works here, so the scheduler's headful workaround
is not needed for polling.

## Measured throughput

7,457 active listings; 6,595 at $10k+; 101 distinct curve tags in the tagged feed.

Median **4.9s per listing** (Playwright, headless, resources blocked). Effective rate is that
divided by concurrency:

| concurrency | full 7,457 pass |
|---|---|
| 3 | ~3.3 hours |
| 8 | ~75 min |

A full daily pass is unnecessary. `--min-hours-between-polls` already spreads load, so cap the
batch instead — roughly 2,500/day at concurrency 8 (~25 min) polls every listing about every
three days, which is ample for detecting exits.

Verified end to end on a real 12-listing batch: all 12 classified `live`, state and log written
correctly, `poll_count` and streak counters advancing as designed.

## Next steps

1. ~~Calibrate the gone patterns~~ — DONE, see above. The detector is verified.
2. Enable `AUTOSNIPER_AUTOTRADER_EXIT_POLL=1` and let clean exit data accumulate.
   Suggested: `_CONCURRENCY=8`, `_MAX=2500`.
3. Build the resale ledger: join confirmed exits to Grays sold rows by spec to produce
   simulated profit, then run `scripts/evaluate_buy_selection.py` against it.
4. Remember exit price is an **asking** price, not a realised sale price — cars sell below
   asking by an amount that still needs calibrating. Design the validation to demand a wide
   margin so it stays robust to that error.
5. ~~Backfill opportunity~~ — BUILT, see below.

## Backfill — built and sampled 2026-07-28

`--status sold --exclude-relisted --require-price` selects past exits for retroactive
verification. Funnel: 36,281 state rows -> 28,824 sold -> 18,018 never relisted -> **17,957**
with a recorded price.

**Sample of 80 polled: 73.8% confirmed gone, 26.2% still LIVE.**

That is the headline number. Even on the *cleanest* subset — everything ever relisted already
excluded — better than one in four "sold" flags is simply wrong; the car is on Autotrader right
now. Combined with the 47.6% relist contradiction rate, the legacy flag is wrong most of the
time. Every confirmed exit came via `redirect_removed_flag`; zero ambiguous verdicts.

Extrapolating: roughly **13,000 verified exits** available from the backfill.

### Performance fix

With content patterns empty the verdict needs only status + redirect target, so navigation now
stops at `wait_until="commit"` and never serialises the page body. Median 11,245ms -> 6,622ms.
Verified safe: 40 URLs polled under both wait states produced **zero verdict changes**, proving
the `removed=true` redirect is a real HTTP redirect resolved before commit.

Full backfill: ~4 hours at concurrency 8 (was ~6.8).

## Retail exit ledger

`scripts/build_retail_exit_ledger.py` turns confirmed exits into resale observations: spec,
canonical/curve tag, days on market, initial and final asking price, total reduction, reduction
percentage, price-change count, exit reason.

From the 87-exit sample:

- median final asking price **$26,488**
- **69 rows at $15k+** — against only 23 rows in that band on the Grays side, which is why the
  earlier anchor work could not test the money band at all
- all 87 curve-tagged
- **34 of 87 (39%) cut price before exiting**, median $1,000 / 4.8%

That last figure is directly observed and is a partial calibration of the asking-vs-sale gap —
it captures what sellers conceded publicly, though not what buyers negotiated after.

**Column naming is deliberate.** `final_asking_price`, never `sale_price`. Do not rename it and
do not build a profit number treating it as a realised sale without a haircut.

A production bug was caught by the ledger tests: `frame.get(missing)` returns `None`, and
subtracting two of those raises rather than yielding NaT, so any state file lacking
`first_seen`/`last_seen` would have aborted the whole build.

## Unrelated pre-existing failure

`tests/test_canonical_tagging_mitsubishi.py::test_assign_canonical_tag_accepts_mitsubishi_pajero_glx_nt_nw_diesel_auto_only`
fails in the working tree. Both that test and `config/allowed_variants.csv` are uncommitted
in-progress curve work; the Pajero NT-NW variant is not yet in the allowlist. Not related to
this change.
