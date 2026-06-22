from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.data_loader import dataset_path


DEFAULT_OUTPUT = dataset_path("model_audit/simulated_sold_outcomes.csv")

SIMULATED_SALE_PRICE_FIELDS = (
    "resale_mid_value",
    "carsales_price_estimate",
    "resale_mid",
    "expected_resale",
    "predicted_resale_price",
)


def _parse_currency(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    for separator in (" - ", "-", " to "):
        if separator in text:
            parts = [part.strip() for part in text.split(separator) if part.strip()]
            numbers = [_parse_currency(part) for part in parts]
            numbers = [number for number in numbers if number is not None]
            return sum(numbers) / len(numbers) if numbers else None
    cleaned = (
        text.replace("$", "")
        .replace(",", "")
        .replace("AUD", "")
        .replace("aud", "")
        .strip()
    )
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _latest_by_url(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "url" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    working = df.copy()
    if "analysis_timestamp" in working.columns:
        working["analysis_timestamp"] = pd.to_datetime(working["analysis_timestamp"], errors="coerce")
        working = working.sort_values("analysis_timestamp")
    return working.drop_duplicates(subset=["url"], keep="last")


def _first_price(row: pd.Series, fields: tuple[str, ...]) -> tuple[float | None, str]:
    for field in fields:
        if field not in row.index:
            continue
        value = _parse_currency(row.get(field))
        if value is not None:
            return value, field
    return None, ""


def _numeric_column(df: pd.DataFrame, column: str, default: float | None = None) -> pd.Series:
    if column in df.columns:
        return pd.to_numeric(df[column], errors="coerce")
    return pd.Series(default, index=df.index, dtype="float64")


def generate_simulated_sold_outcomes(
    *,
    valuations_path: Path,
    scored_path: Path,
    output_path: Path,
) -> pd.DataFrame:
    valuations = pd.read_csv(valuations_path, low_memory=False)
    scored = pd.read_csv(scored_path, low_memory=False)

    if "url" not in valuations.columns:
        raise ValueError(f"{valuations_path} must include a url column")
    if "url" not in scored.columns:
        raise ValueError(f"{scored_path} must include a url column")

    valuations = _latest_by_url(valuations)
    scored = scored.drop_duplicates(subset=["url"], keep="last").copy()

    keep_valuation_cols = [
        column
        for column in (
            "url",
            "analysis_timestamp",
            "action_label",
            "computed_verdict",
            "bid_status",
            "recommended_max_bid",
            "recommended_max_bid_value",
            "expected_auction_profit",
            "expected_auction_profit_value",
            *SIMULATED_SALE_PRICE_FIELDS,
        )
        if column in valuations.columns
    ]
    keep_scored_cols = [
        column
        for column in (
            "url",
            "year",
            "make",
            "model",
            "variant",
            "purchase_price",
            "purchase_date",
            "actual_fees_total",
            "reconditioning_cost",
            "settled_date",
        )
        if column in scored.columns
    ]

    joined = valuations[keep_valuation_cols].merge(scored[keep_scored_cols], on="url", how="inner")
    if joined.empty:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_dataframe_csv_atomic(joined, output_path, index=False)
        return joined

    sale_prices: list[float | None] = []
    sale_sources: list[str] = []
    for _, row in joined.iterrows():
        price, source = _first_price(row, SIMULATED_SALE_PRICE_FIELDS)
        sale_prices.append(price)
        sale_sources.append(source)

    joined["simulated_sale_price"] = sale_prices
    joined["simulated_source"] = sale_sources
    joined["purchase_price"] = _numeric_column(joined, "purchase_price")
    joined["actual_fees_total"] = _numeric_column(joined, "actual_fees_total", 0.0).fillna(0.0)
    joined["reconditioning_cost"] = _numeric_column(joined, "reconditioning_cost", 0.0).fillna(0.0)
    joined["simulated_actual_profit"] = pd.NA

    has_inputs = joined["simulated_sale_price"].notna() & joined["purchase_price"].notna()
    joined.loc[has_inputs, "simulated_actual_profit"] = (
        joined.loc[has_inputs, "simulated_sale_price"]
        - joined.loc[has_inputs, "purchase_price"]
        - joined.loc[has_inputs, "actual_fees_total"]
        - joined.loc[has_inputs, "reconditioning_cost"]
    )
    joined["outcome_type"] = "simulated"
    joined["outcome_note"] = (
        "Proxy benchmark only: simulated_sale_price comes from resale estimate fields, not a real sale."
    )

    output_columns = [
        "url",
        "year",
        "make",
        "model",
        "variant",
        "analysis_timestamp",
        "action_label",
        "computed_verdict",
        "bid_status",
        "purchase_price",
        "actual_fees_total",
        "reconditioning_cost",
        "simulated_sale_price",
        "simulated_actual_profit",
        "simulated_source",
        "outcome_type",
        "outcome_note",
        "settled_date",
    ]
    output_columns = [column for column in output_columns if column in joined.columns]
    output = joined[output_columns].copy()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_dataframe_csv_atomic(output, output_path, index=False)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate clearly labelled simulated sold outcomes from resale estimate fields."
    )
    parser.add_argument("--valuations", type=Path, default=dataset_path("ai_listing_valuations.csv"))
    parser.add_argument("--scored", type=Path, default=dataset_path("scored_listings_enriched.csv"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    output = generate_simulated_sold_outcomes(
        valuations_path=args.valuations,
        scored_path=args.scored,
        output_path=args.output,
    )
    with_profit = pd.to_numeric(output.get("simulated_actual_profit"), errors="coerce").notna().sum()
    print(
        "[simulated-outcomes] "
        f"rows={len(output)} "
        f"with_simulated_profit={int(with_profit)} "
        f"output={args.output}"
    )
    return 0 if with_profit else 2


if __name__ == "__main__":
    raise SystemExit(main())
