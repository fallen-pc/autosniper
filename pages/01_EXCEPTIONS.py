import pandas as pd
import streamlit as st

from shared.curves import curve_model
from shared.ops_utils import (
    apply_global_filters,
    ISSUE_DEFINITIONS,
    build_curve_meta,
    build_issue_index,
    build_tag_group_map,
    confidence_bucket,
    explode_issues,
    format_issue_label,
    issue_hint,
    load_active_df,
    load_curves_df,
    load_flags_df,
    load_group_map_df,
    load_static_df,
    load_valuations_df,
    parse_time_remaining_hours,
    time_bucket,
)
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Exceptions - Ops", layout="wide")
inject_global_styles()
display_banner()
page_intro("EXCEPTIONS", "Ruthless list of everything broken or incomplete.", show_logo=False)

static_df = load_static_df()
active_df = load_active_df()
valuations_df = load_valuations_df()

if static_df.empty:
    st.warning("No static listings available. Run the scrapers to populate vehicle_static_details.csv.")
    st.stop()

curves_df = load_curves_df()
group_map_df = load_group_map_df()
tag_group_map = build_tag_group_map(group_map_df)
curve_meta = build_curve_meta(curves_df)
issue_df = build_issue_index(static_df, active_df, valuations_df, tag_group_map, curve_meta)
issue_df = issue_df[issue_df["issue_count"] > 0]
flags_df = load_flags_df()
flag_lookup = {}
if not flags_df.empty and "url" in flags_df.columns:
    flags_df["timestamp"] = pd.to_datetime(flags_df.get("timestamp"), errors="coerce")
    latest_flags = flags_df.sort_values("timestamp").drop_duplicates("url", keep="last")
    flag_lookup = latest_flags.set_index("url").to_dict(orient="index")

if issue_df.empty:
    st.success("No exceptions found. Everything is clean.")
    st.stop()

exploded = explode_issues(issue_df)
summary = (
    exploded.groupby("issue_code")
    .size()
    .reset_index(name="count")
    .sort_values("count", ascending=False)
)
summary["label"] = summary["issue_code"].apply(format_issue_label)
summary["hint"] = summary["issue_code"].apply(issue_hint)
summary["severity"] = summary["issue_code"].apply(
    lambda code: ISSUE_DEFINITIONS.get(code, {}).get("severity", "gray")
)

section_heading("Global Filters", "Filters persist across the Ops + QA + Builder pages.")
filter_container = st.container()
with filter_container:
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    makes = sorted(static_df["make"].dropna().unique().tolist()) if "make" in static_df.columns else []
    models = sorted(static_df["model"].dropna().unique().tolist()) if "model" in static_df.columns else []
    statuses = sorted(active_df["status"].dropna().unique().tolist()) if "status" in active_df.columns else []
    verdicts = sorted(valuations_df["verdict"].dropna().unique().tolist()) if "verdict" in valuations_df.columns else []
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
    issues_only = c9.checkbox("Only listings with issues", value=True, key="ops_issues_only")

section_heading("Exception Buckets", "Pick a reason code and fix it now.")
st.dataframe(summary[["issue_code", "label", "count", "severity", "hint"]], use_container_width=True)

selected_issue = st.selectbox(
    "Issue group",
    options=summary["issue_code"].tolist(),
    format_func=lambda code: f"{format_issue_label(code)} ({code})",
)

left, right = st.columns([3, 2])

with left:
    section_heading("Exception List", f"Listings flagged with {selected_issue}.")
    issue_urls = exploded[exploded["issue_code"] == selected_issue]["url"].unique().tolist()
    subset = static_df[static_df["url"].isin(issue_urls)].copy()
    if not active_df.empty:
        subset = subset.merge(
            active_df[["url", "status", "time_remaining_or_date_sold", "price", "bids"]],
            on="url",
            how="left",
        )
    if not valuations_df.empty:
        subset = subset.merge(
            valuations_df[["url", "verdict", "confidence"]],
            on="url",
            how="left",
        )
    if "time_remaining_or_date_sold" in subset.columns:
        subset["time_remaining_hours"] = subset["time_remaining_or_date_sold"].apply(parse_time_remaining_hours)
    else:
        subset["time_remaining_hours"] = pd.Series([None] * len(subset), index=subset.index)
    subset["time_bucket"] = subset["time_remaining_hours"].apply(time_bucket)
    subset["confidence_bucket"] = subset.get("confidence", pd.Series(dtype=float)).apply(confidence_bucket)
    if curve_model() == "v2":
        subset["has_curve"] = subset["canonical_tag"].apply(
            lambda tag: bool(tag) and str(tag).strip() in curve_meta
        )
    else:
        subset["has_curve"] = subset["canonical_tag"].apply(
            lambda tag: bool(tag) and tag_group_map.get(str(tag).strip()) in curve_meta
        )
    subset["is_flagged"] = subset["url"].map(lambda url: bool(flag_lookup.get(url)))
    subset = apply_global_filters(
        subset,
        make_filter=make_filter,
        model_filter=model_filter,
        status_filter=status_filter,
        verdict_filter=verdict_filter,
        confidence_filter=confidence_filter,
        time_bucket_filter=time_filter,
        has_curve_filter=None if has_curve_filter == "All" else has_curve_filter,
    )
    if hide_flagged:
        subset = subset[~subset["is_flagged"]]
    if issues_only:
        subset = subset[subset["url"].isin(issue_df["url"])]
    display_cols = [
        "issue_codes",
        "year",
        "make",
        "model",
        "variant",
        "odometer_reading",
        "vin",
        "canonical_tag",
        "canonical_reason",
        "status",
        "time_remaining_or_date_sold",
        "price",
        "bids",
        "url",
    ]
    subset = subset.merge(issue_df[["url", "issue_codes", "issue_summary"]], on="url", how="left")
    subset["issue_codes"] = subset["issue_codes"].apply(
        lambda codes: " ".join(f"[{code}]" for code in codes) if isinstance(codes, list) else ""
    )

    display_cols = [col for col in display_cols if col in subset.columns]
    table_df = subset[display_cols].copy()
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
    if len(selected_rows) == 1:
        st.session_state["ops_selected_url"] = selected_rows.iloc[0]["url"]
    elif len(selected_rows) > 1:
        st.info("Select one row to inspect it in the side panel.")

with right:
    section_heading("Fix Kit", "Open the right tool for this exception.")
    selected_url = st.session_state.get("ops_selected_url")
    if not selected_url:
        st.info("Select a row on the left to populate this panel.")
    else:
        row = subset[subset["url"] == selected_url]
        if row.empty:
            st.warning("Selected URL is no longer in this exception list.")
        else:
            data = row.iloc[0]
            title = " ".join(
                part
                for part in [
                    str(data.get("year", "")).strip(),
                    str(data.get("make", "")).strip(),
                    str(data.get("model", "")).strip(),
                    str(data.get("variant", "")).strip(),
                ]
                if part
            )
            st.markdown(f"**{title or 'Listing'}**")
            st.caption(data.get("url", ""))

            if st.button("Open detail view", key="exceptions_open_detail"):
                st.session_state["ops_selected_url"] = data.get("url")
                try:
                    st.switch_page("pages/02_DETAIL.py")
                except Exception:
                    st.info("Open the Detail page from the sidebar to view this listing.")

            if st.button("Open curves", key="exceptions_open_curves"):
                st.session_state["ops_selected_tag"] = data.get("canonical_tag")
                try:
                    st.switch_page("pages/03_CURVES.py")
                except Exception:
                    st.info("Open the Curves page from the sidebar to view this tag.")

            if st.button("Open mappings", key="exceptions_open_mappings"):
                try:
                    st.switch_page("pages/04_MAPPINGS.py")
                except Exception:
                    st.info("Open the Mappings page from the sidebar to edit rules.")
