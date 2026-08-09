"""Build governed Mazda CX-7 ER Series 2 Classic and Luxury Sports curves."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.curve_builder_v2 import propose_curve_from_evidence
from shared.curves import CURVE_COLUMNS


ROOT = Path(__file__).resolve().parent.parent
RETAIL = ROOT / "CSV_data" / "quality" / "carsales_apify_listings.csv"
SOLD = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    {
        "base": "mazda_cx-7_classic_er-series-2_wagon_auto_petrol",
        "match": "mazda_cx-7_classic_petrol_auto_wagon_er-series-2",
        "retail": r"^Classic ER Series 2 Auto$",
        "sold": r"^classic(?: petrol(?: suv)?)?$",
        "badge": "classic",
        "aliases": "classic|classic petrol|classic petrol suv",
        "engine": r"2\.5L",
        "excluded": "manual|diesel|luxury|luxury sports|classic sports|2.3",
    },
    {
        "base": "mazda_cx-7_luxury-sports_er-series-2_wagon_auto_petrol",
        "match": "mazda_cx-7_luxury-sports_petrol_auto_wagon_er-series-2",
        "retail": r"^Luxury Sports ER Series 2 Auto 4WD$",
        "sold": r"^luxury sports(?: \(4x4\)| awd| awd petrol| petrol)?$",
        "badge": "luxury sports",
        "aliases": "luxury sports|luxury sports 4x4|luxury sports awd|luxury sports awd petrol",
        "engine": r"2\.3L",
        "excluded": "manual|diesel|classic|classic sports|luxury er|2.5",
    },
]


def _replace_rows(path: Path, rows: list[dict[str, object]], key: str, managed: set[str]) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key].astype(str).isin(managed)].copy()
    incoming = pd.DataFrame(rows, columns=existing.columns)
    write_dataframe_csv_atomic(
        pd.concat([existing, incoming], ignore_index=True).drop_duplicates(key, keep="last"),
        path,
        index=False,
    )


def main() -> int:
    retail = pd.read_csv(RETAIL, low_memory=False)
    sold = pd.read_csv(SOLD, low_memory=False)
    retail = retail[
        retail["seller_type"].fillna("").str.lower().eq("private")
        & retail["make"].fillna("").str.lower().eq("mazda")
        & retail["model"].fillna("").str.lower().eq("cx-7")
    ].copy()
    sold = sold[
        sold["make"].fillna("").str.lower().eq("mazda")
        & sold["model"].fillna("").str.lower().eq("cx-7")
    ].copy()
    for frame, year, odometer, price in [
        (retail, "year", "odometer", "price"),
        (sold, "year", "odometer_reading", "price"),
    ]:
        frame["year_numeric"] = pd.to_numeric(frame[year], errors="coerce")
        frame["odometer_numeric"] = pd.to_numeric(frame[odometer], errors="coerce")
        frame["price_numeric"] = pd.to_numeric(frame[price], errors="coerce")

    proposals: list[pd.DataFrame] = []
    allowed_rows = []
    group_rows = []
    supported_rows = []
    override_rows = []
    for lane in LANES:
        market = retail[
            retail["variant"].fillna("").str.contains(lane["retail"], case=False, regex=True)
            & retail["engine"].fillna("").str.contains(lane["engine"], case=False, regex=True)
            & retail["transmission"].fillna("").str.contains("auto", case=False)
            & retail["fuel_type"].fillna("").str.contains("petrol", case=False)
        ].dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        auction = sold[
            sold["variant"].fillna("").str.contains(lane["sold"], case=False, regex=True)
            & sold["body_type"].fillna("").str.contains("wagon|suv", case=False, regex=True)
            & sold["transmission"].fillna("").str.contains("auto", case=False)
            & sold["fuel_type"].fillna("").str.contains("petrol", case=False)
            & sold["year_numeric"].between(2009, 2011)
        ].dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        if len(market) < 6 or auction["vin"].fillna(auction["url"]).nunique() < 6:
            raise RuntimeError(f"Insufficient evidence for {lane['base']}")
        proposal, metadata = propose_curve_from_evidence(
            base_curve_tag=lane["base"],
            active_market_df=market,
            sold_df=auction,
            anchor_years=[2009, 2010, 2011],
            buckets=BUCKETS,
            evidence_source="existing private Carsales staging and live Grays sold",
        )
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        demand = int(auction["vin"].fillna(auction["url"]).nunique())
        note = (
            f"Built from {metadata.active_rows_used} exact private Carsales rows and "
            f"{demand} unique live Grays vehicles; ER Series 1 Luxury, other trims, "
            "manual, diesel, and the alternate 2.3/2.5 powertrain remain separate."
        )
        allowed_rows.append({
            "canonical_tag": lane["match"], "make": "mazda", "model": "cx7",
            "body": "wagon", "fuel": "petrol", "transmission": "auto",
            "badge": lane["badge"], "series": "er series 2",
            "allowed_badge_aliases": lane["aliases"], "allowed_body_aliases": "wagon|suv",
            "excluded_keywords": lane["excluded"],
        })
        group_rows.append({"match_tag": lane["match"], "base_curve_tag": lane["base"], "status": "active", "notes": note})
        supported_rows.append({
            "base_curve_tag": lane["base"], "make": "mazda", "model": "cx-7",
            "body": "wagon", "fuel": "petrol", "transmission": "auto",
            "generation": "er series 2", "coverage_status": "live_now",
            "resale_supported": 1, "notes": note,
        })
        override_rows.append({"base_curve_tag": lane["base"], "anchor_years": "2009|2010|2011", "notes": note})
        print(f"{lane['base']}: retail={len(market)} grays_unique={demand}")

    curves_path = ROOT / "CSV_data" / "restricted" / "curves.csv"
    curves = pd.read_csv(curves_path)
    bases = {lane["base"] for lane in LANES}
    matches = {lane["match"] for lane in LANES}
    curves = curves[~curves["canonical_tag"].isin(bases)]
    write_dataframe_csv_atomic(pd.concat([curves, *proposals], ignore_index=True), curves_path, index=False)
    _replace_rows(ROOT / "config" / "allowed_variants.csv", allowed_rows, "canonical_tag", matches)
    _replace_rows(ROOT / "config" / "curve_groups_v2.csv", group_rows, "match_tag", matches)
    _replace_rows(ROOT / "config" / "supported_curve_universe_v1.csv", supported_rows, "base_curve_tag", bases)
    _replace_rows(ROOT / "config" / "curve_anchor_overrides_v2.csv", override_rows, "base_curve_tag", bases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
