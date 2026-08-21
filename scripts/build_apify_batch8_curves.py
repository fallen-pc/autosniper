"""Build the eighth governed curve batch from accumulated exact Carsales evidence."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from shared.curve_builder_v2 import propose_curve_from_evidence
from shared.curve_versioning import snapshot_curve_version
from shared.curves import CURVE_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
RETAIL_PATHS = sorted(
    (ROOT / "CSV_data" / "scrapers").glob("carsales_grays_targets_batch*.csv")
)
SOLD_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    dict(
        key="mazda_3_sp25_bl_sedan_auto",
        make="mazda", model="3", title_pattern=r"\bSP25\b.*\bBL\b",
        sold_variant="sp25 bl", years=(2009, 2012), anchors=[2009, 2011, 2012],
        body="sedan", body_aliases="sedan|saloon", transmission="auto",
        sold_transmission="automatic", fuel="petrol", engine=r"2\.5L",
        badge="sp25", aliases="sp25", series="bl10f1",
        excluded=(
            "manual|diesel|hybrid|hatch|wagon|suv|neo|maxx|maxx sport|touring|"
            "astina|mps|bk|bm|bn"
        ),
        base="mazda_3_sp25_bl_sedan_auto_petrol",
        match="mazda_3_sp25_petrol_auto_sedan_bl",
    ),
]


def _replace(path: Path, rows: list[dict[str, object]], key: str, managed: set[str]) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key].astype(str).isin(managed)]
    incoming = pd.DataFrame(rows, columns=existing.columns)
    subset = [key, "series"] if path.name == "allowed_variants.csv" else [key]
    output = pd.concat([existing, incoming], ignore_index=True).drop_duplicates(
        subset, keep="last"
    )
    write_dataframe_csv_atomic(output, path, index=False)


def _load_retail() -> pd.DataFrame:
    retail = pd.concat(
        [pd.read_csv(path, low_memory=False) for path in RETAIL_PATHS],
        ignore_index=True, sort=False,
    )
    retail = retail[retail["seller_type"].fillna("").str.lower().eq("private")].copy()
    identity = retail["ad_id"].fillna("").astype(str).str.strip()
    retail["_identity"] = identity.mask(
        identity.eq(""), retail["url"].fillna("").astype(str)
    )
    return retail.sort_values("scraped_at").drop_duplicates("_identity", keep="last")


def main() -> int:
    retail = _load_retail()
    sold = pd.read_csv(SOLD_PATH, low_memory=False)
    for frame, odometer in ((retail, "odometer"), (sold, "odometer_reading")):
        frame["year_numeric"] = pd.to_numeric(frame["year"], errors="coerce")
        frame["odometer_numeric"] = pd.to_numeric(frame[odometer], errors="coerce")
        frame["price_numeric"] = pd.to_numeric(frame["price"], errors="coerce")

    proposals, allowed, groups, supported, overrides = [], [], [], [], []
    for lane in LANES:
        y0, y1 = lane["years"]
        market = retail[
            retail["make"].fillna("").str.lower().eq(lane["make"])
            & retail["model"].fillna("").str.lower().eq(lane["model"])
            & retail["title"].fillna("").str.contains(
                lane["title_pattern"], case=False, regex=True
            )
            & retail["engine"].fillna("").str.contains(lane["engine"], case=False, regex=True)
            & retail["body_type"].fillna("").str.contains(
                lane["body_aliases"], case=False, regex=True
            )
            & retail["transmission"].fillna("").str.contains(
                lane["transmission"], case=False
            )
            & retail["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
            & retail["year_numeric"].between(y0, y1)
        ].dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        auction = sold[
            sold["make"].fillna("").str.lower().eq(lane["make"])
            & sold["model"].fillna("").str.lower().eq(lane["model"])
            & sold["variant"].fillna("").str.lower().eq(lane["sold_variant"])
            & sold["year_numeric"].between(y0, y1)
            & sold["body_type"].fillna("").str.contains(
                lane["body_aliases"], case=False, regex=True
            )
            & sold["transmission"].fillna("").str.contains(
                lane["sold_transmission"], case=False
            )
            & sold["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
        ].dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        identities = auction["vin"].fillna("").astype(str).str.strip()
        unique_demand = int(
            identities.mask(identities.eq(""), auction["url"].fillna("").astype(str)).nunique()
        )
        if len(market) < 6 or unique_demand < 6:
            raise RuntimeError(
                f"Insufficient evidence for {lane['key']}: retail={len(market)} "
                f"grays={unique_demand}"
            )
        proposal, metadata = propose_curve_from_evidence(
            base_curve_tag=lane["base"], active_market_df=market, sold_df=auction,
            anchor_years=lane["anchors"], buckets=BUCKETS,
            evidence_source="tracked accumulated exact private Carsales evidence through batch 5",
        )
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        note = (
            f"Built from {metadata.active_rows_used} exact private Carsales rows "
            f"({metadata.active_rows_trimmed} outliers trimmed) and {unique_demand} unique "
            "live Grays vehicles; adjacent trims, generations, bodies, transmissions, fuels, "
            "and drivetrains remain separate."
        )
        allowed.append({
            "canonical_tag": lane["match"], "make": lane["make"], "model": lane["model"],
            "body": lane["body"], "fuel": lane["fuel"],
            "transmission": lane["transmission"], "badge": lane["badge"],
            "series": lane["series"], "allowed_badge_aliases": lane["aliases"],
            "allowed_body_aliases": lane["body_aliases"],
            "excluded_keywords": lane["excluded"],
        })
        groups.append({
            "match_tag": lane["match"], "base_curve_tag": lane["base"],
            "group_status": "active", "reason": note,
        })
        supported.append({
            "base_curve_tag": lane["base"], "make": lane["make"], "model": lane["model"],
            "body": lane["body"], "fuel": lane["fuel"],
            "transmission": lane["transmission"], "series": lane["series"],
            "status": "live_now", "priority": 1.0, "notes": note,
        })
        overrides.append({
            "base_curve_tag": lane["base"],
            "anchor_years": "|".join(map(str, lane["anchors"])), "notes": note,
        })
        print(
            f"{lane['key']}: retail={len(market)} used={metadata.active_rows_used} "
            f"grays_unique={unique_demand}"
        )

    curves_path = ROOT / "CSV_data" / "restricted" / "curves.csv"
    curves = pd.read_csv(curves_path)
    bases, matches = {lane["base"] for lane in LANES}, {lane["match"] for lane in LANES}
    curves = curves[~curves["canonical_tag"].isin(bases)]
    write_dataframe_csv_atomic(
        pd.concat([curves, *proposals], ignore_index=True), curves_path, index=False
    )
    _replace(ROOT / "config" / "allowed_variants.csv", allowed, "canonical_tag", matches)
    _replace(ROOT / "config" / "curve_groups_v2.csv", groups, "match_tag", matches)
    _replace(
        ROOT / "config" / "supported_curve_universe_v1.csv",
        supported, "base_curve_tag", bases,
    )
    _replace(
        ROOT / "config" / "curve_anchor_overrides_v2.csv",
        overrides, "base_curve_tag", bases,
    )
    snapshot_curve_version(
        curves_path, source="codex_grays_apify_batch8",
        change_summary=(
            "Added Mazda 3 SP25 BL automatic sedan curve from accumulated exact private "
            "Carsales evidence backed by live Grays demand"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
