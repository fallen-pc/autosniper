"""Build governed curve lanes recovered from Apify batch a0OgyhtH9v8YGHZDa."""

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
RETAIL_PATH = ROOT / "CSV_data" / "scrapers" / "carsales_grays_targets_batch3_20260809.csv"
SOLD_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    dict(
        key="mercedes_b200_w245", retail_make="mercedesbenz", retail_model="bclass",
        sold_make="mercedes", sold_model="benz", retail_badge=r"^b200$", sold_variant=r"^b200 w245$",
        years=(2006, 2011), anchors=[2006, 2008, 2011], body="hatch", body_aliases="hatch|hatchback",
        transmission="auto", sold_transmission=r"auto|cvt", fuel="petrol", engine=r"2\.0L",
        badge="b200", aliases="b200|b200 w245", series="w245",
        excluded="manual|diesel|hybrid|turbo|b180|b250|w246",
        base="mercedes_benz_b200_w245_hatch_auto_petrol",
        match="mercedes_benz_b200_petrol_auto_hatch_w245",
    ),
    dict(
        key="mercedes_c200_be_w204", retail_make="mercedesbenz", retail_model="cclass",
        sold_make="mercedes", sold_model="benz", retail_badge=r"^c200 blueefficiency$",
        sold_variant=r"^c200 be w204$", years=(2011, 2013), anchors=[2011, 2012, 2013],
        body="sedan", body_aliases="sedan|saloon", transmission="auto", sold_transmission=r"auto",
        fuel="petrol", engine=r"1\.8L", badge="c200 be", aliases="c200 be|c200 blueefficiency|c200 be w204",
        series="w204", excluded="manual|diesel|hybrid|coupe|wagon|c180|c250|c300|c63|kompressor|w205",
        base="mercedes_benz_c200-be_w204_sedan_auto_petrol",
        match="mercedes_benz_c200-be_petrol_auto_sedan_w204",
    ),
    dict(
        key="nissan_xtrail_st_t30", retail_make="nissan", retail_model="xtrail", sold_make="nissan",
        sold_model="x-trail", config_model="xtrail", retail_badge=r"^st$", sold_variant=r"^st \(4x4\) t30$",
        retail_title=r"\bt30\b", years=(2002, 2007), anchors=[2002, 2005, 2007],
        body="suv", body_aliases="suv|wagon", transmission="auto", sold_transmission=r"auto|cvt",
        fuel="petrol", engine=r"2\.5L", badge="st", aliases="st|st 4x4|st (4x4)", series="t30",
        excluded="manual|diesel|hybrid|st-l|stl|ti|ts|tl|t31|t32|t33",
        base="nissan_xtrail_st_t30_suv_auto_petrol",
        match="nissan_xtrail_st_petrol_auto_suv_t30",
    ),
]


def _replace(path: Path, rows: list[dict[str, object]], key: str, managed: set[str]) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key].astype(str).isin(managed)]
    incoming = pd.DataFrame(rows, columns=existing.columns)
    subset = [key, "series"] if path.name == "allowed_variants.csv" else [key]
    output = pd.concat([existing, incoming], ignore_index=True).drop_duplicates(subset, keep="last")
    write_dataframe_csv_atomic(output, path, index=False)


def main() -> int:
    retail = pd.read_csv(RETAIL_PATH, low_memory=False)
    retail = retail[retail["seller_type"].fillna("").str.lower().eq("private")].copy()
    sold = pd.read_csv(SOLD_PATH, low_memory=False)
    for frame, odo in ((retail, "odometer"), (sold, "odometer_reading")):
        frame["year_numeric"] = pd.to_numeric(frame["year"], errors="coerce")
        frame["odometer_numeric"] = pd.to_numeric(frame[odo], errors="coerce")
        frame["price_numeric"] = pd.to_numeric(frame["price"], errors="coerce")

    proposals, allowed, groups, supported, overrides = [], [], [], [], []
    for lane in LANES:
        y0, y1 = lane["years"]
        market = retail[
            retail["make"].fillna("").str.lower().eq(lane["retail_make"])
            & retail["model"].fillna("").str.lower().eq(lane["retail_model"])
            & retail["badge"].fillna("").str.contains(lane["retail_badge"], case=False, regex=True)
            & retail["engine"].fillna("").str.contains(lane["engine"], case=False, regex=True)
            & retail["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & retail["transmission"].fillna("").str.contains("auto", case=False)
            & retail["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
            & retail["year_numeric"].between(y0, y1)
        ].copy()
        if lane.get("retail_title"):
            market = market[market["title"].fillna("").str.contains(lane["retail_title"], case=False, regex=True)]
        auction = sold[
            sold["make"].fillna("").str.lower().eq(lane["sold_make"])
            & sold["model"].fillna("").str.lower().eq(lane["sold_model"])
            & sold["variant"].fillna("").str.contains(lane["sold_variant"], case=False, regex=True)
            & sold["year_numeric"].between(y0, y1)
            & sold["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & sold["transmission"].fillna("").str.contains(lane["sold_transmission"], case=False, regex=True)
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
            evidence_source="private Carsales Apify run a0OgyhtH9v8YGHZDa",
        )
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        note = (
            f"Built from {metadata.active_rows_used} exact private Carsales rows "
            f"({metadata.active_rows_trimmed} outliers trimmed) and {unique_demand} unique live Grays vehicles; "
            "adjacent trims, generations, bodies, fuels, and transmissions remain separate."
        )
        allowed.append({"canonical_tag": lane["match"], "make": lane["sold_make"],
                        "model": lane.get("config_model", lane["sold_model"]),
                        "body": lane["body"], "fuel": lane["fuel"], "transmission": lane["transmission"],
                        "badge": lane["badge"], "series": lane["series"], "allowed_badge_aliases": lane["aliases"],
                        "allowed_body_aliases": lane["body_aliases"], "excluded_keywords": lane["excluded"]})
        groups.append({"match_tag": lane["match"], "base_curve_tag": lane["base"], "group_status": "active", "reason": note})
        supported.append({"base_curve_tag": lane["base"], "make": lane["sold_make"],
                          "model": lane.get("config_model", lane["sold_model"]),
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
        curves_path, source="codex_grays_apify_batch3",
        change_summary="Added Mercedes B200 W245, Mercedes C200 BlueEFFICIENCY W204, and Nissan X-Trail ST T30 curves from recovered private Carsales evidence backed by live Grays demand",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
