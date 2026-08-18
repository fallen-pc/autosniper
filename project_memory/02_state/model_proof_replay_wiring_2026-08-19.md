# Model Proof wired to the replay; outcome_tracking traced — August 19, 2026

## What the trace found

`ops/outcome_tracking.py` reads `ai_listing_valuations.csv` as `PREDICTIONS_SOURCE` without
filtering `analysis_context`, and produces:

    scored_listings_enriched.csv   23,179 rows · 732 verdicts · 0 actual_profit
    model_accuracy_weekly.csv      HEADER ONLY, no data rows
    model_accuracy_by_tier.csv     HEADER ONLY, no data rows

**It is not producing wrong numbers - it is producing no numbers.** Accuracy needs
`actual_profit`, which is null on every row because no cars have been bought. The
`predicted_verdict` column it expects in `PREDICTED_COLUMNS` does not exist in the source file
at all.

So the stale-row contamination is real but currently inert: 146 of 231 rows in
`ai_listing_valuations.csv` are `sold_simulated` carrying the retired vocabulary (`Trap` 53,
`Conditional Flip` 28 unfiltered, dropping to 7 and 0 when restricted to `analysis_context ==
"active"`), but they flow into a chain whose outputs are empty regardless.

11 of 14 readers of `ai_listing_valuations.csv` do not filter `analysis_context`. Only
`ops/active_monitor.py`, `scripts/ai_listing_valuation.py:835` and `scripts/scheduled_jobs.py:468`
do.

## What was changed

`pages/17_MODEL_PROOF.py` now has a third proof level: **Verified Retail-Exit Replay**, reading
`CSV_data/model_audit/replay_outcomes.csv`.

It renders rows replayed, would-have-bought, profitable-in-period, precision, recall, and the
full confusion matrix, plus the action-label split and an expander over the underlying rows.

Currently displays: **989 rows, 79 bought, TP 79, FP 0, FN 555, TN 355, precision 100.0%,
recall 12.5%.**

The existing "Real settled-profit benchmark" column was left alone. It already handled the empty
case honestly — badge "Unavailable", caption explaining no real post-purchase outcomes exist —
so it was not lying and did not need replacing.

A `st.warning` on the new section states plainly that this measures selection quality and not
realised profit, because the outcome side is a median of ASKING prices with an uncalibrated gap
to realised sale.

## Why this is the strongest evidence available

`build_replay_outcomes.py` deliberately bypasses the whole `outcome_tracking` chain. It re-scores
under the current policy and takes outcomes from verified retail exits rather than from an
`actual_profit` column nobody can fill. Decision and outcome come from independent sources — the
curve resale the live page had, versus scraped exit observations — so it is not circular.

## Standing conclusion

`ops/outcome_tracking.py` and `scored_listings_enriched.csv` are **superseded for now**. They
were built for a world where cars had been bought and real outcomes recorded. Until that exists
they will keep emitting empty files. Left in place and otherwise untouched: correct for their
intended purpose, just starved of input.

## Not done

Adding an `analysis_context` filter to the unfiltered readers. It is correct hygiene and would
prevent recurrence if outcomes ever land, but it fixes a pipeline that currently produces
nothing, so it was not treated as urgent.

## Tests

990 pass.
