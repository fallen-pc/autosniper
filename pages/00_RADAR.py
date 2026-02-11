import pandas as pd
import streamlit as st

from shared.curves import curve_model
from shared.ops_utils import (
    apply_global_filters,
    build_curve_meta,
    build_issue_index,
    build_tag_group_map,
    confidence_bucket,
    load_active_df,
    load_curves_df,
    load_flags_df,
    load_group_map_df,
    load_static_df,
    load_valuations_df,
    parse_currency,
    parse_percent,
    parse_time_remaining_hours,
    time_bucket,
)
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Radar - Ops", layout="wide")
inject_global_styles()
display_banner()
page_intro("RADAR", "Ops view: what to bid, ignore, and fix today.", show_logo=False)

static_df = load_static_df()
active_df = load_active_df()
valuations_df = load_valuations_df()

if active_df.empty:
    st.warning("No active listings available. Run the scrapers to populate active_vehicle_details.csv.")
    st.stop()

curves_df = load_curves_df()
group_map_df = load_group_map_df()
tag_group_map = build_tag_group_map(group_map_df)
curve_meta = build_curve_meta(curves_df)
issue_df = build_issue_index(static_df, active_df, valuations_df, tag_group_map, curve_meta)

radar_df = active_df.merge(issue_df, on="url", how="left")
if not valuations_df.empty:
    radar_df = radar_df.merge(valuations_df, on="url", how="left", suffixes=("", "_ai"))

if "confidence" not in radar_df.columns:
    radar_df["confidence"] = None
if "verdict" not in radar_df.columns and "computed_verdict" in radar_df.columns:
    radar_df["verdict"] = radar_df["computed_verdict"]

radar_df["time_remaining_hours"] = radar_df["time_remaining_or_date_sold"].apply(parse_time_remaining_hours)
radar_df["time_bucket"] = radar_df["time_remaining_hours"].apply(time_bucket)
radar_df["confidence_bucket"] = radar_df["confidence"].apply(confidence_bucket)
if curve_model() == "v2":
    radar_df["has_curve"] = radar_df["canonical_tag"].apply(
        lambda tag: bool(tag) and str(tag).strip() in curve_meta
    )
else:
    radar_df["has_curve"] = radar_df["canonical_tag"].apply(
        lambda tag: bool(tag) and tag_group_map.get(str(tag).strip()) in curve_meta
    )

radar_df["profit_margin_value"] = radar_df.get("profit_margin_percent", pd.Series(dtype=float)).apply(parse_percent)
radar_df["recommended_max_bid_value"] = radar_df.get("recommended_max_bid", pd.Series(dtype=float)).apply(parse_currency)
radar_df["resale_mid_value"] = radar_df.get("resale_mid", pd.Series(dtype=float)).apply(parse_currency)
radar_df["expected_profit_value"] = radar_df.get("expected_profit", pd.Series(dtype=float)).apply(parse_currency)

radar_df["severity"] = radar_df["severity"].fillna("green")
radar_df["issue_summary"] = radar_df["issue_summary"].fillna("")
radar_df["issue_codes"] = radar_df["issue_codes"].apply(
    lambda codes: " ".join(f"[{code}]" for code in codes) if isinstance(codes, list) else ""
)

flags_df = load_flags_df()
flag_lookup = {}
if not flags_df.empty and "url" in flags_df.columns:
    flags_df["timestamp"] = pd.to_datetime(flags_df.get("timestamp"), errors="coerce")
    latest_flags = flags_df.sort_values("timestamp").drop_duplicates("url", keep="last")
    flag_lookup = latest_flags.set_index("url").to_dict(orient="index")

radar_df["flag"] = radar_df["url"].map(lambda url: flag_lookup.get(url, {}).get("flag", ""))
radar_df["flag_reason"] = radar_df["url"].map(lambda url: flag_lookup.get(url, {}).get("reason", ""))
radar_df["is_flagged"] = radar_df["flag"].astype(str).str.strip().ne("")

section_heading("Global Filters", "Filters persist across the Ops + QA + Builder pages.")
filter_container = st.container()
with filter_container:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    makes = sorted(radar_df["make"].dropna().unique().tolist()) if "make" in radar_df.columns else []
    models = sorted(radar_df["model"].dropna().unique().tolist()) if "model" in radar_df.columns else []
    statuses = sorted(radar_df["status"].dropna().unique().tolist()) if "status" in radar_df.columns else []
    verdicts = sorted(radar_df["verdict"].dropna().unique().tolist()) if "verdict" in radar_df.columns else []
    time_buckets = ["<24h", "1-2d", "2-3d", "3+d", "Unknown"]
    confidence_levels = ["High", "Medium", "Low", "Unknown"]

    make_filter = c1.multiselect("Make", makes, key="ops_make_filter")
    model_filter = c2.multiselect("Model", models, key="ops_model_filter")
    status_filter = c3.multiselect("Status", statuses, default=statuses, key="ops_status_filter")
    verdict_filter = c4.multiselect("Verdict", verdicts, key="ops_verdict_filter")
    time_filter = c5.multiselect("Time bucket", time_buckets, default=time_buckets, key="ops_time_filter")
    confidence_filter = c6.multiselect(
        "Confidence", confidence_levels, default=confidence_levels, key="ops_conf_filter"
    )

    c7, c8, c9 = st.columns(3)
    has_curve_filter = c7.selectbox("Has curve", ["All", "Yes", "No"], key="ops_curve_filter")
    hide_flagged = c8.checkbox("Hide flagged listings", value=False, key="ops_hide_flagged")
    issues_only = c9.checkbox("Only listings with issues", value=False, key="ops_issues_only")

filtered_df = apply_global_filters(
    radar_df,
    make_filter=make_filter,
    model_filter=model_filter,
    status_filter=status_filter,
    verdict_filter=verdict_filter,
    confidence_filter=confidence_filter,
    time_bucket_filter=time_filter,
    has_curve_filter=None if has_curve_filter == "All" else has_curve_filter,
)

if hide_flagged:
    filtered_df = filtered_df[~filtered_df["is_flagged"]]
if issues_only:
    filtered_df = filtered_df[filtered_df["issue_count"].fillna(0) > 0]

filtered_df["profit_sort"] = filtered_df["profit_margin_value"].where(
    filtered_df["confidence"].fillna(0) >= 0.7, -9999
)
filtered_df = filtered_df.sort_values(by=["profit_sort", "confidence"], ascending=[False, False])

metrics = st.columns(4)
metrics[0].metric("Active listings", f"{len(active_df):,}")
metrics[1].metric("Visible", f"{len(filtered_df):,}")
metrics[2].metric("With issues", f"{int((filtered_df['issue_count'].fillna(0) > 0).sum()):,}")
metrics[3].metric("No curve", f"{int((filtered_df['has_curve'] == False).sum()):,}")

left, right = st.columns([3, 2])

with left:
    section_heading("Scan View", "Fast decisions. Click a row to inspect in the side panel.")

    display_cols = [
        "severity",
        "issue_codes",
        "verdict",
        "recommended_max_bid",
        "resale_mid",
        "profit_margin_percent",
        "year",
        "make",
        "model",
        "variant",
        "odometer_reading",
        "fuel_type",
        "transmission",
        "confidence",
        "time_remaining_or_date_sold",
        "price",
        "bids",
        "location",
        "canonical_tag",
        "url",
    ]
    display_cols = [col for col in display_cols if col in filtered_df.columns]
    table_df = filtered_df[display_cols].copy()
    table_df.insert(0, "Select", False)

    edited = st.data_editor(
        table_df,
        hide_index=True,
        use_container_width=True,
        disabled=[col for col in table_df.columns if col != "Select"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select"),
            "url": st.column_config.LinkColumn("Listing", display_text="Open"),
        },
    )

    selected_rows = edited[edited["Select"]]
    selected_url = None
    if len(selected_rows) == 1:
        selected_url = selected_rows.iloc[0]["url"]
        st.session_state["ops_selected_url"] = selected_url
    elif len(selected_rows) > 1:
        st.info("Select one row to inspect it in the side panel.")

with right:
    section_heading("Inspect + Fix", "Snapshot for the currently selected listing.")
    selected_url = st.session_state.get("ops_selected_url")
    if not selected_url:
        st.info("Select a row on the left to populate this panel.")
    else:
        selected_row = filtered_df[filtered_df["url"] == selected_url]
        if selected_row.empty:
            st.warning("Selected URL is no longer in the filtered results.")
        else:
            row = selected_row.iloc[0]
            title_parts = [str(row.get("year", "")).strip(), str(row.get("make", "")).strip(),
                           str(row.get("model", "")).strip(), str(row.get("variant", "")).strip()]
            title = " ".join(part for part in title_parts if part)
            st.markdown(f"**{title or 'Listing'}**")
            st.caption(row.get("url", ""))

            st.markdown("**Verdict / Confidence**")
            st.write({
                "verdict": row.get("verdict", "N/A"),
                "confidence": row.get("confidence", "N/A"),
                "issues": row.get("issue_summary", ""),
            })

            st.markdown("**Pricing**")
            st.write({
                "recommended_max_bid": row.get("recommended_max_bid", ""),
                "resale_mid": row.get("resale_mid", ""),
                "profit_margin_percent": row.get("profit_margin_percent", ""),
                "expected_profit": row.get("expected_profit", ""),
            })

            st.markdown("**Actions**")
            if row.get("url"):
                link_button = getattr(st, "link_button", None)
                if callable(link_button):
                    link_button("Open listing", row.get("url"))
                else:
                    st.markdown(f"[Open listing]({row.get('url')})")
            if st.button("Open detail view", key="ops_open_detail"):
                st.session_state["ops_selected_url"] = row.get("url")
                try:
                    st.switch_page("pages/02_DETAIL.py")
                except Exception:
                    st.info("Open the Detail page from the sidebar to view this listing.")
            if st.button("Open curves", key="ops_open_curves"):
                st.session_state["ops_selected_tag"] = row.get("canonical_tag")
                try:
                    st.switch_page("pages/03_CURVES.py")
                except Exception:
                    st.info("Open the Curves page from the sidebar to view this tag.")
