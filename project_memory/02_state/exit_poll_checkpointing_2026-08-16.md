# Exit poller checkpointing fix — August 16, 2026

## What happened

The full backfill (17,957 listings, ~4h) was launched in the background and was later stopped
before completing. It persisted **zero** results — `listing_exit_state.csv` was still at the
132 rows the earlier samples had produced.

## Why

`poll_listing_status.py` accumulated every result in memory and called `append_exit_log()` and
`write_exit_state()` exactly once, after the entire run finished. Any interruption — process
exit, kill, crash at hour 3.9 of 4 — discarded all of it. The design was all-or-nothing, which
is the wrong shape for a multi-hour job.

This was a flaw in the module as written, not an environment problem.

## Fix

Results are now folded into state and written **incrementally**:

- `--checkpoint-every N` (default 200) persists state + log every N results.
- `_poll_urls_playwright` takes an `on_checkpoint` callback and flushes as it goes, keeping the
  single browser context (no relaunch per batch).
- The flush is in a `finally`, so an interrupt or mid-run failure still persists completed work.
- `KeyboardInterrupt` reports how many results survived and exits 130.
- The requests path batches the same way.

## Why a rerun resumes correctly

`select_listings_to_poll` already skips listings polled within `--min-hours-between-polls`
(default 12) and drops confirmed exits. So each checkpointed batch shrinks the candidate set on
the next run — rerunning the same command continues rather than restarting. Three tests now
lock this in (`test_already_polled_listings_are_skipped_on_a_rerun`,
`test_partial_progress_narrows_the_remaining_work`,
`test_confirmed_exits_stay_excluded_across_reruns`).

## Verified

30-listing run with `--checkpoint-every 10` printed checkpoints at 10/20/30 and grew
`listing_exit_state.csv` from 132 to 162 rows. 60 tests passing.

## Running totals

- exit state rows: 162
- confirmed exits: 107
- gone rate on the sold-never-relisted backfill population holds around 67-74% across samples,
  i.e. roughly a quarter to a third of legacy `sold` flags are wrong even on the cleanest subset

## Note on the earlier date

The prior state files in this series are named `2026-07-28` from an earlier session; the actual
current date is 2026-08-16. Content in those files remains accurate.

## Next

Relaunch the backfill. It is resumable now, so it can be run in chunks with `--max-listings`
rather than as one long job:

    python autotrader_isolated/poll_listing_status.py --status sold --exclude-relisted \
      --require-price --concurrency 8 --delay 0.2 --confirm-threshold 1 \
      --checkpoint-every 200 --cookie-file autotrader_isolated/output/autotrader_cookie.txt

Then `python -m scripts.build_retail_exit_ledger --tagged-only --min-price 5000`.
