"""Build governed curves qualified by Carsales Apify batch Nu8coMBuDLXOwOEUX."""

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
    *sorted((ROOT / "CSV_data" / "scrapers").glob("carsales_grays_targets_batch*.csv")),
]
SOLD_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    dict(key="hyundai_i45_active_yf", make="hyundai", model="i45", retail=r"^Active I45$",
         sold=r"^active yf$", years=(2010, 2012), anchors=[2010, 2011, 2012], body="sedan",
         body_aliases="sedan", transmission="automatic", sold_transmission="auto", fuel="petrol",
         engine=r"2\.4L", badge="active", aliases="active|active yf", series="yf",
         excluded="manual|diesel|hybrid|premium|elite|2.0l",
         base="hyundai_i45_active_yf_sedan_auto_petrol",
         match="hyundai_i45_active_petrol_auto_sedan_yf"),
    dict(key="nissan_dualis_st_j10", make="nissan", model="dualis", retail=r"^St Dualis$",
         sold=r"^st j10$", years=(2009, 2013), anchors=[2009, 2011, 2013], body="wagon",
         body_aliases="wagon|suv", transmission="automatic", sold_transmission="cvt", fuel="petrol",
         engine=r"2\.0L", badge="st", aliases="st|st j10", series="j10",
         excluded="manual|diesel|hybrid|+2|j107|ti|ts|awd|4x4",
         base="nissan_dualis_st_j10_wagon_cvt_petrol",
         match="nissan_dualis_st_petrol_cvt_wagon_j10"),
    dict(key="ford_mondeo_lx_tdci_mc", make="ford", model="mondeo", retail=r"^Lx Tdci Mondeo$",
         sold=r"^lx tdci mc$", years=(2011, 2014), anchors=[2011, 2012, 2014], body="wagon",
         body_aliases="wagon", transmission="automatic", sold_transmission="auto", fuel="diesel",
         engine=r"2\.0L", badge="lx tdci", aliases="lx tdci|lx tdci mc", series="mc",
         excluded="manual|petrol|hybrid|hatch|sedan|ambiente|zetec|titanium|md|ma|mb",
         base="ford_mondeo_lx-tdci_mc_wagon_auto_diesel",
         match="ford_mondeo_lx-tdci_diesel_auto_wagon_mc"),
    dict(key="volkswagen_golf_gti_vi", make="volkswagen", model="golf", retail=r"^Gti Golf$",
         sold=r"^gti a6$", years=(2009, 2012), anchors=[2009, 2011, 2012], body="hatch",
         body_aliases="hatch|hatchback", transmission="automatic", sold_transmission="auto", fuel="petrol",
         engine=r"2\.0L", badge="gti", aliases="gti|gti a6|gti vi", series="vi",
         excluded="manual|diesel|hybrid|wagon|golf r|r32|comfortline|trendline|highline|vii|7|a7|v|a5",
         base="volkswagen_golf_gti_vi_hatch_auto_petrol",
         match="volkswagen_golf_gti_petrol_auto_hatch_vi"),
    dict(key="volvo_xc60_t5_dz", make="volvo", model="xc60", retail=r"^T5 Xc60$",
         sold=r"^t5$", years=(2011, 2013), anchors=[2011, 2012, 2013], body="wagon",
         body_aliases="wagon|suv", transmission="automatic", sold_transmission="auto", fuel="petrol",
         engine=r"2\.0L", badge="t5", aliases="t5", series="dz",
         excluded="manual|diesel|hybrid|teknik|luxury|kinetic|r-design|r design|momentum|inscription|uz|t6|d4|d5",
         base="volvo_xc60_t5_dz_wagon_auto_petrol",
         match="volvo_xc60_t5_petrol_auto_wagon_dz"),
]


def _replace(path: Path, rows: list[dict[str, object]], key: str, managed: set[str]) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key].astype(str).isin(managed)]
    incoming = pd.DataFrame(rows, columns=existing.columns)
    subset = [key, "series"] if path.name == "allowed_variants.csv" else [key]
    output = pd.concat([existing, incoming], ignore_index=True).drop_duplicates(subset, keep="last")
    write_dataframe_csv_atomic(output, path, index=False)


def _load_retail() -> pd.DataFrame:
    retail = pd.concat([pd.read_csv(path, low_memory=False) for path in RETAIL_PATHS], ignore_index=True, sort=False)
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
        series_match = retail["series"].fillna("").str.contains(lane["series"], case=False, regex=True)
        if lane["key"] == "ford_mondeo_lx_tdci_mc":
            series_match = retail["title"].fillna("").str.contains(r"\bMC\b", case=False, regex=True)
        market = retail[
            retail["make"].fillna("").str.lower().eq(lane["make"])
            & retail["model"].fillna("").str.lower().eq(lane["model"])
            & retail["variant"].fillna("").str.contains(lane["retail"], case=False, regex=True)
            & series_match
            & retail["engine"].fillna("").str.contains(lane["engine"], case=False, regex=True)
            & retail["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & retail["transmission"].fillna("").str.contains(lane["transmission"], case=False)
            & retail["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
            & retail["year_numeric"].between(y0, y1)
        ].copy()
        if lane["key"] == "nissan_dualis_st_j10":
            market = market[~market["title"].fillna("").str.contains(r"\+2", regex=True)]
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
            evidence_source="private Carsales Apify run Nu8coMBuDLXOwOEUX plus prior exact evidence",
        )
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        note = (f"Built from {metadata.active_rows_used} exact private Carsales rows "
                f"({metadata.active_rows_trimmed} outliers trimmed) and {unique_demand} unique live Grays vehicles; "
                "adjacent trims, generations, bodies, fuels, transmissions, and drivetrains remain separate.")
        allowed.append({"canonical_tag": lane["match"], "make": lane["make"], "model": lane["model"],
                        "body": lane["body"], "fuel": lane["fuel"], "transmission": "auto" if lane["transmission"] == "automatic" else lane["transmission"],
                        "badge": lane["badge"], "series": lane["series"], "allowed_badge_aliases": lane["aliases"],
                        "allowed_body_aliases": lane["body_aliases"], "excluded_keywords": lane["excluded"]})
        groups.append({"match_tag": lane["match"], "base_curve_tag": lane["base"], "group_status": "active", "reason": note})
        supported.append({"base_curve_tag": lane["base"], "make": lane["make"], "model": lane["model"],
                          "body": lane["body"], "fuel": lane["fuel"], "transmission": "auto", "series": lane["series"],
                          "status": "live_now", "priority": 1.0, "notes": note})
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
        curves_path, source="codex_grays_apify_batch5",
        change_summary="Added Hyundai i45 Active YF, Nissan Dualis ST J10, Ford Mondeo LX TDCi MC, Volkswagen Golf GTI VI, and Volvo XC60 T5 DZ curves from exact private Carsales evidence backed by live Grays demand",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
