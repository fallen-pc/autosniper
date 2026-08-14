"""Build governed curves qualified by Carsales Apify batch 7WiZTPzBBDWBnn9kK."""

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
RETAIL_PATHS = [
    ROOT / "CSV_data" / "quality" / "carsales_apify_listings.csv",
    ROOT / "CSV_data" / "scrapers" / "carsales_grays_targets_batch2_20260805.csv",
    ROOT / "CSV_data" / "scrapers" / "carsales_grays_targets_batch4_20260813.csv",
]
SOLD_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    dict(key="ford_kuga_trend_tf", make="ford", model="kuga", retail=r"\btrend tf auto awd\b",
         sold=r"^awd trend tf$", years=(2013, 2014), anchors=[2013, 2014], body="wagon",
         body_aliases="wagon|suv", transmission="auto", sold_transmission="auto", fuel="diesel",
         engine=r"2\.0L", badge="awd trend", aliases="awd trend|trend|awd trend tf", series="tf",
         excluded="manual|petrol|hybrid|mkii|mk ii|titanium|ambiente|2wd",
         base="ford_kuga_awd-trend_tf_wagon_auto_diesel",
         match="ford_kuga_awd-trend_diesel_auto_wagon_tf"),
    dict(key="ford_kuga_titanium_tf", make="ford", model="kuga", retail=r"\btitanium tf auto awd\b",
         sold=r"^awd titanium tf$", years=(2013, 2014), anchors=[2013, 2014], body="wagon",
         body_aliases="wagon|suv", transmission="auto", sold_transmission="auto", fuel="diesel",
         engine=r"2\.0L", badge="awd titanium", aliases="awd titanium|titanium|awd titanium tf", series="tf",
         excluded="manual|petrol|hybrid|mkii|mk ii|trend|ambiente|2wd",
         base="ford_kuga_awd-titanium_tf_wagon_auto_diesel",
         match="ford_kuga_awd-titanium_diesel_auto_wagon_tf"),
    dict(key="mazda3_neo_bl_sedan", make="mazda", model="3", retail=r"\bneo bl .* auto\b",
         sold=r"^neo bl$", years=(2009, 2013), anchors=[2009, 2011, 2013], body="sedan",
         body_aliases="sedan", transmission="auto", sold_transmission="auto", fuel="petrol",
         engine=r"2\.0L", badge="neo", aliases="neo|neo bl", series="bl10f1",
         excluded="manual|diesel|hybrid|hatch|maxx|sp25|bm|bn|bk",
         base="mazda_3_neo_bl_sedan_auto_petrol",
         match="mazda_3_neo_petrol_auto_sedan_bl"),
    dict(key="holden_barina_tk_manual", make="holden", model="barina", retail=r"\btk manual\b",
         sold=r"^tk$", years=(2006, 2011), anchors=[2006, 2009, 2011], body="hatch",
         body_aliases="hatch|hatchback", transmission="manual", sold_transmission="manual", fuel="petrol",
         engine=r"1\.6L", badge="tk", aliases="tk", series="tk",
         excluded="automatic|diesel|hybrid|sedan|tm|xc|spark",
         base="holden_barina_tk_hatch_manual_petrol",
         match="holden_barina_tk_petrol_manual_hatch"),
]


def _replace(path: Path, rows: list[dict[str, object]], key: str, managed: set[str]) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key].astype(str).isin(managed)]
    incoming = pd.DataFrame(rows, columns=existing.columns)
    subset = [key, "series"] if path.name == "allowed_variants.csv" else [key]
    output = pd.concat([existing, incoming], ignore_index=True).drop_duplicates(subset, keep="last")
    write_dataframe_csv_atomic(output, path, index=False)


def _load_retail() -> pd.DataFrame:
    frames = [pd.read_csv(path, low_memory=False) for path in RETAIL_PATHS]
    retail = pd.concat(frames, ignore_index=True, sort=False)
    retail = retail[retail["seller_type"].fillna("").str.lower().eq("private")].copy()
    identity = retail["ad_id"].fillna("").astype(str).str.strip()
    retail["_identity"] = identity.mask(identity.eq(""), retail["url"].fillna("").astype(str))
    return retail.sort_values("scraped_at").drop_duplicates("_identity", keep="last")


def main() -> int:
    retail = _load_retail()
    sold = pd.read_csv(SOLD_PATH, low_memory=False)
    for frame, odo in ((retail, "odometer"), (sold, "odometer_reading")):
        frame["year_numeric"] = pd.to_numeric(frame["year"], errors="coerce")
        frame["odometer_numeric"] = pd.to_numeric(frame[odo], errors="coerce")
        frame["price_numeric"] = pd.to_numeric(frame["price"], errors="coerce")

    proposals, allowed, groups, supported, overrides = [], [], [], [], []
    for lane in LANES:
        y0, y1 = lane["years"]
        market = retail[
            retail["make"].fillna("").str.lower().eq(lane["make"])
            & retail["model"].fillna("").str.lower().eq(lane["model"])
            & retail["title"].fillna("").str.contains(lane["retail"], case=False, regex=True)
            & retail["engine"].fillna("").str.contains(lane["engine"], case=False, regex=True)
            & retail["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & retail["transmission"].fillna("").str.contains(lane["transmission"], case=False)
            & retail["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
            & retail["year_numeric"].between(y0, y1)
        ].copy()
        auction = sold[
            sold["make"].fillna("").str.lower().eq(lane["make"])
            & sold["model"].fillna("").str.lower().eq(lane["model"])
            & sold["variant"].fillna("").str.contains(lane["sold"], case=False, regex=True)
            & sold["year_numeric"].between(y0, y1)
            & sold["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & sold["transmission"].fillna("").str.contains(lane["sold_transmission"], case=False)
            & sold["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
        ].copy()
        market = market.dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        auction = auction.dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        ids = auction["vin"].fillna("").astype(str).str.strip()
        unique_demand = int(ids.mask(ids.eq(""), auction["url"]).nunique())
        if len(market) < 6 or unique_demand < 6:
            raise RuntimeError(f"Insufficient evidence for {lane['key']}: retail={len(market)} grays={unique_demand}")
        proposal, metadata = propose_curve_from_evidence(
            base_curve_tag=lane["base"], active_market_df=market, sold_df=auction,
            anchor_years=lane["anchors"], buckets=BUCKETS,
            evidence_source="private Carsales Apify run 7WiZTPzBBDWBnn9kK plus prior exact evidence",
        )
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        note = (f"Built from {metadata.active_rows_used} exact private Carsales rows "
                f"({metadata.active_rows_trimmed} outliers trimmed) and {unique_demand} unique live Grays vehicles; "
                "adjacent trims, generations, bodies, fuels, and transmissions remain separate.")
        allowed.append({"canonical_tag": lane["match"], "make": lane["make"], "model": lane["model"],
                        "body": lane["body"], "fuel": lane["fuel"], "transmission": lane["transmission"],
                        "badge": lane["badge"], "series": lane["series"], "allowed_badge_aliases": lane["aliases"],
                        "allowed_body_aliases": lane["body_aliases"], "excluded_keywords": lane["excluded"]})
        groups.append({"match_tag": lane["match"], "base_curve_tag": lane["base"], "group_status": "active", "reason": note})
        supported.append({"base_curve_tag": lane["base"], "make": lane["make"], "model": lane["model"],
                          "body": lane["body"], "fuel": lane["fuel"], "transmission": lane["transmission"],
                          "series": lane["series"], "status": "live_now", "priority": 1.0, "notes": note})
        overrides.append({"base_curve_tag": lane["base"], "anchor_years": "|".join(map(str, lane["anchors"])), "notes": note})
        print(f"{lane['key']}: retail={len(market)} used={metadata.active_rows_used} grays_unique={unique_demand}")

    curves_path = ROOT / "CSV_data" / "restricted" / "curves.csv"
    curves = pd.read_csv(curves_path)
    bases, matches = {lane["base"] for lane in LANES}, {lane["match"] for lane in LANES}
    curves = curves[~curves["canonical_tag"].isin(bases)]
    write_dataframe_csv_atomic(pd.concat([curves, *proposals], ignore_index=True), curves_path, index=False)
    _replace(ROOT / "config" / "allowed_variants.csv", allowed, "canonical_tag", matches)
    _replace(ROOT / "config" / "curve_groups_v2.csv", groups, "match_tag", matches)
    _replace(ROOT / "config" / "supported_curve_universe_v1.csv", supported, "base_curve_tag", bases)
    _replace(ROOT / "config" / "curve_anchor_overrides_v2.csv", overrides, "base_curve_tag", bases)
    snapshot_curve_version(
        curves_path, source="codex_grays_apify_batch4",
        change_summary="Added Ford Kuga Trend and Titanium TF diesel, Mazda 3 Neo BL sedan, and Holden Barina TK manual curves from exact private Carsales evidence backed by live Grays demand",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
