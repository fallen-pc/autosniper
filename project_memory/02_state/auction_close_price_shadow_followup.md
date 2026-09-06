# Auction close-price shadow follow-up

Status: shadow-only research; not connected to live valuation, bidding, resale curves, or the VPS.

## What exists

- `scripts/backtest_auction_close_prices.py` reconstructs 24-hour and 6-hour pre-close prediction rows from retained snapshots and verified final sale prices.
- It blocks time leakage: snapshots must precede the recorded sale day end, and comparable sales must be from an earlier calendar day.
- The model evaluates a comparable-only baseline, a pre-auction CatBoost model, and a live CatBoost model. Live predictions cannot be below the observed current bid.

## Latest evidence (2026-09-06)

The rolling run in ignored `artifacts/shadow_auction_backtest_rolling_20260906/` evaluated May, June, and July 2026 independently. In every window, the live model had lower MAE than the comparable-only baseline at both horizons. July was strongest: 24h $1,123 live versus $2,451 baseline (800 rows); 6h $999 live versus $2,441 baseline (826 rows).

## Return-to-work trigger

When later verified sale outcomes and retained snapshots are available, rerun rolling windows with the same leakage guards and compare each new period against its comparable-only and current-bid baselines. Do not promote this model until multiple additional months, high-value/unclassified error analysis, and calibrated prediction ranges support a separate, explicit decision. Any later hammer-price work must remain separate from governed retail resale curves and proxy-max policy.
