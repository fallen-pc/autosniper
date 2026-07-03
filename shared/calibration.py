"""Calibration report helpers for AutoSniper buy/no-buy rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.ai_listing_valuation import (
    _interstate_purchase_blocked,
    OPERATING_STATE,
    _is_interstate_listing,
)
from shared.comps_engine import parse_currency, parse_numeric
from shared.curves import (
    interpolate_base_by_year,
    interpolate_price_by_km,
    load_curves,
    resolve_curve_canonical_tag,
)
from shared.data_loader import dataset_path
from shared.missed_opportunities import compute_decision_metrics


DEFAULT_OUTPUT_DIR = Path("output/calibration")


@dataclass(frozen=True)
class CalibrationPaths:
    detail_csv: Path
    summary_md: Path


def _safe_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return default
    return text


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def interpolate_curve_value(
    curves_df: pd.DataFrame,
    canonical_tag: str,
    year: int | None,
    km: float | int | None,
    value_col: str,
) -> float | None:
    curve_tag = resolve_curve_canonical_tag(canonical_tag)
    if curves_df.empty or not curve_tag or year is None or km is None:
        return None
    subset = curves_df[curves_df["canonical_tag"] == curve_tag].copy()
    subset = subset.dropna(subset=["anchor_year"])
    if subset.empty:
        return None
    anchor_years = sorted({int(y) for y in subset["anchor_year"].dropna()})
    if not anchor_years or year < anchor_years[0] or year > anchor_years[-1]:
        return None

    def _price_for_anchor(anchor_year: int) -> float | None:
        segment = subset[subset["anchor_year"] == anchor_year].copy()
        segment = segment.dropna(subset=["km_bucket", value_col])
        if segment.empty:
            return None
        segment["km_bucket"] = pd.to_numeric(segment["km_bucket"], errors="coerce")
        segment[value_col] = pd.to_numeric(segment[value_col], errors="coerce")
        segment = segment.dropna(subset=["km_bucket", value_col])
        if segment.empty:
            return None
        points = list(
            segment.sort_values("km_bucket")[["km_bucket", value_col]].itertuples(
                index=False, name=None
            )
        )
        return interpolate_price_by_km(points, km)

    lower_year = anchor_years[0]
    upper_year = anchor_years[-1]
    for start, end in zip(anchor_years, anchor_years[1:]):
        if start <= year <= end:
            lower_year = start
            upper_year = end
            break

    lower_price = _price_for_anchor(lower_year)
    upper_price = _price_for_anchor(upper_year)
    if lower_price is None and upper_price is None:
        return None
    if lower_price is None:
        return upper_price
    if upper_price is None:
        return lower_price
    if upper_year == lower_year:
        return lower_price
    ratio = (year - lower_year) / float(upper_year - lower_year)
    return lower_price + ratio * (upper_price - lower_price)


def compute_underbid_pct(sold_price: Any, max_bid: Any) -> float | None:
    sold_val = _to_float(sold_price)
    max_bid_val = _to_float(max_bid)
    if sold_val is None or max_bid_val is None or max_bid_val <= 0:
        return None
    return ((max_bid_val - sold_val) / max_bid_val) * 100.0


def classify_calibration_row(row: pd.Series) -> str:
    spec_reason = _safe_text(row.get("spec_reason"), "")
    if spec_reason:
        return "not covered"
    out_of_state = str(row.get("out_of_operating_state") or "").strip().lower() in {
        "true",
        "1",
        "yes",
    }
    if out_of_state:
        return "out of operating state"

    sold_price = _to_float(row.get("sold_price"))
    max_bid = _to_float(row.get("max_bid"))
    curve_estimate = _to_float(row.get("curve_estimate"))
    curve_high = _to_float(row.get("curve_high"))
    projected_profit = _to_float(row.get("projected_profit_at_sold"))
    delta_pct = _to_float(row.get("delta_pct"))
    risk_buffer = max(_to_float(row.get("risk_buffer")) or 0.0, 0.0)
    repair_cost = max(_to_float(row.get("repair_cost_estimate")) or 0.0, 0.0)
    cost_drag = risk_buffer + repair_cost

    if sold_price is None or curve_estimate is None or max_bid is None:
        return "unclassified"
    if curve_high is not None and sold_price > (curve_high * 1.05):
        return "auction price spike"

    would_win = sold_price <= max_bid
    profitable_at_sold = projected_profit is not None and projected_profit > 0

    if would_win and profitable_at_sold:
        return "profitable within bid"
    if would_win and not profitable_at_sold:
        return "overbid risk"
    if profitable_at_sold:
        if cost_drag > 0 and (curve_estimate - sold_price) > 0 and cost_drag >= (curve_estimate - sold_price) * 0.35:
            return "risk deduction too large"
        if delta_pct is not None and delta_pct >= 12.0:
            return "curve too conservative"
        return "bid cap too conservative"
    return "correct pass"


def load_calibration_inputs(
    *,
    sold_path: Path | None = None,
    group_map_path: Path | None = None,
    curves_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sold_file = sold_path or dataset_path("sold_cars_restricted.csv")
    group_file = group_map_path or dataset_path("restricted_group_map.csv")
    sold_df = pd.read_csv(sold_file)
    group_map_df = pd.read_csv(group_file)
    curves = curves_df if curves_df is not None else load_curves()
    return sold_df, group_map_df, curves


def build_calibration_detail(
    sold_df: pd.DataFrame,
    group_map_df: pd.DataFrame,
    curves_df: pd.DataFrame,
    *,
    include_repairs: bool = True,
    limit: int | None = None,
) -> pd.DataFrame:
    if sold_df.empty:
        return pd.DataFrame()

    sold = sold_df.copy()
    if "url" not in sold.columns:
        return pd.DataFrame()
    sold["url"] = sold["url"].astype(str).str.strip()
    sold["odometer_numeric"] = sold.get("odometer_reading", pd.Series(index=sold.index)).apply(parse_numeric)
    sold["price_numeric"] = sold.get("price", pd.Series(index=sold.index)).apply(parse_currency)

    group_map = group_map_df.copy()
    if not group_map.empty and {"url", "canonical_tag", "source"}.issubset(group_map.columns):
        sold_groups = (
            group_map[group_map["source"] == "sold"][["url", "canonical_tag", "reason_code"]]
            .rename(columns={"reason_code": "canonical_reason"})
            .drop_duplicates("url")
        )
        sold = sold.merge(sold_groups, on="url", how="left", suffixes=("", "_group"))
    elif "canonical_tag" not in sold.columns:
        sold["canonical_tag"] = None

    sold = sold.dropna(subset=["price_numeric"]).copy()
    if limit is not None:
        sold = sold.head(limit).copy()

    records: list[dict[str, object]] = []
    for _, row in sold.iterrows():
        canonical_tag = _safe_text(row.get("canonical_tag"), "")
        curve_key = resolve_curve_canonical_tag(canonical_tag)
        canonical_reason = _safe_text(row.get("canonical_reason"), "")
        year_val = _safe_int(row.get("year"))
        odo_val = row.get("odometer_numeric")

        spec_reason = ""
        curve_estimate = curve_low = curve_high = None
        if not curve_key:
            spec_reason = canonical_reason or "NOT_COVERED"
        else:
            curve_subset = curves_df[curves_df["canonical_tag"] == curve_key]
            curve_estimate = interpolate_base_by_year(curve_subset, curve_key, year_val, odo_val)
            curve_low = interpolate_curve_value(curve_subset, curve_key, year_val, odo_val, "price_low")
            curve_high = interpolate_curve_value(curve_subset, curve_key, year_val, odo_val, "price_high")
            if curve_estimate is None:
                spec_reason = "NOT_COVERED"

        sold_price = _to_float(row.get("price_numeric"))
        decision = compute_decision_metrics(
            row,
            curve_estimate,
            include_repairs=include_repairs,
        )
        out_of_operating_state = _interstate_purchase_blocked(row.to_dict())
        max_bid = decision.get("max_bid")
        projected_profit = decision.get("projected_profit_at_sold")
        delta = curve_estimate - sold_price if curve_estimate is not None and sold_price is not None else None
        delta_pct = (delta / curve_estimate * 100.0) if delta is not None and curve_estimate else None
        repair_cost = decision.get("repair_cost")
        risk_buffer = decision.get("risk_buffer")
        underbid_pct = compute_underbid_pct(sold_price, max_bid)
        would_win = bool(sold_price is not None and max_bid is not None and sold_price <= float(max_bid))
        profitable_at_sold = bool(projected_profit is not None and float(projected_profit) > 0)
        record = {
            "url": _safe_text(row.get("url"), ""),
            "year": row.get("year"),
            "make": row.get("make"),
            "model": row.get("model"),
            "variant": row.get("variant"),
            "canonical_tag": curve_key,
            "operating_state": OPERATING_STATE,
            "out_of_operating_state": out_of_operating_state,
            "spec_reason": spec_reason,
            "sold_price": sold_price,
            "curve_estimate": curve_estimate,
            "curve_low": curve_low,
            "curve_high": curve_high,
            "delta": delta,
            "delta_pct": delta_pct,
            "max_bid": max_bid,
            "bid_gap": (float(max_bid) - sold_price) if max_bid is not None and sold_price is not None else None,
            "underbid_pct": underbid_pct,
            "would_win": would_win,
            "profitable_at_sold": profitable_at_sold,
            "projected_profit_at_sold": projected_profit,
            "profit_margin_pct": decision.get("profit_margin_pct"),
            "total_costs": decision.get("total_costs"),
            "platform_fees": decision.get("platform_fees"),
            "transport_costs": decision.get("transport"),
            "admin_costs": decision.get("admin_costs"),
            "repair_cost_estimate": repair_cost,
            "risk_buffer": risk_buffer,
            "expected_auction_price": decision.get("expected_auction_price"),
            "date_sold": row.get("date_sold"),
            "location": row.get("location"),
            "general_condition": row.get("general_condition"),
        }
        record["calibration_reason"] = classify_calibration_row(pd.Series(record))
        records.append(record)

    return pd.DataFrame(records)


def summarize_calibration(detail_df: pd.DataFrame) -> dict[str, object]:
    if detail_df.empty:
        return {
            "total_rows": 0,
            "covered_rows": 0,
            "not_covered_rows": 0,
            "would_win_rows": 0,
            "profitable_within_bid_rows": 0,
            "overbid_risk_rows": 0,
            "priced_out_profitable_rows": 0,
            "total_profitable_within_bid": 0.0,
            "avg_profit_within_bid": None,
            "reason_counts": {},
        }

    out_of_state = (
        detail_df["out_of_operating_state"].fillna(False).astype(bool)
        if "out_of_operating_state" in detail_df.columns
        else pd.Series(False, index=detail_df.index)
    )
    covered = detail_df[
        detail_df["spec_reason"].fillna("").astype(str).str.strip().eq("")
    ]
    operating_scope = covered[~out_of_state.loc[covered.index]]
    local_rows = ~out_of_state
    would_win = detail_df["would_win"]
    profitable = detail_df["projected_profit_at_sold"].fillna(0) > 0
    profitable_within_bid = detail_df[local_rows & would_win & profitable]
    overbid_risk = detail_df[local_rows & would_win & ~profitable]
    priced_out_profitable = detail_df[local_rows & ~would_win & profitable]
    reason_counts = detail_df["calibration_reason"].fillna("unclassified").value_counts().to_dict()
    profit_series = profitable_within_bid["projected_profit_at_sold"].dropna()
    return {
        "total_rows": int(len(detail_df)),
        "covered_rows": int(len(operating_scope)),
        "not_covered_rows": int(len(detail_df) - len(covered)),
        "out_of_operating_state_rows": int(out_of_state.sum()),
        "would_win_rows": int((detail_df["would_win"] & ~out_of_state).sum()),
        "profitable_within_bid_rows": int(len(profitable_within_bid)),
        "overbid_risk_rows": int(len(overbid_risk)),
        "priced_out_profitable_rows": int(len(priced_out_profitable)),
        "total_profitable_within_bid": float(profit_series.clip(lower=0).sum()) if not profit_series.empty else 0.0,
        "avg_profit_within_bid": float(profit_series.mean()) if not profit_series.empty else None,
        "reason_counts": reason_counts,
    }


def render_summary_markdown(summary: dict[str, object], detail_df: pd.DataFrame) -> str:
    reason_counts = summary.get("reason_counts") or {}
    reason_lines = "\n".join(
        f"- {reason}: {count}" for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    ) or "- No rows"
    avg_profit = summary.get("avg_profit_within_bid")
    avg_profit_text = "N/A" if avg_profit is None else f"${float(avg_profit):,.0f}"
    total_profit = float(summary.get("total_profitable_within_bid") or 0.0)

    out_of_state = (
        detail_df["out_of_operating_state"].fillna(False).astype(bool)
        if "out_of_operating_state" in detail_df.columns
        else pd.Series(False, index=detail_df.index)
    )
    top_rows = (
        detail_df[~out_of_state]
        .sort_values("projected_profit_at_sold", ascending=False, na_position="last")
        .head(10)
    )
    top_lines = []
    for _, row in top_rows.iterrows():
        label = " ".join(
            part for part in (
                _safe_text(row.get("year")),
                _safe_text(row.get("make")),
                _safe_text(row.get("model")),
                _safe_text(row.get("variant")),
            )
            if part
        ) or _safe_text(row.get("url"), "Listing")
        profit = _to_float(row.get("projected_profit_at_sold"))
        reason = _safe_text(row.get("calibration_reason"), "unclassified")
        top_lines.append(f"- {label}: {('$' + format(profit, ',.0f')) if profit is not None else 'N/A'} ({reason})")
    top_text = "\n".join(top_lines) or "- No rows"

    return "\n".join(
        [
            "# Valuation Calibration Report",
            "",
            "This compares historical restricted sold rows against the current AutoSniper buy/no-buy rules.",
            "",
            "## Summary",
            "",
            f"- Total sold rows checked: {summary.get('total_rows')}",
            f"- Covered by curves: {summary.get('covered_rows')}",
            f"- Not covered: {summary.get('not_covered_rows')}",
            f"- Out of operating state: {summary.get('out_of_operating_state_rows', 0)}",
            f"- Would have been inside max bid: {summary.get('would_win_rows')}",
            f"- Profitable within max bid: {summary.get('profitable_within_bid_rows')}",
            f"- Overbid risk rows: {summary.get('overbid_risk_rows')}",
            f"- Profitable but priced out by max bid: {summary.get('priced_out_profitable_rows')}",
            f"- Total theoretical profit inside max bid: ${total_profit:,.0f}",
            f"- Average profit inside max bid: {avg_profit_text}",
            "",
            "## Reason Counts",
            "",
            reason_lines,
            "",
            "## Top Local Projected Profit Rows",
            "",
            top_text,
            "",
        ]
    )


def write_calibration_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    include_repairs: bool = True,
    limit: int | None = None,
) -> CalibrationPaths:
    sold_df, group_map_df, curves_df = load_calibration_inputs()
    detail_df = build_calibration_detail(
        sold_df,
        group_map_df,
        curves_df,
        include_repairs=include_repairs,
        limit=limit,
    )
    summary = summarize_calibration(detail_df)
    output_dir.mkdir(parents=True, exist_ok=True)
    detail_csv = output_dir / "valuation_calibration_detail.csv"
    summary_md = output_dir / "valuation_calibration_summary.md"
    detail_df.to_csv(detail_csv, index=False)
    summary_md.write_text(render_summary_markdown(summary, detail_df), encoding="utf-8")
    return CalibrationPaths(detail_csv=detail_csv, summary_md=summary_md)
