from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.comps_engine import parse_currency, parse_numeric


AUTOTRADER_PATH = Path("autotrader_isolated/output/autotrader_recent_market_tagged.csv")
SOLD_PATH = Path("CSV_data/scrapers/sold_cars.csv")
OUTPUT_DIR = Path("output/ute_lanes")


def _text(row: pd.Series) -> str:
    parts = [
        row.get("make", ""),
        row.get("model", ""),
        row.get("variant", ""),
        row.get("body_type", ""),
        row.get("fuel_type", ""),
        row.get("transmission", ""),
        row.get("url", ""),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _cab_style(text: str) -> str:
    if re.search(r"dual cab|double cab|crew cab", text):
        return "dual_cab"
    if re.search(r"extra cab|space cab|super cab|king cab", text):
        return "extra_cab"
    if re.search(r"single cab|cab chassis|cab-chassis", text):
        return "single_cab"
    return "unknown_cab"


def _body_style(text: str) -> str:
    if re.search(r"cab chassis|cab-chassis|chassis", text):
        return "cab_chassis"
    if re.search(r"pick up|pickup|ute|dual cab|extra cab|single cab|crew cab", text):
        return "pickup"
    return "unknown_body"


def _drivetrain(text: str) -> str:
    if re.search(r"\b4x4\b|\b4wd\b|\bawd\b", text):
        return "4x4"
    if re.search(r"\b4x2\b|\b2wd\b|\bhi rider\b|\bhi-rider\b|\brwd\b", text):
        return "4x2"
    return "unknown_drive"


def _prepare(df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    working = df.copy()
    mask = (
        working.get("make", "").astype(str).str.lower().str.contains("toyota", na=False)
        & working.get("model", "").astype(str).str.lower().str.contains("hilux|hi-lux", na=False)
        & working.get("variant", "").astype(str).str.lower().str.contains(r"\bsr\b", regex=True, na=False)
        & working.get("fuel_type", "").astype(str).str.lower().str.contains("diesel", na=False)
        & working.get("transmission", "").astype(str).str.lower().str.contains("auto|automatic|cvt", regex=True, na=False)
    )
    working = working[mask].copy()
    if working.empty:
        return working
    text = working.apply(_text, axis=1)
    working["cab_style"] = text.apply(_cab_style)
    working["body_style"] = text.apply(_body_style)
    working["drivetrain"] = text.apply(_drivetrain)
    working["ute_lane"] = (
        "hilux_sr_diesel_auto_"
        + working["drivetrain"]
        + "_"
        + working["cab_style"]
        + "_"
        + working["body_style"]
    )
    working["price_numeric"] = working.get("price", "").apply(parse_currency)
    odo_col = "odometer" if "odometer" in working.columns else "odometer_reading"
    working["odometer_numeric"] = working.get(odo_col, "").apply(parse_numeric)
    working["year_numeric"] = working.get("year", "").apply(parse_numeric)
    working["source"] = source
    return working


def _summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    return (
        frame.groupby(["source", "ute_lane"])
        .agg(
            rows=("url", "count"),
            median_price=("price_numeric", "median"),
            median_year=("year_numeric", "median"),
            median_odo=("odometer_numeric", "median"),
            min_year=("year_numeric", "min"),
            max_year=("year_numeric", "max"),
        )
        .reset_index()
        .sort_values(["source", "rows"], ascending=[True, False])
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    retail = _prepare(pd.read_csv(AUTOTRADER_PATH, low_memory=False), source="autotrader")
    sold = _prepare(pd.read_csv(SOLD_PATH, low_memory=False), source="sold")
    combined = pd.concat([retail, sold], ignore_index=True, sort=False)
    columns = [
        "source",
        "ute_lane",
        "year",
        "make",
        "model",
        "variant",
        "body_type",
        "fuel_type",
        "transmission",
        "odometer_numeric",
        "price_numeric",
        "cab_style",
        "body_style",
        "drivetrain",
        "url",
    ]
    combined[[column for column in columns if column in combined.columns]].to_csv(
        OUTPUT_DIR / "hilux_sr_diesel_auto_evidence.csv",
        index=False,
    )
    summary = _summary(combined)
    summary.to_csv(OUTPUT_DIR / "hilux_sr_diesel_auto_summary.csv", index=False)
    print(summary.to_string(index=False))
    print(f"Evidence written: {OUTPUT_DIR / 'hilux_sr_diesel_auto_evidence.csv'}")
    print(f"Summary written: {OUTPUT_DIR / 'hilux_sr_diesel_auto_summary.csv'}")


if __name__ == "__main__":
    main()
