"""Turn verified Autotrader listing exits into retail resale observations.

What this produces
------------------
One row per listing whose removal has been *verified* by polling its own URL
(`autotrader_isolated/poll_listing_status.py`), carrying the spec, the price
trajectory and the final asking price.

This is the resale side of the profit equation. It exists because no cars have
been bought yet, so `CSV_data/model_audit/scored_listings_enriched.csv` has 23,179
predictions and zero populated `actual_profit` values. Retail exits are the only
route to validating buy decisions without committing capital.

Read this before using the output
---------------------------------
`final_asking_price` is an **asking** price, not a realised sale price. Cars sell
below asking by an amount that has not been calibrated here. Every column name in
this file says "asking" for that reason. Do not rename it to sale_price, and do
not build a profit figure that treats it as one without applying a haircut.

The safe way to use it is to demand a wide margin: if a Grays car would be bought
at $12k against a $26k retail exit, the verdict survives a large error in the
proxy. Conclusions that depend on the proxy being accurate to a few percent are
not supported by this data.

Exclusions
----------
Only listings with `confirmed_gone_date` set are included: exits confirmed by the
site's own `removed=true` redirect (or a 404/410), not the legacy `sold` flag.
That flag is unreliable — 47.6% of its events were contradicted by a relist, and
direct polling found a further 26.2% of the *cleanest* remainder still live.

Usage
-----
    python -m scripts.build_retail_exit_ledger
    python -m scripts.build_retail_exit_ledger --min-price 5000 --output out.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.curves import load_curves, resolve_curve_canonical_tag

AUTOTRADER_OUT = ROOT_DIR / "autotrader_isolated" / "output"
DEFAULT_EXIT_STATE = AUTOTRADER_OUT / "listing_exit_state.csv"
DEFAULT_LISTING_STATE = AUTOTRADER_OUT / "listing_state.csv"
DEFAULT_HISTORY = AUTOTRADER_OUT / "listing_history.csv"
DEFAULT_TAGGED = AUTOTRADER_OUT / "autotrader_recent_market_tagged.csv"
DEFAULT_OUTPUT = ROOT_DIR / "CSV_data" / "model_audit" / "retail_exit_ledger.csv"

SPEC_COLUMNS = (
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "odometer",
    "transmission",
    "fuel_type",
    "location",
)

LEDGER_COLUMNS = [
    "url",
    "canonical_tag",
    "curve_tag",
    "tag_source",
    *SPEC_COLUMNS,
    "first_listed",
    "last_seen",
    "exit_confirmed_date",
    "exit_reason",
    "days_visible_in_scrape",
    "initial_asking_price",
    "final_asking_price",
    "total_reduction",
    "reduction_pct",
    "price_change_count",
    "price_basis",
]

# Values that look like a tag but are not one. The --tagged-only filter originally
# tested only for the empty string, so "nan" and "UNCLASSIFIED" both slipped
# through and inflated the apparent usable row count by more than 20x.
UNUSABLE_TAGS = {"", "nan", "none", "nat", "unclassified"}


def is_real_tag(series: pd.Series) -> pd.Series:
    return ~series.astype(str).str.strip().str.lower().isin(UNUSABLE_TAGS)


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _datetime(frame: pd.DataFrame, column: str) -> pd.Series:
    """Always return a datetime Series aligned to the frame.

    frame.get(missing) yields None, and arithmetic on two of those raises rather
    than producing NaT, so an incomplete state file would abort the whole build.
    """
    if column not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    return pd.to_datetime(frame[column], errors="coerce")


def confirmed_exits(exit_state: pd.DataFrame) -> pd.DataFrame:
    """Rows whose exit was verified by a direct poll."""
    if exit_state.empty or "confirmed_gone_date" not in exit_state.columns:
        return pd.DataFrame(columns=exit_state.columns)
    source = exit_state["confirmed_gone_date"]
    confirmed = source.astype(str).str.strip()
    keep = source.notna() & confirmed.ne("") & ~confirmed.str.lower().isin({"nan", "nat", "none", "<na>"})
    return exit_state[keep].copy()


def price_trajectory(history: pd.DataFrame, urls: set[str]) -> pd.DataFrame:
    """Initial asking price and number of reductions, per listing."""
    empty = pd.DataFrame(columns=["url", "initial_asking_price", "price_change_count"])
    if history.empty or "url" not in history.columns:
        return empty

    frame = history[history["url"].astype(str).str.strip().isin(urls)].copy()
    if frame.empty:
        return empty

    frame["url"] = frame["url"].astype(str).str.strip()
    frame["_ts"] = pd.to_datetime(frame.get("event_date"), errors="coerce")
    frame["_price"] = pd.to_numeric(frame.get("price"), errors="coerce")
    frame = frame.sort_values("_ts")

    priced = frame[frame["_price"].notna() & (frame["_price"] > 0)]
    initial = (
        priced.groupby("url")["_price"].first().rename("initial_asking_price").reset_index()
        if not priced.empty
        else empty[["url", "initial_asking_price"]]
    )

    changes = frame[frame.get("event").astype(str).str.strip() == "price_change"]
    counts = (
        changes.groupby("url").size().rename("price_change_count").reset_index()
        if not changes.empty
        else pd.DataFrame(columns=["url", "price_change_count"])
    )

    return initial.merge(counts, on="url", how="outer")


def _tag_from_spec(ledger: pd.DataFrame) -> pd.DataFrame:
    """Canonically tag rows the tagged feed did not cover, using their own spec.

    The feed (`autotrader_recent_market_tagged.csv`) only spans the recent market
    window, so backfilled exits from months ago are mostly absent from it. Those
    rows still carry year/make/model/variant/body/transmission/fuel, which is what
    the tagger needs, so they can be classified directly.
    """
    needs = ~is_real_tag(ledger["canonical_tag"])
    if not needs.any():
        return ledger

    try:
        from shared.canonical_tagging import tag_dataframe
    except Exception as exc:  # noqa: BLE001
        print(f"  direct tagging unavailable ({type(exc).__name__}), keeping feed tags only")
        return ledger

    subset = ledger.loc[needs].copy()
    # The tagger reads a `price` column; the ledger stores it under its own name.
    subset["price"] = subset["final_asking_price"]
    try:
        retagged = tag_dataframe(
            subset,
            source="autotrader_exit_ledger",
            require_price=False,
            append_log=False,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  direct tagging failed ({type(exc).__name__}: {exc})")
        return ledger

    if "canonical_tag" not in retagged.columns:
        return ledger

    new_tags = retagged["canonical_tag"].to_numpy()
    ledger.loc[needs, "canonical_tag"] = new_tags
    gained = is_real_tag(pd.Series(new_tags)).sum()
    ledger.loc[needs, "tag_source"] = [
        "spec" if real else "" for real in is_real_tag(pd.Series(new_tags))
    ]
    print(f"  direct tagging recovered {int(gained):,} of {int(needs.sum()):,} untagged rows")
    return ledger


def build_ledger(
    exit_state: pd.DataFrame,
    listing_state: pd.DataFrame,
    history: pd.DataFrame,
    tagged: pd.DataFrame | None,
    curves_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    confirmed = confirmed_exits(exit_state)
    if confirmed.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    confirmed["url"] = confirmed["url"].astype(str).str.strip()
    keep_exit = ["url", "confirmed_gone_date", "last_reason", "exit_price"]
    ledger = confirmed[[c for c in keep_exit if c in confirmed.columns]].copy()
    ledger = ledger.rename(
        columns={"confirmed_gone_date": "exit_confirmed_date", "last_reason": "exit_reason"}
    )

    state = listing_state.copy()
    state["url"] = state["url"].astype(str).str.strip()
    keep_state = ["url", "first_seen", "last_seen", "last_price", *SPEC_COLUMNS]
    state = state[[c for c in keep_state if c in state.columns]].drop_duplicates(subset=["url"])
    ledger = ledger.merge(state, on="url", how="left")
    ledger = ledger.rename(columns={"first_seen": "first_listed"})

    # Prefer the price captured at confirmation; fall back to the last known price.
    exit_price = _numeric(ledger, "exit_price")
    last_price = _numeric(ledger, "last_price")
    ledger["final_asking_price"] = exit_price.where(exit_price.notna() & (exit_price > 0), last_price)
    ledger["price_basis"] = [
        "exit_price" if pd.notna(e) and e > 0 else ("last_price" if pd.notna(l) and l > 0 else "")
        for e, l in zip(exit_price, last_price)
    ]

    traj = price_trajectory(history, set(ledger["url"]))
    ledger = ledger.merge(traj, on="url", how="left")

    initial = _numeric(ledger, "initial_asking_price")
    final = _numeric(ledger, "final_asking_price")
    ledger["total_reduction"] = (initial - final).where(initial.notna() & final.notna())
    ledger["reduction_pct"] = (
        (ledger["total_reduction"] / initial * 100.0).where(initial.notna() & (initial > 0))
    ).round(2)

    # NOT time-to-sell. first_seen/last_seen come from the legacy scrape's presence
    # in search results, which churns with scope and pagination - the observed
    # median is ~4 days, far too short for a real used-car sale. Named for what it
    # actually measures so nobody reads it as days on market.
    listed = _datetime(ledger, "first_listed")
    seen = _datetime(ledger, "last_seen")
    ledger["days_visible_in_scrape"] = ((seen - listed).dt.total_seconds() / 86400).round(1)

    if tagged is not None and not tagged.empty and "url" in tagged.columns:
        tags = tagged.copy()
        tags["url"] = tags["url"].astype(str).str.strip()
        tag_cols = [c for c in ("url", "canonical_tag") if c in tags.columns]
        tags = tags[tag_cols].drop_duplicates(subset=["url"])
        ledger = ledger.merge(tags, on="url", how="left")

    if "canonical_tag" not in ledger.columns:
        ledger["canonical_tag"] = ""
    ledger["tag_source"] = ["feed" if real else "" for real in is_real_tag(ledger["canonical_tag"])]

    # The tagged feed only covers the recent market window, so most backfilled
    # exits are absent from it. Tag those directly from the spec the ledger
    # already carries rather than discarding them.
    ledger = _tag_from_spec(ledger)

    if curves_df is not None:
        ledger["curve_tag"] = (
            ledger["canonical_tag"].astype(str).str.strip().apply(
                lambda tag: resolve_curve_canonical_tag(tag, curves_df=curves_df) if tag else ""
            )
        )
    else:
        ledger["curve_tag"] = ""

    ledger["price_change_count"] = _numeric(ledger, "price_change_count").fillna(0).astype(int)
    return ledger.reindex(columns=LEDGER_COLUMNS)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build retail resale observations from verified Autotrader listing exits."
    )
    p.add_argument("--exit-state", type=Path, default=DEFAULT_EXIT_STATE)
    p.add_argument("--listing-state", type=Path, default=DEFAULT_LISTING_STATE)
    p.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    p.add_argument("--tagged", type=Path, default=DEFAULT_TAGGED)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--min-price", type=float, default=0.0,
                   help="Drop observations below this final asking price.")
    p.add_argument("--tagged-only", action="store_true",
                   help="Keep only rows that resolve to a curve_tag.")
    return p.parse_args(argv)


def _read(path: Path, label: str) -> pd.DataFrame:
    if not path.exists():
        print(f"  {label}: not found ({path})")
        return pd.DataFrame()
    frame = pd.read_csv(path, low_memory=False)
    print(f"  {label}: {len(frame):,} rows")
    return frame


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print("Loading inputs:")
    exit_state = _read(args.exit_state, "exit state")
    if exit_state.empty:
        print("\nNo exit state. Run autotrader_isolated/poll_listing_status.py first.")
        return 1
    listing_state = _read(args.listing_state, "listing state")
    history = _read(args.history, "history")
    tagged = _read(args.tagged, "tagged market")

    try:
        curves_df = load_curves()
    except Exception as exc:  # noqa: BLE001
        print(f"  curves: unavailable ({type(exc).__name__}), curve_tag will be blank")
        curves_df = None

    ledger = build_ledger(exit_state, listing_state, history, tagged, curves_df)
    print(f"\nconfirmed exits: {len(ledger):,}")
    if ledger.empty:
        print("Nothing confirmed yet - poll more listings before building the ledger.")
        return 0

    if args.min_price > 0:
        before = len(ledger)
        ledger = ledger[_numeric(ledger, "final_asking_price") >= args.min_price]
        print(f"  min price >= ${args.min_price:,.0f}: {before:,} -> {len(ledger):,}")

    if args.tagged_only:
        before = len(ledger)
        ledger = ledger[is_real_tag(ledger["curve_tag"])]
        print(f"  curve-tagged only: {before:,} -> {len(ledger):,}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(ledger, args.output, index=False)

    price = _numeric(ledger, "final_asking_price")
    real_tags = is_real_tag(ledger["curve_tag"])
    print(f"\nwritten: {args.output} ({len(ledger):,} rows)")
    print(f"  final asking price  median ${price.median():,.0f}")
    print(f"    >= $10k: {(price >= 10000).sum():,}    >= $15k: {(price >= 15000).sum():,}")
    print(f"  curve-tagged        {int(real_tags.sum()):,} of {len(ledger):,}")
    if real_tags.any():
        lanes = ledger.loc[real_tags, "curve_tag"].value_counts()
        print(f"  distinct lanes      {len(lanes):,}")
        for depth in (3, 5, 10):
            deep = lanes[lanes >= depth]
            print(f"    lanes with >={depth:2d} obs: {len(deep):3,} covering {int(deep.sum()):,} rows")
    reduced = _numeric(ledger, "total_reduction")
    had_cut = reduced.notna() & (reduced > 0)
    if had_cut.any():
        print(f"  cut price before exit {had_cut.sum():,} "
              f"(median ${reduced[had_cut].median():,.0f}, "
              f"{_numeric(ledger, 'reduction_pct')[had_cut].median():.1f}%)")
    print("\nNOTE: final_asking_price is an ASKING price, not a realised sale price.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
