"""Show how far the Autotrader exit backfill has got.

Safe to run at any time, including while a poll is in progress - it only reads.

    python scripts/exit_poll_progress.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

AUTOTRADER_OUT = ROOT_DIR / "autotrader_isolated" / "output"
EXIT_STATE = AUTOTRADER_OUT / "listing_exit_state.csv"
EXIT_LOG = AUTOTRADER_OUT / "listing_exit_log.csv"
LISTING_STATE = AUTOTRADER_OUT / "listing_state.csv"
HISTORY = AUTOTRADER_OUT / "listing_history.csv"


def _is_set(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    return text.ne("") & ~text.isin({"nan", "NaT", "None"})


def main() -> int:
    if not EXIT_STATE.exists():
        print("No exit state yet - the poll has not written anything.")
        return 1

    state = pd.read_csv(EXIT_STATE, low_memory=False)
    polled = len(state)
    confirmed = int(_is_set(state["confirmed_gone_date"]).sum()) if "confirmed_gone_date" in state else 0

    print(f"polled          : {polled:,}")
    print(f"confirmed exits : {confirmed:,}")

    if "last_verdict" in state.columns:
        counts = state["last_verdict"].value_counts()
        for verdict in ("live", "gone", "unknown"):
            n = int(counts.get(verdict, 0))
            if polled:
                print(f"  {verdict:<8}      {n:,} ({n / polled * 100:.1f}%)")

    # Remaining work, mirroring the backfill's own selection.
    if LISTING_STATE.exists():
        listings = pd.read_csv(LISTING_STATE, low_memory=False)
        if "status" in listings.columns:
            listings = listings[listings["status"].astype(str).str.strip() == "sold"]
        if HISTORY.exists():
            history = pd.read_csv(HISTORY, usecols=["event", "url"], low_memory=False)
            relisted = set(
                history[history["event"].astype(str).str.strip() == "relisted"]["url"]
                .astype(str)
                .str.strip()
            )
            listings = listings[~listings["url"].astype(str).str.strip().isin(relisted)]
        if "last_price" in listings.columns:
            price = pd.to_numeric(listings["last_price"], errors="coerce")
            listings = listings[price.notna() & (price > 0)]

        candidates = set(listings["url"].astype(str).str.strip())
        done = set(state["url"].astype(str).str.strip())
        remaining = len(candidates - done)
        total = len(candidates)
        if total:
            pct = (total - remaining) / total * 100
            print(f"\nbackfill        : {total - remaining:,}/{total:,} done ({pct:.1f}%)")
            print(f"remaining       : {remaining:,}")

    if EXIT_LOG.exists():
        log = pd.read_csv(EXIT_LOG, low_memory=False)
        if "elapsed_ms" in log.columns and len(log):
            print(f"\nmedian per poll : {int(log['elapsed_ms'].median()):,} ms")
        if "poll_ts" in log.columns and len(log):
            print(f"last poll batch : {log['poll_ts'].iloc[-1]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
