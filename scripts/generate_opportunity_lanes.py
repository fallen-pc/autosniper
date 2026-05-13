from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from shared.comps_engine import parse_currency, parse_numeric
from shared.curves import resolve_curve_canonical_tag


DEFAULT_AUTOTRADER_PATH = Path("autotrader_isolated/output/autotrader_recent_market_tagged.csv")
DEFAULT_SOLD_PATH = Path("CSV_data/scrapers/sold_cars.csv")
DEFAULT_CURVES_PATH = Path("CSV_data/restricted/curves.csv")
DEFAULT_OUTPUT_PATH = Path("output/opportunity_lanes.csv")
DEFAULT_SUMMARY_PATH = Path("output/opportunity_lanes.md")

NOISE_TOKENS = {
    "auto",
    "automatic",
    "manual",
    "cvt",
    "dct",
    "petrol",
    "diesel",
    "turbo",
    "unleaded",
    "hybrid",
    "electric",
    "wagon",
    "hatch",
    "hatchback",
    "sedan",
    "suv",
    "ute",
    "van",
    "fwd",
    "rwd",
    "awd",
    "4wd",
    "4x4",
    "4x2",
    "2wd",
    "series",
}


def _norm_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value or "").strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_choice(value: object, patterns: Iterable[tuple[str, tuple[str, ...]]]) -> str:
    text = _norm_text(value)
    for label, needles in patterns:
        if any(re.search(pattern, text) for pattern in needles):
            return label
    return ""


def _norm_body(value: object) -> str:
    return _norm_choice(
        value,
        (
            ("hatch", (r"\bhatch\b", r"\bhatchback\b")),
            ("sedan", (r"\bsedan\b",)),
            ("wagon", (r"\bwagon\b", r"\bsuv\b")),
            ("ute", (r"\bute\b", r"\bpick up\b", r"\bpickup\b")),
            ("van", (r"\bvan\b",)),
            ("people_mover", (r"\bpeople mover\b",)),
            ("coupe", (r"\bcoupe\b",)),
            ("convertible", (r"\bconvertible\b",)),
        ),
    )


def _norm_fuel(value: object) -> str:
    return _norm_choice(
        value,
        (
            ("hybrid", (r"\bhybrid\b",)),
            ("diesel", (r"\bdiesel\b",)),
            ("electric", (r"\belectric\b", r"\bev\b")),
            ("petrol", (r"\bpetrol\b", r"\bunleaded\b", r"\bpremium\b")),
        ),
    )


def _norm_trans(value: object) -> str:
    return _norm_choice(
        value,
        (
            ("auto", (r"\bauto\b", r"\bautomatic\b", r"\bcvt\b", r"\bdct\b")),
            ("manual", (r"\bmanual\b",)),
        ),
    )


def _variant_family(row: pd.Series) -> str:
    variant_text = _norm_text(row.get("variant"))
    make = _norm_text(row.get("make"))
    model = _norm_text(row.get("model"))
    tokens = [token for token in variant_text.split() if token]
    cleaned: list[str] = []
    for token in tokens:
        if token in NOISE_TOKENS:
            continue
        if token == make or token == model:
            continue
        if re.fullmatch(r"20\d{2}|19\d{2}", token):
            continue
        if re.fullmatch(r"[a-z]{1,3}\d{1,3}[a-z]?", token):
            continue
        cleaned.append(token)
    return "_".join(cleaned[:3]) or "base"


def _prepare_common(df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    working = df.copy()
    working["make_key"] = working.get("make", "").apply(_norm_text)
    working["model_key"] = working.get("model", "").apply(_norm_text)
    working["body_key"] = working.get("body_type", "").apply(_norm_body)
    working["fuel_key"] = working.get("fuel_type", "").apply(_norm_fuel)
    working["trans_key"] = working.get("transmission", "").apply(_norm_trans)
    working["variant_family"] = working.apply(_variant_family, axis=1)
    working["lane_key"] = (
        working["make_key"]
        + "|"
        + working["model_key"]
        + "|"
        + working["variant_family"]
        + "|"
        + working["body_key"]
        + "|"
        + working["fuel_key"]
        + "|"
        + working["trans_key"]
    )
    working["source"] = source
    working["year_numeric"] = working.get("year", "").apply(parse_numeric)
    odo_col = "odometer" if "odometer" in working.columns else "odometer_reading"
    working["odometer_numeric"] = working.get(odo_col, "").apply(parse_numeric)
    if "canonical_tag" not in working.columns:
        working["canonical_tag"] = ""
    working["canonical_tag"] = working["canonical_tag"].fillna("").astype(str).str.strip()
    return working


def _load_supported_curve_tags(path: Path) -> set[str]:
    if not path.exists():
        return set()
    curves = pd.read_csv(path, low_memory=False)
    if "canonical_tag" not in curves.columns:
        return set()
    return set(curves["canonical_tag"].dropna().astype(str).str.strip())


def _summarise_lane(
    retail: pd.DataFrame,
    sold: pd.DataFrame,
    supported_curve_tags: set[str],
) -> pd.DataFrame:
    retail_group = retail.groupby("lane_key")
    sold_group = sold.groupby("lane_key")
    rows: list[dict[str, object]] = []
    for lane_key, retail_lane in retail_group:
        if lane_key not in sold_group.groups:
            continue
        sold_lane = sold_group.get_group(lane_key)
        retail_prices = retail_lane["retail_price"].dropna()
        sold_prices = sold_lane["sold_price"].dropna()
        if retail_prices.empty or sold_prices.empty:
            continue

        sample = retail_lane.iloc[0]
        sold_sample = sold_lane.iloc[0]
        retail_median = float(retail_prices.median())
        sold_median = float(sold_prices.median())
        retail_years = retail_lane["year_numeric"].dropna()
        sold_years = sold_lane["year_numeric"].dropna()
        retail_median_year = float(retail_years.median()) if not retail_years.empty else None
        sold_median_year = float(sold_years.median()) if not sold_years.empty else None
        median_year_gap = (
            abs(retail_median_year - sold_median_year)
            if retail_median_year is not None and sold_median_year is not None
            else None
        )
        retail_odo = retail_lane["odometer_numeric"].dropna()
        sold_odo = sold_lane["odometer_numeric"].dropna()
        raw_spread = retail_median - sold_median
        estimated_costs = max(2500.0, sold_median * 0.10 + 1800.0)
        estimated_margin = raw_spread - estimated_costs

        lane_tags = set(retail_lane["canonical_tag"].dropna().astype(str).str.strip())
        lane_tags.update(sold_lane["canonical_tag"].dropna().astype(str).str.strip())
        lane_tags.discard("")
        lane_tags.discard("UNCLASSIFIED")
        curve_tags = {resolve_curve_canonical_tag(tag) for tag in lane_tags if tag}
        already_supported = bool(curve_tags & supported_curve_tags)

        year_comparable = median_year_gap is None or median_year_gap <= 4

        if not year_comparable:
            recommendation = "year_mismatch"
        elif len(retail_prices) >= 5 and len(sold_prices) >= 3 and estimated_margin >= 2500:
            recommendation = "strong_review"
        elif len(retail_prices) >= 3 and len(sold_prices) >= 2 and estimated_margin >= 1500:
            recommendation = "review"
        elif len(retail_prices) < 3 or len(sold_prices) < 2:
            recommendation = "thin_evidence"
        elif estimated_margin <= 0:
            recommendation = "weak_spread"
        else:
            recommendation = "watch"

        rows.append(
            {
                "make": sample["make_key"],
                "model": sample["model_key"],
                "variant_family": sample["variant_family"],
                "body": sample["body_key"],
                "fuel": sample["fuel_key"],
                "transmission": sample["trans_key"],
                "lane_key": lane_key,
                "autotrader_count": int(len(retail_prices)),
                "autotrader_median": round(retail_median, 2),
                "autotrader_p25": round(float(retail_prices.quantile(0.25)), 2),
                "autotrader_p75": round(float(retail_prices.quantile(0.75)), 2),
                "autotrader_median_year": round(retail_median_year, 1) if retail_median_year is not None else "",
                "autotrader_median_odo": round(float(retail_odo.median()), 0) if not retail_odo.empty else "",
                "sold_count": int(len(sold_prices)),
                "sold_median": round(sold_median, 2),
                "sold_p25": round(float(sold_prices.quantile(0.25)), 2),
                "sold_p75": round(float(sold_prices.quantile(0.75)), 2),
                "sold_median_year": round(sold_median_year, 1) if sold_median_year is not None else "",
                "sold_median_odo": round(float(sold_odo.median()), 0) if not sold_odo.empty else "",
                "median_year_gap": round(median_year_gap, 1) if median_year_gap is not None else "",
                "raw_spread": round(raw_spread, 2),
                "estimated_costs": round(estimated_costs, 2),
                "estimated_margin": round(estimated_margin, 2),
                "already_supported": already_supported,
                "canonical_tags_seen": "|".join(sorted(lane_tags)),
                "recommendation": recommendation,
                "example_autotrader_url": retail_lane["url"].dropna().astype(str).iloc[0],
                "example_sold_url": sold_lane["url"].dropna().astype(str).iloc[0],
                "sold_canonical_reason": sold_sample.get("canonical_reason", ""),
            }
        )
    return pd.DataFrame(rows)


def build_report(
    *,
    autotrader_path: Path = DEFAULT_AUTOTRADER_PATH,
    sold_path: Path = DEFAULT_SOLD_PATH,
    curves_path: Path = DEFAULT_CURVES_PATH,
) -> pd.DataFrame:
    retail = pd.read_csv(autotrader_path, low_memory=False)
    sold = pd.read_csv(sold_path, low_memory=False)

    retail = _prepare_common(retail, source="autotrader")
    sold = _prepare_common(sold, source="sold")
    retail["retail_price"] = retail.get("price", "").apply(parse_currency)
    sold["sold_price"] = sold.get("price", "").apply(parse_currency)

    retail = retail.dropna(subset=["retail_price", "make_key", "model_key"])
    sold = sold.dropna(subset=["sold_price", "make_key", "model_key"])
    retail = retail[(retail["retail_price"] > 1000) & (retail["retail_price"] < 250000)]
    sold = sold[(sold["sold_price"] > 0) & (sold["sold_price"] < 250000)]

    supported_curve_tags = _load_supported_curve_tags(curves_path)
    report = _summarise_lane(retail, sold, supported_curve_tags)
    if report.empty:
        return report
    recommendation_rank = {
        "strong_review": 0,
        "review": 1,
        "watch": 2,
        "thin_evidence": 3,
        "weak_spread": 4,
        "year_mismatch": 5,
    }
    report["recommendation_rank"] = report["recommendation"].map(recommendation_rank).fillna(99)
    report = report.sort_values(
        by=["recommendation_rank", "estimated_margin", "sold_count", "autotrader_count"],
        ascending=[True, False, False, False],
    ).drop(columns=["recommendation_rank"])
    return report.reset_index(drop=True)


def write_summary(report: pd.DataFrame, path: Path, *, top_n: int = 20) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Opportunity Lanes", ""]
    if report.empty:
        lines.append("No matching Autotrader/Sold lanes found.")
        path.write_text("\n".join(lines), encoding="utf-8")
        return
    lines.extend(
        [
            f"Rows: {len(report)}",
            "",
            "This report ranks current Autotrader retail asking prices against repaired Grays sold prices.",
            "It is a candidate-selection report only; it does not create tags or curves.",
            "",
            "## Top Candidates",
            "",
        ]
    )
    columns = [
        "make",
        "model",
        "variant_family",
        "autotrader_count",
        "autotrader_median",
        "autotrader_median_year",
        "sold_count",
        "sold_median",
        "sold_median_year",
        "median_year_gap",
        "estimated_margin",
        "already_supported",
        "recommendation",
    ]
    lines.append(_markdown_table(report.head(top_n)[columns]))
    lines.append("")
    lines.append("## Recommendation Counts")
    lines.append("")
    counts = report["recommendation"].value_counts().rename_axis("recommendation").reset_index(name="count")
    lines.append(_markdown_table(counts))
    path.write_text("\n".join(lines), encoding="utf-8")


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    columns = list(frame.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        values = [str(row.get(column, "")).replace("|", "\\|") for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank possible new vehicle lanes from Autotrader retail vs Grays sold prices.")
    parser.add_argument("--autotrader", type=Path, default=DEFAULT_AUTOTRADER_PATH)
    parser.add_argument("--sold", type=Path, default=DEFAULT_SOLD_PATH)
    parser.add_argument("--curves", type=Path, default=DEFAULT_CURVES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    args = parser.parse_args()

    report = build_report(autotrader_path=args.autotrader, sold_path=args.sold, curves_path=args.curves)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(args.output, index=False)
    write_summary(report, args.summary)
    print(f"Opportunity lane report written: {args.output} ({len(report)} rows)")
    print(f"Summary written: {args.summary}")


if __name__ == "__main__":
    main()
