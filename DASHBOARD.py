"""Streamlit overview dashboard for the AutoSniper dataset."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path, ensure_datasets_available
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="AutoSniper - Dashboard", layout="wide")
inject_global_styles()
display_banner()

page_intro("DASHBOARD", "Monitor live stock, track state changes, and review coverage across the intake feeds.")

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
SOLD_FILE = dataset_path("sold_cars.csv")
REFERRED_FILE = dataset_path("referred_cars.csv")
SCORED_FILE = dataset_path("scored_listings.csv")

df = pd.read_csv(CSV_FILE)

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
            background: var(--autosniper-panel);
            border-radius: 20px;
            padding: 1.2rem 1.4rem;
            border: 1px solid var(--autosniper-border);
            box-shadow: 0 22px 42px rgba(13, 2, 45, 0.18);
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
        .top-auction-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 0.65rem;
            margin-top: 0.75rem;
        }
        .top-auction-metric {
            background: rgba(255, 255, 255, 0.8);
            border-radius: 16px;
            padding: 0.6rem 0.8rem;
            border: 1px solid rgba(13, 2, 45, 0.06);
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
            background: rgba(255, 255, 255, 0.86);
            border-radius: 18px;
            border: 1px solid rgba(13, 2, 45, 0.1);
            box-shadow: 0 16px 32px rgba(13, 2, 45, 0.14);
            padding: 1rem 1.2rem;
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
            background: rgba(40, 71, 53, 0.07);
            border-radius: 14px;
            padding: 0.4rem 0.65rem;
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
        return pd.read_csv(file_path, parse_dates=parse_dates)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not read {file_path}: {exc}")
        return pd.DataFrame()


def parse_currency_value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    if not matches:
        return None
    numbers = [float(match) for match in matches]
    if len(numbers) > 1 and "-" in text:
        return sum(numbers) / len(numbers)
    return numbers[0]


def parse_percent_value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("%", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def format_currency_value(value: float | None, default: str = "N/A") -> str:
    if value is None:
        return default
    return f"${value:,.0f}"


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


valuations_df = pd.DataFrame()
if VALUATIONS_FILE.exists():
    valuations_df = safe_read_csv(VALUATIONS_FILE)
    if not valuations_df.empty:
        if "analysis_timestamp" in valuations_df.columns:
            valuations_df["analysis_timestamp"] = pd.to_datetime(
                valuations_df["analysis_timestamp"], errors="coerce"
            )
        valuations_df = valuations_df.sort_values("analysis_timestamp").drop_duplicates("url", keep="last")
        valuations_df["expected_profit_value"] = valuations_df["expected_profit"].apply(parse_currency_value)
        valuations_df["profit_margin_value"] = valuations_df["profit_margin_percent"].apply(parse_percent_value)
        valuations_df["score_value"] = pd.to_numeric(valuations_df.get("score_out_of_10"), errors="coerce")

section_heading(
    "Top Live Auctions",
    "AI valuation signals blended with real-time bids to highlight the three sharpest buying windows.",
)
if valuations_df.empty or active_df.empty:
    st.info("Need both active listings and AI valuations to rank live auctions. Run the AI pricing analysis once.")
else:
    merged_top = active_df.merge(valuations_df, on="url", how="inner", suffixes=("", "_ai"))
    merged_top["current_price_value"] = merged_top["price"].apply(parse_currency_value)
    merged_top["bids_value"] = pd.to_numeric(merged_top.get("bids"), errors="coerce")
    merged_top["potential_rank"] = (
        merged_top["score_value"].fillna(0) * 100
        + merged_top["profit_margin_value"].fillna(0)
        + merged_top["expected_profit_value"].fillna(0) / 1000
    )
    merged_top = merged_top.sort_values(by=["potential_rank"], ascending=False)
    top_rows = merged_top.head(3)

    if top_rows.empty:
        st.info("AI valuations have not touched any of the current live listings yet.")
    else:
        cards = st.columns(len(top_rows))
        for idx, (row_index, row) in enumerate(top_rows.iterrows()):
            with cards[idx]:
                year = int(row["year"]) if pd.notna(row.get("year")) else ""
                title_parts = [str(part) for part in [year, row.get("make", ""), row.get("model", "")] if str(part).strip()]
                title = " ".join(title_parts) or "Unnamed listing"
                variant = str(row.get("variant", "") or "").strip()
                location = str(row.get("location", "") or "Unknown location")
                time_remaining = str(row.get("time_remaining_or_date_sold", "N/A"))
                current_price = format_currency_value(row.get("current_price_value"))
                manual_override = row.get("manual_carsales_estimate") or row.get("manual_carsales_avg")
                if manual_override:
                    carsales_estimate = manual_override
                else:
                    carsales_estimate = row.get("carsales_price_estimate") or format_currency_value(
                        parse_currency_value(row.get("carsales_price_estimate"))
                    )
                expected_profit = format_currency_value(row.get("expected_profit_value"))
                profit_margin = row.get("profit_margin_percent") or (
                    f"{row['profit_margin_value']:.0f}%" if pd.notna(row.get("profit_margin_value")) else "N/A"
                )
                bids_display = (
                    f"{int(row['bids_value'])}" if pd.notna(row.get("bids_value")) else str(row.get("bids") or "0")
                )
                score_display = (
                    f"{row['score_value']:.1f}/10" if pd.notna(row.get("score_value")) else "Not scored yet"
                )
                ai_url = row.get("url", "")
                st.markdown(
                    clean_html(
                        f"""
                        <div class="top-auction-card">
                            <div class="top-auction-pill">TOP {idx + 1}</div>
                            <h3>{title}</h3>
                            <div class="autosniper-body">{variant or "Variant unavailable"}</div>
                            <div class="autosniper-body" style="color: var(--autosniper-muted);">
                                {location} &bullet; {time_remaining}
                            </div>
                            <div class="top-auction-metrics">
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Current bid</span>
                                    <span class="top-auction-value">{current_price}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Carsales estimate</span>
                                    <span class="top-auction-value">{carsales_estimate or "N/A"}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">Bids / Margin</span>
                                    <span class="top-auction-value">{bids_display} bids | {profit_margin}</span>
                                </div>
                                <div class="top-auction-metric">
                                    <span class="top-auction-label">AI view</span>
                                    <span class="top-auction-value">{score_display}</span>
                                </div>
                            </div>
                            <div class="top-auction-actions">
                                <a class="ghost-button" href="{ai_url}" target="_blank">Open Listing</a>
                            </div>
                        </div>
                        """
                    ),
                    unsafe_allow_html=True,
                )
                if ai_url:
                    if st.button("Open in AI Analysis", key=f"ai-link-{row_index}", use_container_width=True):
                        st.session_state["ai_focus_url"] = ai_url
                        try:
                            st.switch_page("pages/5_AI_ANALYSIS.py")
                        except Exception:
                            st.info("Open the AI Pricing Analysis page from the sidebar to view this listing.")
section_heading("Status Snapshot", "Distribution of tracked listings by workflow state.")
status_columns = st.columns(5)
render_metric(status_columns[0], "Total Listings", total_listings)
for idx, (code, label) in enumerate(tracked_statuses, start=1):
    count = int(status_counts.get(code, 0))
    share = (count / total_listings) if total_listings else None
    render_metric(status_columns[idx], label, count, share)
share_other = (other_total / total_listings) if total_listings else None
render_metric(status_columns[-1], "Other / Unknown", other_total, share_other)

status_table = (
    status_counts.rename_axis("Status")
    .reset_index(name="Listings")
    .assign(Share=lambda frame: frame["Listings"] / total_listings)
)
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

links_df = safe_read_csv(LINKS_FILE)
sold_df = safe_read_csv(SOLD_FILE)
referred_df = safe_read_csv(REFERRED_FILE)
scored_df = safe_read_csv(SCORED_FILE)

links_last_text, _ = describe_last_run(LINKS_FILE)
details_last_text, _ = describe_last_run(CSV_FILE)
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


def _format_number(value: float | int | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    return f"{int(round(value)):,}"


closing_24h = 0
if not active_df.empty and "time_remaining_or_date_sold" in active_df.columns:
    hours_series = active_df["time_remaining_or_date_sold"].apply(extract_hours_remaining)
    closing_24h = int(sum(1 for value in hours_series if value is not None and value <= 24))

median_bids = None
avg_active_price = None
if not active_df.empty:
    bids_series = pd.to_numeric(active_df.get("bids"), errors="coerce")
    if bids_series.notna().any():
        median_bids = bids_series.median()
    price_series = active_df["price"].apply(parse_currency_value).dropna()
    if not price_series.empty:
        avg_active_price = float(price_series.mean())

manual_columns = [
    "manual_carsales_estimate",
    "manual_carsales_avg",
    "manual_instant_offer_estimate",
]
manual_df = pd.DataFrame()
if not valuations_df.empty:
    available_manual_cols = [col for col in manual_columns if col in valuations_df.columns]
    if available_manual_cols:
        mask = valuations_df[available_manual_cols].notna().any(axis=1)
        manual_df = valuations_df[mask].copy()
        manual_price = None
        for col in manual_columns:
            if col in manual_df.columns:
                parsed = manual_df[col].apply(parse_currency_value)
                manual_price = parsed if manual_price is None else manual_price.combine_first(parsed)
        if manual_price is not None:
            manual_df["manual_avg_price"] = manual_price
            manual_df = manual_df.dropna(subset=["manual_avg_price"])

positive_count = 0
avg_positive_gap = None
if not manual_df.empty and not sold_df.empty:
    sale_source = sold_df["sale_price"] if "sale_price" in sold_df.columns else sold_df.get("price")
    sale_values = pd.Series(dtype=float)
    if sale_source is not None:
        sale_values = sale_source.apply(parse_currency_value)
    joined = sold_df.assign(sale_price_value=sale_values)
    joined = joined.merge(manual_df[["url", "manual_avg_price"]], on="url", how="inner")
    joined = joined.dropna(subset=["manual_avg_price", "sale_price_value"])
    if not joined.empty:
        joined["potential_profit"] = joined["manual_avg_price"] - joined["sale_price_value"]
        positives = joined[joined["potential_profit"] > 0]
        positive_count = len(positives)
        if not positives.empty:
            avg_positive_gap = positives["potential_profit"].mean()

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

workflow_cards = [
    {
        "title": "Page 1 - Link Extractor",
        "meta": links_last_text,
        "summary": (
            f"Extracted {len(links_df):,} live auction links."
            if len(links_df)
            else "Waiting for the first scrape to run."
        ),
        "metrics": [
            ("Links tracked", f"{len(links_df):,}"),
        ],
        "page": "pages/1_LINK_EXTRACTOR.py",
    },
    {
        "title": "Page 2 - Detail Extractor",
        "meta": details_last_text,
        "summary": f"Captured {len(df):,} vehicles with {len(active_df):,} still active.",
        "metrics": [
            ("Listings", f"{len(df):,}"),
            ("Active", f"{len(active_df):,}"),
        ],
        "page": "pages/2_VEHICLE_DETAIL_EXTRACTOR.py",
    },
    {
        "title": "Page 3 - Active Listings",
        "meta": details_last_text,
        "summary": (
            f"{len(active_df):,} auctions live - {closing_24h:,} closing < 24h"
            if len(active_df)
            else "No active listings detected."
        ),
        "metrics": [
            ("Median bids", _format_number(median_bids)),
            ("Avg price", format_currency_value(avg_active_price)),
        ],
        "page": "pages/3_ACTIVE_LISTINGS.py",
    },
    {
        "title": "Page 4 - Master Database",
        "meta": master_last_text,
        "summary": f"{len(df):,} active - {len(sold_df):,} sold - {len(referred_df):,} referred.",
        "metrics": [
            ("Sold", f"{len(sold_df):,}"),
            ("Referred", f"{len(referred_df):,}"),
        ],
        "page": "pages/4_MASTER_DATABASE.py",
    },
    {
        "title": "Page 5 - AI Analysis",
        "meta": ai_last_text,
        "summary": (
            f"{len(valuations_df):,} valuations scored."
            if len(valuations_df)
            else "Run AI pricing to generate valuations."
        ),
        "metrics": [
            ("Valuations", f"{len(valuations_df):,}"),
            (
                "Avg score",
                f"{ai_avg_score:.1f}/10"
                if ai_avg_score is not None and not pd.isna(ai_avg_score)
                else "N/A",
            ),
        ],
        "page": "pages/5_AI_ANALYSIS.py",
    },
    {
        "title": "Page 6 - Missed Opportunities",
        "meta": describe_latest_run(SOLD_FILE, VALUATIONS_FILE),
        "summary": (
            f"{positive_count:,} profitable misses flagged."
            if positive_count
            else "Log manual Carsales tables to surface misses."
        ),
        "metrics": [
            ("Manual tables", f"{len(manual_df):,}"),
            ("Avg upside", format_currency_value(avg_positive_gap)),
        ],
        "page": "pages/6_MISSED_OPPORTUNITIES.py",
    },
    {
        "title": "Page 7 - Model Accuracy",
        "meta": model_last_text,
        "summary": (
            f"{settled_count:,} settled deals logged."
            if settled_count
            else "No settled deals available yet."
        ),
        "metrics": [
            ("Scored", f"{len(scored_df):,}"),
            ("Accuracy", accuracy_display),
        ],
        "page": "pages/7_MODEL_ACCURACY.py",
    },
]

section_heading("Workflow Pulse", "Quick readout of when each tool last ran and what it produced.")
if not workflow_cards:
    st.info("No workflow activity detected yet.")
else:
    for start in range(0, len(workflow_cards), 3):
        row_cards = workflow_cards[start : start + 3]
        columns = st.columns(len(row_cards))
        for column, card in zip(columns, row_cards):
            metrics_html = "".join(
                f"""
                <div class="page-status-metric">
                    <div class="page-status-label">{clean_html(label)}</div>
                    <div class="page-status-value">{value}</div>
                </div>
                """
                for label, value in card["metrics"]
            )
            card_html = f"""
                <div class="page-status-card">
                    <h4>{card['title']}</h4>
                    <div class="page-status-meta">{card['meta']}</div>
                    <div class="page-status-highlight">{card['summary']}</div>
                    <div class="page-status-metrics">{metrics_html}</div>
                </div>
            """
            column.markdown(clean_html(card_html), unsafe_allow_html=True)
            page_link = getattr(st, "page_link", None)
            if callable(page_link):
                page_link(card["page"], label="Open page", icon=":material/arrow_outward:")
            else:
                column.markdown(f"[Open page]({card['page']})")


section_heading("Sample Listings", "Preview the first 10 records from the master file.")
st.dataframe(df.head(10), width="stretch", hide_index=True)
