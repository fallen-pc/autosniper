"""Build the ninth governed curve batch from tracked accumulated evidence."""

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
SOLD_PATH = ROOT / "notes" / "curve_decisions" / "evidence" / "grays_batch9_exact_sold.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    dict(
        key="bmw_x5_sdrive25d_f15_auto_diesel",
        make="bmw", model="x5", title_pattern=r"\bX5\b.*\bsDrive25d\b.*\bF15\b",
        sold_variant="sdrive 25d f15", years=(2014, 2018),
        anchors=[2014, 2016, 2018], body="wagon", body_aliases="wagon|suv",
        transmission="auto", sold_transmission="automatic", fuel="diesel",
        engine=r"2\.0L", badge="sdrive25d",
        aliases="sdrive25d f15|sdrive 25d f15", series="f15",
        excluded="manual|petrol|hybrid|xdrive|30d|40d|m50|e70|g05",
        base="bmw_x5_sdrive25d_f15_wagon_auto_diesel",
        match="bmw_x5_sdrive25d_diesel_auto_wagon_f15",
    ),
    dict(
        key="nissan_micra_st_k13_auto_petrol",
        make="nissan", model="micra",
        title_pattern=r"\bMicra\b.*\bST\b(?!-L\b).*\bK13\b",
        sold_variant="st k13", years=(2011, 2016), anchors=[2011, 2014, 2016],
        body="hatch", body_aliases="hatch|hatchback", transmission="auto",
        sold_transmission="automatic", fuel="petrol", engine=r"1\.2L",
        badge="st", aliases="st k13", series="k13",
        excluded="manual|diesel|hybrid|st-l|st l|ti|k12",
        base="nissan_micra_st_k13_hatch_auto_petrol",
        match="nissan_micra_st_k13_petrol_auto_hatch",
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


def _select_market(retail: pd.DataFrame, lane: dict[str, object]) -> pd.DataFrame:
    year_min, year_max = lane["years"]
    return retail[
        retail["make"].fillna("").str.lower().eq(lane["make"])
        & retail["model"].fillna("").str.lower().eq(lane["model"])
        & retail["title"].fillna("").str.contains(
            lane["title_pattern"], case=False, regex=True
        )
        & retail["engine"].fillna("").str.contains(
            lane["engine"], case=False, regex=True
        )
        & retail["body_type"].fillna("").str.contains(
            lane["body_aliases"], case=False, regex=True
        )
        & retail["transmission"].fillna("").str.contains(
            lane["transmission"], case=False
        )
        & retail["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
        & retail["year_numeric"].between(year_min, year_max)
    ].dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])


def _select_auction(sold: pd.DataFrame, lane: dict[str, object]) -> pd.DataFrame:
    year_min, year_max = lane["years"]
    return sold[
        sold["make"].fillna("").str.lower().eq(lane["make"])
        & sold["model"].fillna("").str.lower().eq(lane["model"])
        & sold["variant"].fillna("").str.lower().eq(lane["sold_variant"])
        & sold["year_numeric"].between(year_min, year_max)
        & sold["body_type"].fillna("").str.contains(
            lane["body_aliases"], case=False, regex=True
        )
        & sold["transmission"].fillna("").str.contains(
            lane["sold_transmission"], case=False
        )
        & sold["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
    ].dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])


def main() -> int:
    retail = _load_retail()
    sold = pd.read_csv(SOLD_PATH, low_memory=False)
    for frame, odometer in ((retail, "odometer"), (sold, "odometer_reading")):
        frame["year_numeric"] = pd.to_numeric(frame["year"], errors="coerce")
        frame["odometer_numeric"] = pd.to_numeric(frame[odometer], errors="coerce")
        frame["price_numeric"] = pd.to_numeric(frame["price"], errors="coerce")

    proposals, allowed, groups, supported, overrides = [], [], [], [], []
    for lane in LANES:
        market = _select_market(retail, lane)
        auction = _select_auction(sold, lane)
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
            proposal[column] = (
                pd.to_numeric(proposal[column]) / 100
            ).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        note = (
            f"Built from {metadata.active_rows_used} exact private Carsales rows "
            f"({metadata.active_rows_trimmed} outliers trimmed) and {unique_demand} unique "
            "live Grays vehicles; adjacent trims, generations, bodies, transmissions, fuels, "
            "and drivetrains remain separate."
        )
        allowed.append({
            "canonical_tag": lane["match"], "make": lane["make"],
            "model": lane["model"], "body": lane["body"], "fuel": lane["fuel"],
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
            "base_curve_tag": lane["base"], "make": lane["make"],
            "model": lane["model"], "body": lane["body"], "fuel": lane["fuel"],
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
    bases = {lane["base"] for lane in LANES}
    matches = {lane["match"] for lane in LANES}
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
        curves_path, source="codex_grays_apify_batch9",
        change_summary=(
            "Added BMW X5 sDrive25d F15 and Nissan Micra ST K13 automatic curves "
            "from accumulated exact private Carsales evidence backed by live Grays demand"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
