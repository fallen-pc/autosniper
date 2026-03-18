from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

try:
    from shared.data_loader import dataset_path
    from scripts.atomic_csv import write_dataframe_csv_atomic
except ModuleNotFoundError:  # pragma: no cover
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import dataset_path
    from scripts.atomic_csv import write_dataframe_csv_atomic


def _parse_currency(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("$", "").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _load_bid_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Bid history file not found: {path}")
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["bidder_name"] = df.get("bidder_name", pd.Series([None] * len(df))).fillna("").astype(str).str.strip()
    df["url"] = df.get("url", pd.Series([None] * len(df))).fillna("").astype(str).str.strip()
    df["bid_price_numeric"] = df.get("bid_price", pd.Series([None] * len(df))).apply(_parse_currency)
    df["reserve_met"] = df.get("reserve_met", False).astype(bool)
    return df


def summarize_bidders(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df[df["bidder_name"].astype(bool)].copy()
    if filtered.empty:
        return filtered
    summary = (
        filtered.groupby("bidder_name")
        .agg(
            bid_count=("bidder_name", "size"),
            listings=("url", "nunique"),
            avg_bid=("bid_price_numeric", "mean"),
            max_bid=("bid_price_numeric", "max"),
            reserve_met_count=("reserve_met", "sum"),
        )
        .reset_index()
    )
    summary.sort_values(by=["listings", "bid_count"], ascending=[False, False], inplace=True)
    return summary


def summarize_listings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    listing_summary = (
        df.groupby("url")
        .agg(
            bidders=("bidder_name", "nunique"),
            bid_rows=("bidder_name", "size"),
            max_bid=("bid_price_numeric", "max"),
            reserve_met=("reserve_met", "max"),
        )
        .reset_index()
    )
    listing_summary.sort_values(by=["bidders", "bid_rows"], ascending=[False, False], inplace=True)
    return listing_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze bid history patterns by bidder and listing.")
    parser.add_argument(
        "--input",
        type=Path,
        default=dataset_path("bid_history.csv"),
        help="Path to bid history CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=dataset_path("bid_history_bidders.csv"),
        help="Output CSV for bidder summary.",
    )
    parser.add_argument(
        "--listing-output",
        type=Path,
        default=dataset_path("bid_history_listings.csv"),
        help="Output CSV for listing summary.",
    )
    args = parser.parse_args()

    df = _load_bid_history(args.input)
    if df.empty:
        raise SystemExit("Bid history file is empty.")

    bidders = summarize_bidders(df)
    listings = summarize_listings(df)

    write_dataframe_csv_atomic(bidders, args.output, index=False)
    write_dataframe_csv_atomic(listings, args.listing_output, index=False)

    print(f"Wrote bidder summary to {args.output}")
    print(f"Wrote listing summary to {args.listing_output}")


if __name__ == "__main__":
    main()
