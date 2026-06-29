"""Simulate resale outcomes for scored listings using current Autotrader/Carsales
retail asking prices as a proxy for resale price.

This does NOT use real sale data — no vehicle has been purchased through
AutoSniper yet. It exists to let the model's BUY/WATCH decisions be checked
against a market-price proxy (the median of several current retail listings
for the same spec) before any real capital is committed.

Methodology, in order:
1. For each scored listing, build the same lane_key used in
   generate_opportunity_lanes.py (make/model/variant_family/body/fuel/trans).
2. Pool matching Autotrader + Carsales listings in that lane within a year
   and odometer tolerance.
3. Require a minimum sample size (MIN_RETAIL_MATCHES) before trusting the
   median asking price as a resale proxy — thin samples are dropped, not
   guessed at.
4. simulated_profit = retail_median - buy_price_basis - fees - repair_high
   where buy_price_basis is expected_auction_price_value (or
   recommended_max_bid_value as a fallback) since no real purchase price
   exists yet.

Every output row is tagged outcome_type="simulated_retail_median" with the
match sample size and tolerance baked into outcome_note so the asterisk
travels with the number.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from scripts.generate_opportunity_lanes import _prepare_common
from shared.comps_engine import parse_currency, parse_numeric
from shared.data_loader import dataset_path

DEFAULT_VALUATIONS_PATH = dataset_path("ai_listing_valuations.csv")
DEFAULT_STATIC_DETAILS_PATH = dataset_path("vehicle_static_details.csv")
DEFAULT_CARSALES_PATH = Path("CSV_data/quality/carsales_apify_listings.csv")
DEFAULT_AUTOTRADER_PATH = Path("autotrader_isolated/output/autotrader_recent_market_tagged.csv")
DEFAULT_OUTPUT_PATH = dataset_path("model_audit/simulated_retail_median_outcomes.csv")

STATIC_DETAIL_COLUMNS = ["url", "body_type", "transmission", "fuel_type", "odometer_reading"]

MIN_RETAIL_MATCHES = 5
YEAR_TOLERANCE = 2
ODOMETER_TOLERANCE_PCT = 0.25
ODOMETER_TOLERANCE_FLOOR_KM = 20000


def _latest_by_url(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "url" not in df.columns:
        return df
    working = df.copy()
    if "analysis_timestamp" in working.columns:
        working["analysis_timestamp"] = pd.to_datetime(working["analysis_timestamp"], errors="coerce")
        working = working.sort_values("analysis_timestamp")
    return working.drop_duplicates(subset=["url"], keep="last")


def _load_retail_pool(carsales_path: Path, autotrader_path: Path) -> pd.DataFrame:
    pools: list[pd.DataFrame] = []
    if carsales_path.exists():
        carsales = pd.read_csv(carsales_path, low_memory=False)
        carsales = _prepare_common(carsales, source="carsales")
        carsales["retail_price"] = carsales.get("price", "").apply(parse_currency)
        pools.append(carsales)
    if autotrader_path.exists():
        autotrader = pd.read_csv(autotrader_path, low_memory=False)
        autotrader = _prepare_common(autotrader, source="autotrader")
        autotrader["retail_price"] = autotrader.get("price", "").apply(parse_currency)
        pools.append(autotrader)
    if not pools:
        return pd.DataFrame()
    retail = pd.concat(pools, ignore_index=True, sort=False)
    retail = retail.dropna(subset=["retail_price", "make_key", "model_key"])
    retail = retail[(retail["retail_price"] > 500) & (retail["retail_price"] < 250000)]
    return retail


def _retail_median_match(
    row: pd.Series,
    retail_by_lane: dict[str, pd.DataFrame],
) -> tuple[float | None, int, str]:
    lane_key = row.get("lane_key", "")
    lane = retail_by_lane.get(lane_key)
    if lane is None or lane.empty:
        return None, 0, "no_lane_match"

    year = row.get("year_numeric")
    odometer = row.get("odometer_numeric")

    candidates = lane
    if year is not None and not pd.isna(year):
        candidates = candidates[(candidates["year_numeric"] - year).abs() <= YEAR_TOLERANCE]
    if candidates.empty:
        return None, 0, "no_year_match"

    if odometer is not None and not pd.isna(odometer):
        tolerance = max(odometer * ODOMETER_TOLERANCE_PCT, ODOMETER_TOLERANCE_FLOOR_KM)
        odo_candidates = candidates[(candidates["odometer_numeric"] - odometer).abs() <= tolerance]
        if len(odo_candidates) >= MIN_RETAIL_MATCHES:
            candidates = odo_candidates

    if len(candidates) < MIN_RETAIL_MATCHES:
        return None, len(candidates), "thin_sample"

    return float(candidates["retail_price"].median()), len(candidates), "ok"


def _buy_price_basis(row: pd.Series) -> tuple[float | None, str]:
    for field in ("expected_auction_price_value", "recommended_max_bid_value", "current_bid_numeric"):
        value = row.get(field)
        value = parse_currency(value) if not isinstance(value, (int, float)) else value
        if value is not None and not pd.isna(value) and value > 0:
            return float(value), field
    return None, ""


def _join_static_details(valuations: pd.DataFrame, static_details_path: Path) -> pd.DataFrame:
    if not static_details_path.exists():
        for column in STATIC_DETAIL_COLUMNS[1:]:
            valuations[column] = ""
        return valuations
    static_details = pd.read_csv(static_details_path, low_memory=False)
    available = [column for column in STATIC_DETAIL_COLUMNS if column in static_details.columns]
    static_details = static_details[available].drop_duplicates(subset=["url"], keep="last")
    return valuations.merge(static_details, on="url", how="left")


def generate_retail_median_outcomes(
    *,
    valuations_path: Path = DEFAULT_VALUATIONS_PATH,
    static_details_path: Path = DEFAULT_STATIC_DETAILS_PATH,
    carsales_path: Path = DEFAULT_CARSALES_PATH,
    autotrader_path: Path = DEFAULT_AUTOTRADER_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    if not valuations_path.exists():
        raise FileNotFoundError(valuations_path)

    valuations = pd.read_csv(valuations_path, low_memory=False)
    valuations = _latest_by_url(valuations)
    valuations = _join_static_details(valuations, static_details_path)
    valuations = _prepare_common(valuations, source="scored")

    retail = _load_retail_pool(carsales_path, autotrader_path)
    retail_by_lane = {
        lane_key: group for lane_key, group in retail.groupby("lane_key")
    } if not retail.empty else {}

    rows: list[dict[str, object]] = []
    for _, row in valuations.iterrows():
        retail_median, match_count, match_status = _retail_median_match(row, retail_by_lane)
        buy_price, buy_price_basis = _buy_price_basis(row)
        fees = parse_currency(row.get("fees_estimate")) or 0.0
        repair_high = row.get("repair_estimate_high_value")
        repair_high = parse_currency(repair_high) if not isinstance(repair_high, (int, float)) else repair_high
        repair_high = repair_high or 0.0

        simulated_profit = None
        if retail_median is not None and buy_price is not None:
            simulated_profit = retail_median - buy_price - fees - repair_high

        rows.append(
            {
                "url": row.get("url"),
                "year": row.get("year"),
                "make": row.get("make"),
                "model": row.get("model"),
                "variant": row.get("variant"),
                "lane_key": row.get("lane_key"),
                "action_label": row.get("action_label"),
                "computed_verdict": row.get("computed_verdict"),
                "confidence": row.get("confidence"),
                "buy_price_basis_field": buy_price_basis,
                "buy_price_basis_value": buy_price,
                "fees_estimate": fees,
                "repair_estimate_high": repair_high,
                "retail_match_count": match_count,
                "retail_match_status": match_status,
                "simulated_retail_median": retail_median,
                "simulated_profit": simulated_profit,
                "outcome_type": "simulated_retail_median",
                "outcome_note": (
                    f"Asking-price proxy, not a confirmed sale. Median of "
                    f"{match_count} concurrent Autotrader/Carsales listings "
                    f"matched by make/model/variant family/body/fuel/transmission "
                    f"within ±{YEAR_TOLERANCE}yr and odometer tolerance "
                    f"max({ODOMETER_TOLERANCE_PCT:.0%}, {ODOMETER_TOLERANCE_FLOOR_KM}km)."
                ),
            }
        )

    output = pd.DataFrame(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(output, output_path, index=False)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Simulate resale outcomes using current Autotrader/Carsales median "
            "asking price as a proxy for resale price, since no real sales exist yet."
        )
    )
    parser.add_argument("--valuations", type=Path, default=DEFAULT_VALUATIONS_PATH)
    parser.add_argument("--static-details", type=Path, default=DEFAULT_STATIC_DETAILS_PATH)
    parser.add_argument("--carsales", type=Path, default=DEFAULT_CARSALES_PATH)
    parser.add_argument("--autotrader", type=Path, default=DEFAULT_AUTOTRADER_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args(argv)

    output = generate_retail_median_outcomes(
        valuations_path=args.valuations,
        static_details_path=args.static_details,
        carsales_path=args.carsales,
        autotrader_path=args.autotrader,
        output_path=args.output,
    )
    with_profit = output["simulated_profit"].notna().sum()
    print(
        "[retail-median-outcomes] "
        f"rows={len(output)} "
        f"with_simulated_profit={int(with_profit)} "
        f"output={args.output}"
    )
    if with_profit:
        by_verdict = (
            output.dropna(subset=["simulated_profit"])
            .groupby("action_label")["simulated_profit"]
            .agg(["count", "median", "mean"])
        )
        print(by_verdict.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
