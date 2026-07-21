"""Streamlit overview dashboard for the AutoSniper dataset."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import re

import pandas as pd
import streamlit as st

from ops.active_monitor import load_ai_analysis_active_df
from scripts.ai_listing_valuation import MIN_NET_PROFIT_ABSOLUTE
from shared.decision_policy import action_display_parts
from shared.csv_utils import count_csv_records, read_csv_stable
from shared.curves import list_curve_tags, load_curves
from shared.data_loader import dataset_path, ensure_datasets_available
from shared.global_filters import apply_global_sidebar_filters, render_global_sidebar_filters
from shared.styling import clean_html, display_banner, escape_html, inject_global_styles, page_intro, safe_url, section_heading
from shared.valuation_display import (
    build_ai_analysis_summary_rows,
    parse_currency_value,
    parse_percent_value,
)


st.set_page_config(page_title="AutoSniper - Dashboard", layout="wide")
render_global_sidebar_filters()
inject_global_styles()
display_banner()

page_intro("DASHBOARD", "Scan the current AI Analysis shortlist and monitor the supporting pipeline.")

missing = ensure_datasets_available(["vehicle_static_details.csv"])
if missing:
    st.error(
        "Required dataset `vehicle_static_details.csv` is missing. "
        "Configure `AUTOSNIPER_DATA_URL` or upload the CSV to `CSV_data/`."
    )
    st.stop()

CSV_FILE = dataset_path("vehicle_static_details.csv")
VALUATIONS_FILE = dataset_path("ai_listing_valuations.csv")
LINKS_FILE = dataset_path("all_vehicle_links.csv")
ACTIVE_FILE = dataset_path("active_vehicle_details.csv")
RAW_FILE = dataset_path("raw_vehicle_data.csv")
NORMALISED_FILE = dataset_path("normalised_data.csv")
EXCLUDED_FILE = dataset_path("excluded_listings.csv")
SOLD_FILE = dataset_path("sold_cars.csv")
REFERRED_FILE = dataset_path("referred_cars.csv")
SCORED_FILE = dataset_path("scored_listings.csv")
AUTOTRADER_FILE = Path("autotrader_isolated/output/first_page_results.csv")

df = read_csv_stable(CSV_FILE)

if df.empty:
    st.warning("The vehicle dataset is empty. Trigger a scrape to see dashboard metrics.")
    st.stop()


def normalise_status(data: pd.DataFrame) -> pd.Series:
    """Return a clean, lower-cased status series for aggregation."""
    status_raw = data["status"] if "status" in data.columns else pd.Series(pd.NA, index=data.index)
    status_series = (
        status_raw.fillna("unknown")
        .astype(str)
        .str.strip()
        .str.lower()
        .replace({"": "unknown", "nan": "unknown"})
    )
    return status_series


status_series = normalise_status(df)
status_counts = status_series.value_counts()
total_listings = int(len(df))
active_df = df[status_series == "active"].copy()

st.markdown(
    clean_html(
        """
        <style>
        .top-auction-card {
            background: linear-gradient(145deg, rgba(26, 33, 48, 0.98), rgba(10, 16, 28, 0.98));
            border-radius: 16px;
            padding: 1rem;
            border: 1px solid var(--autosniper-border);
            box-shadow: 0 22px 42px rgba(5, 10, 18, 0.34);
            min-height: 100%;
        }
        .top-auction-card h3 {
            margin: 0 0 0.3rem 0;
            font-size: 1.1rem;
        }
        .top-auction-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.18rem 0.65rem;
            border-radius: 999px;
            background: rgba(40, 71, 53, 0.12);
            color: var(--autosniper-accent);
            font-size: 0.78rem;
            letter-spacing: 0.08em;
        }
        .top-auction-pill[data-action="Buy"] {
            border: 1px solid rgba(44, 255, 154, 0.6);
            background: rgba(44, 255, 154, 0.12);
            color: var(--autosniper-success);
        }
        .top-auction-context {
            margin-top: 0.65rem;
            padding-top: 0.55rem;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            color: var(--autosniper-muted);
            font-size: 0.82rem;
            line-height: 1.4;
        }
        .top-auction-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 0.65rem;
            margin-top: 0.75rem;
        }
        .top-auction-metric {
            background: rgba(18, 26, 39, 0.9);
            border-radius: 12px;
            padding: 0.7rem 0.8rem;
            border: 1px solid rgba(31, 166, 255, 0.12);
        }
        .top-auction-metric span {
            display: block;
        }
        .top-auction-label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--autosniper-muted);
            margin-bottom: 0.2rem;
        }
        .top-auction-value {
            font-size: 1.05rem;
            font-weight: 600;
            color: var(--autosniper-primary);
        }
        .top-auction-actions {
            margin-top: 0.9rem;
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }
        .page-status-card {
            background: linear-gradient(145deg, rgba(26, 33, 48, 0.98), rgba(10, 16, 28, 0.98));
            border-radius: 16px;
            border: 1px solid var(--autosniper-border);
            box-shadow: 0 16px 32px rgba(5, 10, 18, 0.3);
            padding: 1rem;
            min-height: 100%;
        }
        .page-status-card h4 {
            margin: 0;
            font-size: 1rem;
        }
        .page-status-meta {
            font-size: 0.85rem;
            color: var(--autosniper-muted);
            margin: 0.2rem 0 0.5rem 0;
        }
        .page-status-highlight {
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--autosniper-primary);
        }
        .page-status-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 0.4rem;
            margin: 0.6rem 0;
        }
        .page-status-metric {
            background: rgba(18, 26, 39, 0.88);
            border-radius: 12px;
            padding: 0.55rem 0.7rem;
            border: 1px solid rgba(31, 166, 255, 0.08);
        }
        .page-status-label {
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.09em;
            color: var(--autosniper-muted);
        }
        .page-status-value {
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--autosniper-text);
        }
        .pipeline-health-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.9rem;
            margin-top: 0.8rem;
        }
        .pipeline-health-card {
            background: linear-gradient(145deg, rgba(26, 33, 48, 0.98), rgba(10, 16, 28, 0.98));
            border-radius: 16px;
            border: 1px solid var(--autosniper-border);
            box-shadow: 0 16px 32px rgba(5, 10, 18, 0.3);
            padding: 1rem;
        }
        .pipeline-health-card[data-tone="green"] {
            border-left: 6px solid var(--autosniper-success);
        }
        .pipeline-health-card[data-tone="orange"] {
            border-left: 6px solid var(--autosniper-warning);
        }
        .pipeline-health-card[data-tone="red"] {
            border-left: 6px solid var(--autosniper-danger);
        }
        .ghost-button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.45rem 1.1rem;
            border-radius: 999px;
            border: 1px solid rgba(31, 166, 255, 0.45);
            background: transparent;
            color: var(--autosniper-accent);
            font-weight: 600;
            font-size: 0.85rem;
            text-decoration: none;
            transition: all 0.15s ease-out;
        }
        .ghost-button:hover {
            background: rgba(31, 166, 255, 0.12);
            color: var(--autosniper-accent);
        }
        .pipeline-health-status {
            font-size: 0.74rem;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }
        .pipeline-health-title {
            font-size: 1rem;
            font-weight: 700;
            color: var(--autosniper-primary);
        }
        .pipeline-health-value {
            font-size: 1.5rem;
            font-weight: 800;
            color: var(--autosniper-primary);
            margin: 0.35rem 0 0.15rem;
        }
        .pipeline-health-note {
            color: var(--autosniper-muted);
            font-size: 0.85rem;
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

tracked_statuses: list[tuple[str, str]] = [
    ("active", "Active"),
    ("sold", "Sold"),
    ("referred", "Referred"),
]
tracked_total = sum(int(status_counts.get(code, 0)) for code, _ in tracked_statuses)
other_total = max(total_listings - tracked_total, 0)


def render_metric(column: "st.delta_generator.DeltaGenerator", label: str, value: int, share: float | None = None) -> None:
    """Display a formatted metric with an optional share-of-total delta."""
    formatted_value = f"{int(value):,}"
    if share is not None and total_listings:
        column.metric(label, formatted_value, f"{share:.0%} of total")
    else:
        column.metric(label, formatted_value)


def safe_read_csv(path: "os.PathLike[str] | str", parse_dates: list[str] | None = None) -> pd.DataFrame:
    file_path = path if isinstance(path, str) else path
    if not Path(file_path).exists():
        return pd.DataFrame()
    try:
        return read_csv_stable(file_path, parse_dates=parse_dates)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not read {file_path}: {exc}")
        return pd.DataFrame()


def format_currency_value(value: float | None, default: str = "N/A") -> str:
    if value is None:
        return default
    return f"${value:,.0f}"


def _format_rows(value: int | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,}"


def format_last_run(ts: datetime | None) -> str:
    if ts is None:
        return "Last run - never"
    local_ts = ts.astimezone()
    delta_minutes = max((datetime.now(timezone.utc) - ts).total_seconds() / 60.0, 0.0)
    if delta_minutes < 60:
        ago = f"{int(delta_minutes)} min ago"
    elif delta_minutes < 1440:
        ago = f"{delta_minutes / 60:.1f} h ago"
    else:
        ago = f"{delta_minutes / 1440:.1f} d ago"
    return f"Last run - {local_ts.strftime('%d %b %Y %H:%M')} ({ago})"


def describe_last_run(path: "os.PathLike[str] | str") -> tuple[str, datetime | None]:
    file_path = Path(path)
    if not file_path.exists():
        return "Last run - never", None
    ts = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
    return format_last_run(ts), ts


def describe_latest_run(*paths: "os.PathLike[str] | str") -> str:
    timestamps: list[datetime] = []
    for path in paths:
        _text, ts = describe_last_run(path)
        if ts is not None:
            timestamps.append(ts)
    latest = max(timestamps) if timestamps else None
    return format_last_run(latest)


active_live_df = safe_read_csv(ACTIVE_FILE)
sold_df = safe_read_csv(SOLD_FILE)
referred_df = safe_read_csv(REFERRED_FILE)
links_df = safe_read_csv(LINKS_FILE)


def extract_hours_remaining(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).lower()
    day_match = re.search(r"(\d+)\s*d", text)
    hour_match = re.search(r"(\d+)\s*h", text)
    if not day_match and not hour_match:
        return None
    days = int(day_match.group(1)) if day_match else 0
    hours = int(hour_match.group(1)) if hour_match else 0
    return days * 24 + hours


def _health_tone(value: int | None, *, expected_min: int = 1, partial_min: int = 1) -> str:
    numeric = int(value or 0)
    if numeric >= expected_min:
        return "green"
    if numeric >= partial_min:
        return "orange"
    return "red"


def _coverage_tone(ratio: float | None) -> str:
    if ratio is None:
        return "red"
    if ratio >= 0.75:
        return "green"
    if ratio > 0:
        return "orange"
    return "red"


def _render_health_card(title: str, value_text: str, note: str, tone: str) -> None:
    st.markdown(
        clean_html(
            f"""
            <div class="pipeline-health-card" data-tone="{tone}">
                <div class="pipeline-health-status">{tone}</div>
                <div class="pipeline-health-title">{title}</div>
                <div class="pipeline-health-value">{value_text}</div>
                <div class="pipeline-health-note">{note}</div>
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


valuations_df = pd.DataFrame()
if VALUATIONS_FILE.exists():
    valuations_df = safe_read_csv(VALUATIONS_FILE)
    if not valuations_df.empty:
        if "analysis_timestamp" in valuations_df.columns:
            valuations_df["analysis_timestamp"] = pd.to_datetime(
                valuations_df["analysis_timestamp"], errors="coerce"
            )
        valuations_df = valuations_df.sort_values("analysis_timestamp").drop_duplicates("url", keep="last")
        valuations_df["profit_margin_value"] = valuations_df["profit_margin_percent"].apply(parse_percent_value)
        valuations_df["score_value"] = pd.to_numeric(valuations_df.get("score_out_of_10"), errors="coerce")

curve_tags = list_curve_tags(load_curves())
active_scope_df = active_live_df.copy()
if not valuations_df.empty and not active_scope_df.empty:
    valuation_scope_cols = ["url"]
    for column in (
        "profit_margin_percent",
        "profit_margin_value",
        "expected_profit",
        "active_profit_value",
        "confidence",
        "score_out_of_10",
        "score_value",
        "analysis_timestamp",
    ):
        if column in valuations_df.columns and column not in valuation_scope_cols:
            valuation_scope_cols.append(column)
    active_scope_df = active_scope_df.merge(
        valuations_df[valuation_scope_cols].drop_duplicates("url"),
        on="url",
        how="left",
        suffixes=("", "_ai"),
    )
active_scope_df = apply_global_sidebar_filters(
    active_scope_df,
    state_columns=("location_state", "rego_state", "location"),
    vehicle_type_columns=("body_type", "body"),
    margin_columns=("profit_margin_value", "profit_margin_percent"),
    canonical_tag_column="canonical_tag",
    curve_tags=curve_tags,
)
sold_scope_df = apply_global_sidebar_filters(
    sold_df,
    state_columns=("location_state", "state", "location"),
    vehicle_type_columns=("body_type", "body"),
    canonical_tag_column="canonical_tag",
    curve_tags=curve_tags,
)
referred_scope_df = apply_global_sidebar_filters(
    referred_df,
    state_columns=("location_state", "state", "location"),
    vehicle_type_columns=("body_type", "body"),
    canonical_tag_column="canonical_tag",
    curve_tags=curve_tags,
)
ai_active_scope_df = load_ai_analysis_active_df()
ai_summary_df = build_ai_analysis_summary_rows(
    ai_active_scope_df,
    valuations_df,
    min_profit=MIN_NET_PROFIT_ABSOLUTE,
)
ai_summary_df = apply_global_sidebar_filters(
    ai_summary_df,
    state_columns=("location_state", "rego_state", "location"),
    vehicle_type_columns=("body_type", "body"),
    margin_columns=("margin_value", "profit_margin_percent"),
    canonical_tag_column="canonical_tag",
    curve_tags=curve_tags,
)

section_heading(
    "Active AI Analysis",
    "A condensed view of every actionable or review listing currently shown by AI Analysis. AI Analysis remains the source of truth.",
)
if valuations_df.empty or ai_active_scope_df.empty:
    st.info("No current AI Analysis active set is available. Refresh AI valuations to populate this section.")
else:
    if ai_summary_df.empty:
        st.info("AI Analysis currently has no actionable or review listings with a proxy max bid.")
    else:
        st.caption(
            f"Showing {len(ai_summary_df):,} current AI Analysis listing(s) from "
            f"{len(ai_active_scope_df):,} curve-covered active listing(s). Avoid rows are hidden, matching the AI Analysis default."
        )
        summary_rows = list(ai_summary_df.iterrows())
        for row_offset in range(0, len(summary_rows), 2):
            cards = st.columns(2, gap="large")
            for card_index, (row_index, row) in enumerate(summary_rows[row_offset : row_offset + 2]):
              with cards[card_index]:
                year = int(row["year"]) if pd.notna(row.get("year")) else ""
                title_parts = [str(part) for part in [year, row.get("make", ""), row.get("model", "")] if str(part).strip()]
                title = " ".join(title_parts) or "Unnamed listing"
                variant = str(row.get("variant", "") or "").strip()
                location = str(row.get("location", "") or "Unknown location")
                time_remaining = str(row.get("time_remaining_or_date_sold", "N/A"))
                current_bid = format_currency_value(row.get("current_price_value"))
                max_bid = str(row.get("proxy_max_label") or "N/A")
                resale_estimate = format_currency_value(row.get("resale_value"))
                profit = format_currency_value(row.get("profit_value"))
                margin = f"{row['margin_value']:.0f}%" if pd.notna(row.get("margin_value")) else "N/A"
                confidence = f"{float(row['confidence_value']) * 100:.0f}%" if pd.notna(row.get("confidence_value")) else "N/A"
                expected_finish = format_currency_value(row.get("expected_finish_value"))
                expected_profit = format_currency_value(row.get("expected_finish_profit_value"))
                action = action_display_parts(row.get("action_label"))[0]
                bid_status = str(row.get("bid_status_display") or "Unknown")
                bid_detail = str(row.get("bid_status_detail") or "")
                risk_flags = str(row.get("risk_flags") or "").strip()
                risk_summary = (
                    risk_flags.replace("|", ", ")
                    if risk_flags and risk_flags.lower() not in {"nan", "none"}
                    else "No stored risk flags"
                )
                ai_url = row.get("url", "")
                st.markdown(
                    clean_html(
                        f"""
                        <div class="top-auction-card">
                            <div class="top-auction-pill" data-action="{escape_html(action)}">{escape_html(action)}</div>
                            <h3>{escape_html(title)}</h3>
                            <div class="autosniper-body">{escape_html(variant) or "Variant unavailable"}</div>
                            <div class="autosniper-body" style="color: var(--autosniper-muted);">
                                {escape_html(location)} &bullet; {escape_html(time_remaining)}
                            </div>
                            <div class="top-auction-metrics">
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Current bid</span>
                                    <span class="top-auction-value">{escape_html(current_bid)}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Proxy max bid</span>
                                    <span class="top-auction-value">{escape_html(max_bid)}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Resale estimate</span>
                                    <span class="top-auction-value">{escape_html(resale_estimate)}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Worst profit at proxy max</span>
                                    <span class="top-auction-value">{escape_html(profit)}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Margin</span>
                                    <span class="top-auction-value">{escape_html(margin)}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Confidence</span>
                                    <span class="top-auction-value">{escape_html(confidence)}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Expected finish</span>
                                    <span class="top-auction-value">{escape_html(expected_finish)}</span>
                                </div>
                            </div>
                            <div class="top-auction-context">
                                <strong>{escape_html(bid_status)}</strong> &mdash; {escape_html(bid_detail)}<br/>
                                Scenario profit at expected finish: <strong>{escape_html(expected_profit)}</strong><br/>
                                Risk: {escape_html(risk_summary)} &bull; Time left: {escape_html(time_remaining)}
                            </div>
                            <div class="top-auction-actions">
                                <a class="ghost-button" href="{safe_url(ai_url)}" target="_blank">Open Listing</a>
                            </div>
                        </div>
                        """
                    ),
                    unsafe_allow_html=True,
                )
                if ai_url:
                    if st.button("Open in AI Analysis", key=f"ai-link-{row_index}", width="stretch"):
                        st.session_state["ai_focus_url"] = ai_url
                        try:
                            st.switch_page("pages/6_AI_ANALYSIS.py")
                        except Exception:
                            st.info("Open the AI Pricing Analysis page from the sidebar to view this listing.")

section_heading("Pipeline Health", "Current processing health across link intake, normalisation, exclusions, and AI analysis.")
links_count = count_csv_records(LINKS_FILE)
raw_count = count_csv_records(RAW_FILE)
normalised_count = count_csv_records(NORMALISED_FILE)
excluded_count = count_csv_records(EXCLUDED_FILE)
analysed_count = len(valuations_df) if not valuations_df.empty else 0
analysis_target = len(ai_active_scope_df) if not ai_active_scope_df.empty else 0
if analysis_target and not valuations_df.empty:
    ai_active_urls = set(ai_active_scope_df["url"].dropna().astype(str))
    analysed_count = int(valuations_df["url"].astype(str).isin(ai_active_urls).sum())
analysis_ratio = (analysed_count / analysis_target) if analysis_target else None

health_cols = st.columns(4)
with health_cols[0]:
    _render_health_card(
        "Links scraped",
        _format_rows(links_count),
        describe_last_run(LINKS_FILE)[0],
        _health_tone(links_count, expected_min=1),
    )
with health_cols[1]:
    normalise_tone = "red"
    if normalised_count and raw_count and normalised_count >= max(int(raw_count * 0.8), 1):
        normalise_tone = "green"
    elif normalised_count:
        normalise_tone = "orange"
    _render_health_card(
        "Vehicles normalized",
        _format_rows(normalised_count),
        describe_last_run(NORMALISED_FILE)[0],
        normalise_tone,
    )
with health_cols[2]:
    exclusion_last_text, exclusion_last_ts = describe_last_run(EXCLUDED_FILE)
    exclusion_age_hours = (
        (datetime.now(timezone.utc) - exclusion_last_ts).total_seconds() / 3600
        if exclusion_last_ts is not None
        else None
    )
    exclusion_tone = (
        "green" if exclusion_age_hours is not None and exclusion_age_hours <= 24
        else "orange" if exclusion_age_hours is not None and exclusion_age_hours <= 48
        else "red"
    )
    _render_health_card(
        "Exclusion log rows",
        _format_rows(excluded_count),
        exclusion_last_text,
        exclusion_tone,
    )
with health_cols[3]:
    _render_health_card(
        "Vehicles analysed",
        _format_rows(analysed_count),
        f"{analysis_ratio:.0%} of filtered active listings" if analysis_ratio is not None else "No active listings loaded",
        _coverage_tone(analysis_ratio),
    )

section_heading("AI Coverage", "Curve coverage health across the current active listing set.")
active_curve_count = 0
active_no_curve_count = 0
curve_coverage_pct = None
if not active_scope_df.empty and "canonical_tag" in active_scope_df.columns:
    canonical_series = active_scope_df["canonical_tag"].fillna("").astype(str).str.strip()
    active_curve_count = int(canonical_series.isin(curve_tags).sum())
    active_no_curve_count = int((~canonical_series.isin(curve_tags)).sum())
    total_active_curve_rows = active_curve_count + active_no_curve_count
    curve_coverage_pct = (active_curve_count / total_active_curve_rows) if total_active_curve_rows else None

coverage_cols = st.columns(3)
coverage_cols[0].metric("Listings With Curves", f"{active_curve_count:,}")
coverage_cols[1].metric("Listings Without Curves", f"{active_no_curve_count:,}")
coverage_cols[2].metric(
    "Curve Coverage %",
    f"{curve_coverage_pct * 100:,.1f}%" if curve_coverage_pct is not None else "N/A",
)
section_heading("Status Snapshot", "Distribution of tracked listings by workflow state.")
tracked_counts = {
    "active": int(len(active_scope_df)),
    "sold": int(len(sold_scope_df)),
    "referred": int(len(referred_scope_df)),
}
tracked_total = sum(tracked_counts.values())
other_total = 0
status_columns = st.columns(5)
render_metric(status_columns[0], "Visible Listings", tracked_total)
for idx, (code, label) in enumerate(tracked_statuses, start=1):
    count = tracked_counts.get(code, 0)
    share = (count / tracked_total) if tracked_total else None
    render_metric(status_columns[idx], label, count, share)
share_other = (other_total / tracked_total) if tracked_total else None
render_metric(status_columns[-1], "Other / Unknown", other_total, share_other)

status_table = pd.DataFrame(
    [
        {"Status": "Active", "Listings": tracked_counts["active"]},
        {"Status": "Sold", "Listings": tracked_counts["sold"]},
        {"Status": "Referred", "Listings": tracked_counts["referred"]},
        {"Status": "Other / Unknown", "Listings": other_total},
    ]
).assign(Share=lambda frame: frame["Listings"] / tracked_total if tracked_total else 0)
status_table["Status"] = status_table["Status"].astype(str).str.replace("_", " ").str.title()
status_table["Share"] = status_table["Share"].map(lambda value: f"{value:.1%}")

section_heading("Status Breakdown", "All statuses ranked by listing volume.")
st.dataframe(status_table, width="stretch", hide_index=True)


def unique_count(column: str) -> int:
    if column not in df.columns:
        return 0
    series = df[column].dropna().astype(str).str.strip()
    series = series[series != ""]
    return int(series.nunique())


section_heading("Inventory Coverage", "Distinct values across key identifiers.")
coverage_columns = st.columns(4)
coverage_config = [
    ("make", "Unique Makes"),
    ("model", "Unique Models"),
    ("auction_house", "Auction Houses"),
    ("location", "Locations"),
]
for column, (field, label) in zip(coverage_columns, coverage_config):
    column.metric(label, f"{unique_count(field):,}")


def build_top_table(column: str, display_name: str, limit: int = 10) -> pd.DataFrame | None:
    if column not in df.columns:
        return None
    series = (
        df[column]
        .fillna("Unknown")
        .astype(str)
        .str.strip()
    )
    series = series.replace("", "Unknown")
    counts = (
        series.value_counts()
        .head(limit)
        .rename_axis(display_name)
        .reset_index(name="Listings")
    )
    return counts


section_heading("Top Sources & Makes", "Highest-volume channels in the current dataset.")
top_columns = st.columns(2)
with top_columns[0]:
    st.markdown("**By Auction House**")
    auction_house_table = build_top_table("auction_house", "Auction House")
    if auction_house_table is not None and not auction_house_table.empty:
        st.dataframe(auction_house_table, width="stretch", hide_index=True)
    else:
        st.info("No auction house data captured yet.")

with top_columns[1]:
    st.markdown("**By Make**")
    make_table = build_top_table("make", "Make")
    if make_table is not None and not make_table.empty:
        st.dataframe(make_table, width="stretch", hide_index=True)
    else:
        st.info("No make data available.")

scored_df = safe_read_csv(SCORED_FILE)

links_last_text, _ = describe_last_run(LINKS_FILE)
details_last_text, _ = describe_last_run(CSV_FILE)
active_last_text, _ = describe_last_run(ACTIVE_FILE)
sold_last_text, _ = describe_last_run(SOLD_FILE)
referred_last_text, _ = describe_last_run(REFERRED_FILE)
autotrader_last_text, _ = describe_last_run(AUTOTRADER_FILE)
master_last_text = describe_latest_run(CSV_FILE, SOLD_FILE, REFERRED_FILE)

ai_latest_ts: datetime | None = None
if not valuations_df.empty and "analysis_timestamp" in valuations_df.columns:
    timestamps = valuations_df["analysis_timestamp"].dropna()
    if not timestamps.empty:
        latest_stamp = timestamps.max()
        if hasattr(latest_stamp, "to_pydatetime"):
            ai_latest_ts = latest_stamp.to_pydatetime()
        elif isinstance(latest_stamp, datetime):
            ai_latest_ts = latest_stamp
        if ai_latest_ts and ai_latest_ts.tzinfo is None:
            ai_latest_ts = ai_latest_ts.replace(tzinfo=timezone.utc)
ai_last_text = format_last_run(ai_latest_ts)
ai_avg_score = valuations_df["score_value"].dropna().mean() if "score_value" in valuations_df else None
transparency_confidence_avg = None
transparency_confidence_share = None
transparency_profit_df = pd.DataFrame()
if not active_scope_df.empty:
    confidence_series = pd.to_numeric(active_scope_df.get("confidence"), errors="coerce").dropna()
    if not confidence_series.empty:
        transparency_confidence_avg = float(confidence_series.mean())
        transparency_confidence_share = float((confidence_series >= 0.75).mean())

    profit_source = (
        active_scope_df["active_profit_value"]
        if "active_profit_value" in active_scope_df.columns
        else pd.Series(index=active_scope_df.index, dtype=float)
    )
    profit_series = pd.to_numeric(profit_source, errors="coerce")
    if profit_series.notna().any():
        profit_bands = pd.cut(
            profit_series,
            bins=[-10_000_000, 0, 2_000, 5_000, 10_000, 100_000_000],
            labels=["<= $0", "$1-$2k", "$2k-$5k", "$5k-$10k", "$10k+"],
            include_lowest=True,
        )
        transparency_profit_df = (
            pd.DataFrame({"Profit Band": profit_bands})
            .dropna()
            .value_counts()
            .rename("Listings")
            .reset_index()
        )


def _format_number(value: float | int | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    return f"{int(round(value)):,}"


closing_24h = 0
if not active_live_df.empty and "time_remaining_or_date_sold" in active_live_df.columns:
    hours_series = active_live_df["time_remaining_or_date_sold"].apply(extract_hours_remaining)
    closing_24h = int(sum(1 for value in hours_series if value is not None and value <= 24))

median_bids = None
avg_active_price = None
if not active_live_df.empty:
    bids_series = pd.to_numeric(active_live_df.get("bids"), errors="coerce")
    if bids_series.notna().any():
        median_bids = bids_series.median()
    price_series = active_live_df["price"].apply(parse_currency_value).dropna()
    if not price_series.empty:
        avg_active_price = float(price_series.mean())

model_last_text, _ = describe_last_run(SCORED_FILE)
settled_count = 0
accuracy_display = "N/A"
if not scored_df.empty and "hit" in scored_df.columns:
    hit_series = scored_df["hit"]
    if hit_series.dtype == object:
        normalised = hit_series.astype(str).str.lower().map(
            {"true": True, "false": False, "1": True, "0": False}
        )
        hit_series = normalised
    valid_hits = hit_series[hit_series.notna()]
    settled_count = int(len(valid_hits))
    if settled_count:
        accuracy = valid_hits.astype(float).mean()
        accuracy_display = f"{accuracy * 100:,.1f}%"

section_heading("Decision Health", "Coverage, confidence, and profit-shape health for the current filtered universe.")
transparency_cols = st.columns(3)
transparency_cols[0].metric(
    "Curve Coverage %",
    f"{curve_coverage_pct * 100:,.1f}%" if curve_coverage_pct is not None else "N/A",
    f"{active_curve_count:,} with curves / {active_no_curve_count:,} without",
)
transparency_cols[1].metric(
    "Model Confidence",
    f"{transparency_confidence_avg * 100:,.1f}%" if transparency_confidence_avg is not None else "N/A",
    (
        f"{transparency_confidence_share * 100:,.0f}% high-confidence listings"
        if transparency_confidence_share is not None
        else "No active confidence data"
    ),
)
transparency_cols[2].metric(
    "Observed Accuracy",
    accuracy_display,
    f"{settled_count:,} settled scored listings",
)

transparency_left, transparency_right = st.columns([1.3, 1], gap="large")
with transparency_left:
    st.markdown("**Profit Distribution**")
    st.caption("Expected profit spread across currently visible active listings.")
    if transparency_profit_df.empty:
        st.info("No profit distribution available for the current filter set.")
    else:
        profit_chart = transparency_profit_df.set_index("Profit Band")
        st.bar_chart(profit_chart)
with transparency_right:
    st.markdown("**Decision Notes**")
    st.markdown(
        "\n".join(
            [
                f"- AI valuations refreshed: {ai_last_text}",
                f"- Scoring model refreshed: {model_last_text}",
                f"- Average score /10: {f'{ai_avg_score:.1f}' if ai_avg_score is not None else 'N/A'}",
                f"- Active listings in scope: {len(active_scope_df):,}",
            ]
        )
    )

section_heading("Sample Listings", "Preview the first 10 records from the master file.")
st.dataframe(df.head(10), width="stretch", hide_index=True)
