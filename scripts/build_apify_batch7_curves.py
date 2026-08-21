"""Build the seventh governed curve batch from accumulated exact Carsales evidence."""

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
    ROOT
    / "notes"
    / "curve_decisions"
    / "evidence"
    / "carsales_apify_batch7_exact_private.csv"
]
SOLD_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
BUCKETS = [30000, 60000, 100000, 150000, 200000, 225000, 300000]
LANES = [
    dict(
        key="hyundai_i30_sx_fd_manual",
        make="hyundai", model="i30", retail_badge="sx", retail_series="fd",
        sold_variant="sx fd", years=(2008, 2012), anchors=[2008, 2010, 2012],
        body="hatch", body_aliases="hatch|hatchback", transmission="manual",
        sold_transmission="manual", fuel="petrol", engine=r"1\.[6-9]L|2\.0L",
        badge="sx", aliases="sx", series="fd",
        excluded=(
            "automatic|diesel|hybrid|sedan|tourer|wagon|active|elite|premium|"
            "trophy|se|sr|sr premium|n line|n-line|gd|pd"
        ),
        base="hyundai_i30_sx_fd_hatch_manual_petrol",
        match="hyundai_i30_sx_petrol_manual_hatch_fd",
    ),
    dict(
        key="toyota_camry_csi_sxv20r",
        make="toyota", model="camry", retail_badge="csi", retail_series="sxv20r",
        sold_variant="csi sxv20r", years=(1998, 2002), anchors=[1998, 2000, 2002],
        body="sedan", body_aliases="sedan|saloon", transmission="auto",
        sold_transmission="automatic", fuel="petrol", engine=r"2\.2L",
        badge="csi", aliases="csi", series="sxv20r",
        excluded=(
            "manual|diesel|hybrid|wagon|hatch|suv|altise|csx|ateva|sportivo|"
            "vienta|acv36r|mcv36r|acv40r|asv50r|asv70r"
        ),
        base="toyota_camry_csi_sxv20r_sedan_auto_petrol",
        match="toyota_camry_csi_petrol_auto_sedan_sxv20r",
    ),
    dict(
        key="ford_falcon_xt_ba",
        make="ford", model="falcon", retail_badge="xt", retail_series="ba",
        sold_variant="xt ba", years=(2002, 2004), anchors=[2002, 2003, 2004],
        body="sedan", body_aliases="sedan|saloon", transmission="auto",
        sold_transmission="automatic", fuel="petrol", engine=r"4\.0L",
        badge="xt", aliases="xt", series="ba",
        excluded=(
            "manual|diesel|hybrid|lpg|gas|dual fuel|ute|wagon|xr6|xr8|g6|g6e|"
            "fairmont|fairlane|bf|fg|fg-x|fgx"
        ),
        base="ford_falcon_xt_ba_sedan_auto_petrol",
        match="ford_falcon_xt_petrol_auto_sedan_ba",
    ),
    dict(
        key="toyota_camry_sportivo_acv40r",
        make="toyota", model="camry", retail_badge="sportivo", retail_series="acv40r",
        sold_variant="sportivo acv40r", years=(2006, 2009), anchors=[2006, 2008, 2009],
        body="sedan", body_aliases="sedan|saloon", transmission="auto",
        sold_transmission="automatic", fuel="petrol", engine=r"2\.4L",
        badge="sportivo", aliases="sportivo", series="acv40r",
        excluded=(
            "manual|diesel|hybrid|wagon|hatch|suv|altise|csi|csx|ateva|vienta|"
            "acv36r|mcv36r|asv50r|asv70r"
        ),
        base="toyota_camry_sportivo_acv40r_sedan_auto_petrol",
        match="toyota_camry_sportivo_petrol_auto_sedan_acv40r",
    ),
]


def _replace(path: Path, rows: list[dict[str, object]], key: str, managed: set[str]) -> None:
    existing = pd.read_csv(path, low_memory=False)
    existing = existing[~existing[key].astype(str).isin(managed)]
    incoming = pd.DataFrame(rows, columns=existing.columns)
    subset = [key, "series"] if path.name == "allowed_variants.csv" else [key]
    output = pd.concat([existing, incoming], ignore_index=True).drop_duplicates(subset, keep="last")
    write_dataframe_csv_atomic(output, path, index=False)


def _load_retail() -> pd.DataFrame:
    retail = pd.concat(
        [pd.read_csv(path, low_memory=False) for path in RETAIL_PATHS],
        ignore_index=True, sort=False,
    )
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
            & retail["badge"].fillna("").str.lower().eq(lane["retail_badge"])
            & retail["series"].fillna("").str.lower().eq(lane["retail_series"])
            & retail["engine"].fillna("").str.contains(lane["engine"], case=False, regex=True)
            & retail["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & retail["transmission"].fillna("").str.contains(lane["transmission"], case=False)
            & retail["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
            & retail["year_numeric"].between(y0, y1)
        ].copy()
        auction = sold[
            sold["make"].fillna("").str.lower().eq(lane["make"])
            & sold["model"].fillna("").str.lower().eq(lane["model"])
            & sold["variant"].fillna("").str.lower().eq(lane["sold_variant"])
            & sold["year_numeric"].between(y0, y1)
            & sold["body_type"].fillna("").str.contains(lane["body_aliases"], case=False, regex=True)
            & sold["transmission"].fillna("").str.contains(lane["sold_transmission"], case=False)
            & sold["fuel_type"].fillna("").str.contains(lane["fuel"], case=False)
        ].copy()
        market = market.dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        auction = auction.dropna(subset=["year_numeric", "odometer_numeric", "price_numeric"])
        identities = auction["vin"].fillna("").astype(str).str.strip()
        unique_demand = int(identities.mask(identities.eq(""), auction["url"]).nunique())
        if len(market) < 6 or unique_demand < 6:
            raise RuntimeError(
                f"Insufficient evidence for {lane['key']}: retail={len(market)} grays={unique_demand}"
            )
        proposal, metadata = propose_curve_from_evidence(
            base_curve_tag=lane["base"], active_market_df=market, sold_df=auction,
            anchor_years=lane["anchors"], buckets=BUCKETS,
            evidence_source="tracked Batch 7 exact private Carsales evidence extract",
        )
        for column in ("price_low", "price_mid", "price_high"):
            proposal[column] = (pd.to_numeric(proposal[column]) / 100).round().astype(int) * 100
        proposals.append(proposal[list(CURVE_COLUMNS)])
        note = (
            f"Built from {metadata.active_rows_used} exact private Carsales rows "
            f"({metadata.active_rows_trimmed} outliers trimmed) and {unique_demand} unique live Grays vehicles; "
            "adjacent trims, generations, bodies, transmissions, fuels, and drivetrains remain separate."
        )
        allowed.append({
            "canonical_tag": lane["match"], "make": lane["make"], "model": lane["model"],
            "body": lane["body"], "fuel": lane["fuel"], "transmission": lane["transmission"],
            "badge": lane["badge"], "series": lane["series"],
            "allowed_badge_aliases": lane["aliases"], "allowed_body_aliases": lane["body_aliases"],
            "excluded_keywords": lane["excluded"],
        })
        groups.append({"match_tag": lane["match"], "base_curve_tag": lane["base"],
                       "group_status": "active", "reason": note})
        supported.append({"base_curve_tag": lane["base"], "make": lane["make"], "model": lane["model"],
                          "body": lane["body"], "fuel": lane["fuel"],
                          "transmission": lane["transmission"], "series": lane["series"],
                          "status": "live_now", "priority": 1.0, "notes": note})
        overrides.append({"base_curve_tag": lane["base"],
                          "anchor_years": "|".join(map(str, lane["anchors"])), "notes": note})
        print(
            f"{lane['key']}: retail={len(market)} used={metadata.active_rows_used} "
            f"grays_unique={unique_demand}"
        )

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
        curves_path, source="codex_grays_apify_batch7",
        change_summary=(
            "Added Hyundai i30 SX FD manual, Toyota Camry CSi SXV20R, Ford Falcon XT BA, "
            "and Toyota Camry Sportivo ACV40R curves from accumulated exact private "
            "Carsales evidence backed by live Grays demand"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
