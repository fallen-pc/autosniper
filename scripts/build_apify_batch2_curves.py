"""Build the governed curve lanes accepted from Apify batch 7WqoauuNvqzoVM5jO."""

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
RETAIL_PATH = ROOT / "CSV_data" / "scrapers" / "carsales_grays_targets_batch2_20260805.csv"
SOLD_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    dict(key="bmw_x5_xdrive30d_f15", make="BMW", model="X5", retail=r"^xDrive30d F15 Auto 4x4",
         sold=r"^xdrive 30d f15$", years=(2013, 2018), anchors=[2013, 2015, 2018],
         body="wagon", body_aliases="wagon|suv", transmission="auto", fuel="diesel",
         engine=r"3\.0L", badge="xdrive30d", aliases="xdrive30d|xdrive 30d|xdrive 30d f15",
         series="f15", excluded="manual|petrol|hybrid|sdrive|25d|40d|m50|e70|g05",
         base="bmw_x5_xdrive30d_f15_wagon_auto_diesel",
         match="bmw_x5_xdrive30d_diesel_auto_wagon_f15"),
    dict(key="audi_a4_18tfsi_b8", make="Audi", model="A4", retail=r"^Auto(?: MY\d+)?$",
         sold=r"^1\.8 tfsi b8$", years=(2008, 2015), anchors=[2008, 2011, 2015],
         body="sedan", body_aliases="sedan|saloon", transmission="auto", fuel="petrol",
         sold_transmission=r"cvt|automatic",
         engine=r"1\.8L", badge="1.8 tfsi", aliases="1.8 tfsi|1 8 tfsi",
         series="b8", excluded="manual|diesel|hybrid|quattro|s line|wagon|avant|2.0|1.4",
         base="audi_a4_1.8-tfsi_b8_sedan_auto_petrol",
         match="audi_a4_1.8-tfsi_petrol_auto_sedan_b8"),
    dict(key="mazda3_neo_bl", make="Mazda", model="3", retail=r"^Neo BL .* Auto",
         sold=r"^neo bl$", years=(2009, 2013), anchors=[2009, 2011, 2013],
         body="hatch", body_aliases="hatch|hatchback", transmission="auto", fuel="petrol",
         engine=r"2\.0L", badge="neo", aliases="neo|neo bl",
         series="bl10f1", excluded="manual|diesel|hybrid|sedan|maxx|sp25|bm|bn|bk",
         base="mazda_3_neo_bl_hatch_auto_petrol",
         match="mazda_3_neo_petrol_auto_hatch_bl"),
    dict(key="jeep_cherokee_sport_kl9", make="Jeep", model="Cherokee", retail=r"^Sport Auto(?: MY\d+)?$",
         sold=r"^sport 4x2 kl 9$", years=(2014, 2016), anchors=[2014, 2015, 2016],
         body="wagon", body_aliases="wagon|suv", transmission="auto", fuel="petrol",
         engine=r"2\.4L", badge="sport 4x2", aliases="sport 4x2|sport 4x2 kl 9|sport",
         series="kl9", excluded="manual|diesel|hybrid|4x4|awd|limited|longitude|trailhawk|3.2",
         base="jeep_cherokee_sport-4x2_kl9_wagon_auto_petrol",
         match="jeep_cherokee_sport-4x2_petrol_auto_wagon_kl9"),
    dict(key="nissan_micra_k12", make="Nissan", model="Micra", retail=r"^K12 Auto",
         sold=r"^k12$", years=(2007, 2010), anchors=[2007, 2009, 2010],
         body="hatch", body_aliases="hatch|hatchback", transmission="auto", fuel="petrol",
         engine=r"1\.4L", badge="k12", aliases="k12",
         series="k12", excluded="manual|diesel|hybrid|k13|st|ti",
         base="nissan_micra_k12_hatch_auto_petrol",
         match="nissan_micra_k12_petrol_auto_hatch"),
]


def _replace(path: Path, rows: list[dict[str, object]], key: str, managed: set[str]) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key].astype(str).isin(managed)]
    incoming = pd.DataFrame(rows, columns=existing.columns)
    subset = [key, "series"] if path.name == "allowed_variants.csv" else [key]
    write_dataframe_csv_atomic(
        pd.concat([existing, incoming], ignore_index=True).drop_duplicates(subset, keep="last"),
        path, index=False,
    )


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
            retail["make"].fillna("").str.lower().eq(lane["make"].lower())
            & retail["model"].fillna("").str.lower().eq(lane["model"].lower())
            & retail["variant"].fillna("").str.contains(lane["retail"], case=False, regex=True)
            & retail["engine"].fillna("").str.contains(lane["engine"], case=False, regex=True)
            & retail["year_numeric"].between(y0, y1)
        ].copy()
        if lane["body"] == "hatch":
            market = market[market["body_type"].fillna("").str.contains("hatch", case=False)]
        auction = sold[
            sold["make"].fillna("").str.lower().eq(lane["make"].lower())
            & sold["model"].fillna("").str.lower().eq(lane["model"].lower())
            & sold["variant"].fillna("").str.contains(lane["sold"], case=False, regex=True)
            & sold["year_numeric"].between(y0, y1)
            & sold["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & sold["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
        ].copy()
        auction = auction[
            auction["transmission"].fillna("").str.contains(
                lane.get("sold_transmission", "auto"), case=False, regex=True
            )
        ]
        market = market.dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        auction = auction.dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        vehicle_ids = auction["vin"].fillna("").astype(str).str.strip()
        unique_demand = int(vehicle_ids.mask(vehicle_ids.eq(""), auction["url"]).nunique())
        if len(market) < 6 or unique_demand < 6:
            raise RuntimeError(f"Insufficient evidence for {lane['key']}: retail={len(market)} grays={unique_demand}")
        proposal, metadata = propose_curve_from_evidence(
            base_curve_tag=lane["base"], active_market_df=market, sold_df=auction,
            anchor_years=lane["anchors"], buckets=BUCKETS,
            evidence_source="private Carsales Apify run 7WqoauuNvqzoVM5jO",
        )
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        note = (
            f"Built from {metadata.active_rows_used} exact private Carsales rows "
            f"({metadata.active_rows_trimmed} outliers trimmed) and {unique_demand} unique live Grays vehicles; "
            "adjacent generations, trims, bodies, fuels, transmissions, and drivetrains remain separate."
        )
        allowed.append({"canonical_tag": lane["match"], "make": lane["make"].lower(), "model": lane["model"].lower(),
                        "body": lane["body"], "fuel": lane["fuel"], "transmission": lane["transmission"],
                        "badge": lane["badge"], "series": lane["series"], "allowed_badge_aliases": lane["aliases"],
                        "allowed_body_aliases": lane["body_aliases"], "excluded_keywords": lane["excluded"]})
        groups.append({"match_tag": lane["match"], "base_curve_tag": lane["base"], "group_status": "active", "reason": note})
        supported.append({"base_curve_tag": lane["base"], "make": lane["make"].lower(), "model": lane["model"].lower(),
                          "body": lane["body"], "fuel": lane["fuel"], "transmission": lane["transmission"],
                          "series": lane["series"], "status": "live_now", "priority": 1.0, "notes": note})
        overrides.append({"base_curve_tag": lane["base"], "anchor_years": "|".join(map(str, lane["anchors"])), "notes": note})
        print(f"{lane['key']}: retail={len(market)} used={metadata.active_rows_used} grays_unique={unique_demand}")

    curves_path = ROOT / "CSV_data" / "restricted" / "curves.csv"
    curves = pd.read_csv(curves_path)
    bases, matches = {lane["base"] for lane in LANES}, {lane["match"] for lane in LANES}
    retired_bases = {"audi_a4_1.8-tfsi_b8_sedan_cvt_petrol"}
    retired_matches = {"audi_a4_1.8-tfsi_petrol_cvt_sedan_b8"}
    curves = curves[~curves["canonical_tag"].isin(bases | retired_bases)]
    write_dataframe_csv_atomic(pd.concat([curves, *proposals], ignore_index=True), curves_path, index=False)
    _replace(ROOT / "config" / "allowed_variants.csv", allowed, "canonical_tag", matches | retired_matches)
    _replace(ROOT / "config" / "curve_groups_v2.csv", groups, "match_tag", matches | retired_matches)
    _replace(ROOT / "config" / "supported_curve_universe_v1.csv", supported, "base_curve_tag", bases | retired_bases)
    _replace(ROOT / "config" / "curve_anchor_overrides_v2.csv", overrides, "base_curve_tag", bases | retired_bases)
    snapshot_curve_version(
        curves_path,
        source="codex_grays_apify_batch2",
        change_summary=(
            "Added BMW X5 xDrive30d F15, Audi A4 1.8 TFSI B8 CVT, Mazda 3 Neo BL, "
            "Jeep Cherokee Sport 4x2 KL9, and Nissan Micra K12 curves from exact private "
            "Carsales evidence backed by live Grays demand"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
