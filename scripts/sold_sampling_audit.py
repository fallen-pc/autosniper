"""Stratified sampling audit for the un-rescraped sold history.

The newest ~1,431 sold rows were re-scraped and price-repaired; the older
~15.7k rows have never been verified. Re-scraping all of them is slow, so this
tool audits a seeded random sample per position band instead:

1. plan   -> draw the sample and write a manifest CSV (no network needed)
2.        -> re-scrape just the sampled URLs on the scraping machine:
             python scripts/rebuild_sold_dataset.py \
                 --source CSV_data/archives/sold_audit_sample.csv \
                 --output CSV_data/archives/sold_audit_rescrape.csv
3. report -> compare sampled prices against the re-scrape and write per-band
             mismatch rates with a clean/suspect verdict per band

Bands with zero mismatches get a rule-of-three upper bound (3/n) on the true
mismatch rate; suspect bands should be queued for a targeted rebuild via
rebuild_sold_dataset.py --offset chunking, mirroring the 2026-05 repair.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from scripts.atomic_csv import write_dataframe_csv_atomic
from scripts.repair_sold_prices_from_rescrape import _normalize_url, _prices_differ, parse_price
from shared.data_loader import dataset_path

DEFAULT_SOURCE = dataset_path("sold_cars.csv")
DEFAULT_RESCRAPED = dataset_path("sold_cars_rescraped.csv")
DEFAULT_SAMPLE = dataset_path("archives/sold_audit_sample.csv")
DEFAULT_AUDIT_RESCRAPE = dataset_path("archives/sold_audit_rescrape.csv")
DEFAULT_REPORT = dataset_path("archives/sold_audit_report.csv")

MISMATCH_SUSPECT_THRESHOLD = 0.05  # >=5% sampled mismatches marks a band suspect


def _load_urls_lower(path: Path) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path, low_memory=False)
    if "url" not in df.columns:
        return set()
    return {_normalize_url(u) for u in df["url"].dropna()}


def build_sample(
    source: Path,
    rescraped: Path,
    *,
    per_band: int,
    band_size: int,
    seed: int,
) -> pd.DataFrame:
    sold = pd.read_csv(source, low_memory=False)
    if "url" not in sold.columns:
        raise RuntimeError("Source dataset must include a 'url' column.")
    sold = sold.reset_index(drop=True)
    source_len = len(sold)
    sold["source_from_end"] = source_len - 1 - sold.index
    sold["band"] = (sold["source_from_end"] // band_size) * band_size

    already = _load_urls_lower(rescraped)
    sold["_url_norm"] = sold["url"].map(_normalize_url)
    eligible = sold[
        sold["url"].astype(str).str.startswith("http", na=False)
        & ~sold["_url_norm"].isin(already)
    ]

    sampled_parts = [
        group.sample(n=min(per_band, len(group)), random_state=seed)
        for _, group in eligible.groupby("band")
    ]
    sampled = (
        pd.concat(sampled_parts, ignore_index=True).sort_values("source_from_end")
        if sampled_parts
        else eligible.head(0)
    )
    keep = [c for c in ("url", "year", "make", "model", "variant", "price", "source_from_end", "band") if c in sampled.columns]
    return sampled[keep].reset_index(drop=True)


def build_report(sample_path: Path, rescrape_path: Path) -> pd.DataFrame:
    sample = pd.read_csv(sample_path, low_memory=False)
    rescrape = pd.read_csv(rescrape_path, low_memory=False)
    if "url" not in rescrape.columns:
        raise RuntimeError("Audit re-scrape output must include a 'url' column.")

    rescrape = rescrape.drop_duplicates(subset=["url"], keep="last")
    rescrape["_url_norm"] = rescrape["url"].map(_normalize_url)
    lookup = rescrape.set_index("_url_norm")

    rows: list[dict] = []
    for _, item in sample.iterrows():
        key = _normalize_url(item.get("url"))
        rescraped_row = lookup.loc[key] if key in lookup.index else None
        new_price = None if rescraped_row is None else rescraped_row.get("price")
        rows.append(
            {
                "band": item.get("band"),
                "url": item.get("url"),
                "source_from_end": item.get("source_from_end"),
                "old_price": item.get("price"),
                "new_price": new_price,
                "rescraped": rescraped_row is not None,
                "mismatch": bool(rescraped_row is not None and _prices_differ(item.get("price"), new_price)),
                "old_numeric": parse_price(item.get("price")),
                "new_numeric": parse_price(new_price),
            }
        )
    return pd.DataFrame(rows)


def summarize_report(detail: pd.DataFrame) -> pd.DataFrame:
    grouped = detail.groupby("band")
    summary = grouped.agg(
        sampled=("url", "count"),
        rescraped=("rescraped", "sum"),
        mismatches=("mismatch", "sum"),
    ).reset_index()
    summary["mismatch_rate"] = summary.apply(
        lambda r: (r["mismatches"] / r["rescraped"]) if r["rescraped"] else None, axis=1
    )
    # Rule of three: with n clean samples, the 95% upper bound on the true rate is ~3/n
    summary["clean_upper_bound_95"] = summary.apply(
        lambda r: (3.0 / r["rescraped"]) if r["rescraped"] and r["mismatches"] == 0 else None,
        axis=1,
    )

    def _verdict(r: pd.Series) -> str:
        if not r["rescraped"] or r["rescraped"] < 10:
            return "INSUFFICIENT"
        if r["mismatch_rate"] >= MISMATCH_SUSPECT_THRESHOLD:
            return "SUSPECT"
        return "CLEAN"

    summary["verdict"] = summary.apply(_verdict, axis=1)
    return summary.sort_values("band").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Draw the stratified sample manifest (no network).")
    plan.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    plan.add_argument("--rescraped", type=Path, default=DEFAULT_RESCRAPED)
    plan.add_argument("--output", type=Path, default=DEFAULT_SAMPLE)
    plan.add_argument("--per-band", type=int, default=40)
    plan.add_argument("--band-size", type=int, default=1000)
    plan.add_argument("--seed", type=int, default=42)

    report = sub.add_parser("report", help="Compare sample vs audit re-scrape and summarize per band.")
    report.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    report.add_argument("--rescrape-output", type=Path, default=DEFAULT_AUDIT_RESCRAPE)
    report.add_argument("--report", type=Path, default=DEFAULT_REPORT)

    args = parser.parse_args()

    if args.command == "plan":
        sample = build_sample(
            args.source,
            args.rescraped,
            per_band=args.per_band,
            band_size=args.band_size,
            seed=args.seed,
        )
        write_dataframe_csv_atomic(sample, args.output, index=False)
        bands = sample.groupby("band").size()
        print(f"[audit-plan] wrote {len(sample)} sampled rows across {len(bands)} bands -> {args.output}")
        print(f"[audit-plan] next: python scripts/rebuild_sold_dataset.py --source {args.output} --output {DEFAULT_AUDIT_RESCRAPE}")
        return

    detail = build_report(args.sample, args.rescrape_output)
    summary = summarize_report(detail)
    write_dataframe_csv_atomic(summary, args.report, index=False)
    detail_path = args.report.with_name(args.report.stem + "_detail.csv")
    write_dataframe_csv_atomic(detail, detail_path, index=False)
    print(f"[audit-report] summary -> {args.report}")
    print(f"[audit-report] detail  -> {detail_path}")
    print(summary.to_string(index=False))
    suspect = summary[summary["verdict"] == "SUSPECT"]
    if len(suspect):
        print(f"[audit-report] {len(suspect)} SUSPECT band(s); queue targeted rebuild_sold_dataset.py runs for those offsets.")
    else:
        print("[audit-report] no suspect bands at the sampled confidence level.")


if __name__ == "__main__":
    main()
