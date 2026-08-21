"""Rank live uncovered Grays sold lanes for the next retail-evidence scrape.

This is candidate discovery, not permission to publish a curve.  It groups the
live ``sold_cars.csv`` rows by exact vehicle identity fields, splits disconnected
year ranges, and removes lanes already represented by a live canonical tag.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
SOLD_PATH = ROOT / "CSV_data" / "scrapers" / "sold_cars.csv"
REJECTION_PATH = ROOT / "notes" / "curve_decisions" / "rejected_curve_lanes.csv"
OUTPUT_PATH = ROOT / "CSV_data" / "model_audit" / "grays_curve_targets_live.csv"


def _clean(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\*+\s*no reserve\s*\*+", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    # Identity fields arrive with inconsistent casing across scraper runs. Lane
    # grouping must not split otherwise identical vehicles into separate rows.
    return text.strip(" -").lower()


def _key(value: object) -> str:
    text = _clean(value).lower()
    # Treat compact badge/engine tokens (147TSI, 2.0i) the same as their
    # space-separated forms in readable rejection-ledger descriptions.
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _year_band_map(years: pd.Series) -> dict[int, str]:
    unique = sorted({int(year) for year in years.dropna()})
    if not unique:
        return {}
    bands: list[list[int]] = [[unique[0]]]
    for year in unique[1:]:
        if year - bands[-1][-1] > 2:
            bands.append([year])
        else:
            bands[-1].append(year)
    return {
        year: f"{band[0]}-{band[-1]}"
        for band in bands
        for year in band
    }


def _rejected_signatures() -> set[str]:
    if not REJECTION_PATH.exists():
        return set()
    rejected = pd.read_csv(REJECTION_PATH, low_memory=False)
    signatures: set[str] = set()
    for value in rejected["vehicle_lane"].dropna():
        signatures.add(_key(value))
    return signatures


def _looks_previously_assessed(row: pd.Series, signatures: set[str]) -> bool:
    candidate = _key(
        " ".join(
            str(row[column])
            for column in ("make", "model", "variant", "body_type", "fuel_type", "transmission")
        )
    )
    for signature in signatures:
        # Ledger entries are either readable lane descriptions or canonical-like
        # tags. Containment is deliberately strict: token-overlap matching marks
        # unrelated trims of the same common model as already assessed.
        if len(signature) >= 12 and (
            signature in candidate or candidate in signature
        ):
            return True
        signature_tokens = signature.split()
        if len(signature_tokens) >= 3:
            core_lane = " ".join(signature_tokens[:3])
            if len(core_lane) >= 10 and core_lane in candidate:
                return True
            numeric_core = " ".join(signature_tokens[: min(4, len(signature_tokens))])
            if len(core_lane) < 10 and len(numeric_core) >= 8 and numeric_core in candidate:
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-grays", type=int, default=6)
    args = parser.parse_args()

    sold = pd.read_csv(SOLD_PATH, low_memory=False)
    uncovered = sold[
        sold["canonical_tag"].fillna("").astype(str).str.upper().eq("UNCLASSIFIED")
        & ~sold["canonical_reason"].fillna("").isin(["[BAD_PARSE]", "[NON_VEHICLE]"])
    ].copy()

    identity = ["make", "model", "variant", "body_type", "transmission", "fuel_type"]
    for column in identity:
        uncovered[column] = uncovered[column].map(_clean)
    uncovered["year_numeric"] = pd.to_numeric(uncovered["year"], errors="coerce")
    uncovered["odometer_numeric"] = pd.to_numeric(
        uncovered["odometer_reading"], errors="coerce"
    )
    uncovered["price_numeric"] = pd.to_numeric(uncovered["price"], errors="coerce")
    uncovered["vehicle_id"] = uncovered["vin"].fillna("").astype(str).str.strip()
    missing_id = uncovered["vehicle_id"].eq("")
    uncovered.loc[missing_id, "vehicle_id"] = (
        uncovered.loc[missing_id, "url"].fillna("").astype(str)
    )

    band_frames: list[pd.DataFrame] = []
    for _, group in uncovered.groupby(identity, dropna=False):
        year_map = _year_band_map(group["year_numeric"])
        group = group.copy()
        group["year_band"] = group["year_numeric"].map(year_map).fillna("unknown")
        band_frames.append(group)
    banded = pd.concat(band_frames, ignore_index=True) if band_frames else uncovered

    worklist = (
        banded.groupby(identity + ["year_band", "canonical_reason"], dropna=False)
        .agg(
            grays_records=("url", "size"),
            unique_vehicles=("vehicle_id", "nunique"),
            year_min=("year_numeric", "min"),
            year_max=("year_numeric", "max"),
            median_odometer=("odometer_numeric", "median"),
            median_last_advertised_price=("price_numeric", "median"),
            latest_sale_date=("date_sold", "max"),
        )
        .reset_index()
    )
    worklist = worklist[worklist["unique_vehicles"] >= args.min_grays].copy()
    signatures = _rejected_signatures()
    worklist["previously_assessed"] = worklist.apply(
        _looks_previously_assessed, axis=1, signatures=signatures
    )
    worklist["recommended_action"] = worklist["canonical_reason"].map(
        {
            "[OUT_OF_SCOPE_YEAR]": "inspect existing curve year extension",
            "[DISALLOWED_VARIANT]": "inspect matcher or build distinct trim lane",
            "[AMBIG_BADGE]": "resolve badge/series then assess lane",
            "[AMBIG_FUEL]": "resolve fuel then assess lane",
            "[AMBIG_TRANS]": "resolve transmission then assess lane",
            "[OUT_OF_SCOPE]": "scrape exact private retail lane",
        }
    ).fillna("inspect classification failure")
    worklist["median_odometer"] = worklist["median_odometer"].round()
    worklist["median_last_advertised_price"] = worklist[
        "median_last_advertised_price"
    ].round()
    worklist = worklist.sort_values(
        ["previously_assessed", "unique_vehicles", "grays_records"],
        ascending=[True, False, False],
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    worklist.to_csv(OUTPUT_PATH, index=False)
    fresh = worklist[~worklist["previously_assessed"]]
    print(f"Live Grays sold rows: {len(sold):,}")
    print(f"Uncovered usable rows: {len(uncovered):,}")
    print(
        f"Candidate lanes with >= {args.min_grays} unique vehicles: "
        f"{len(worklist):,} ({len(fresh):,} not previously assessed)"
    )
    print(
        f"Fresh candidate auction records represented: "
        f"{int(fresh['unique_vehicles'].sum()):,}"
    )
    print()
    print(
        fresh[
            [
                "make",
                "model",
                "variant",
                "year_band",
                "fuel_type",
                "transmission",
                "unique_vehicles",
                "canonical_reason",
                "recommended_action",
            ]
        ]
        .head(30)
        .to_string(index=False)
    )
    print(f"\nWrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
