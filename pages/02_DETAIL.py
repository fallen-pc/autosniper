import pandas as pd
import streamlit as st

from shared.ops_utils import (
    append_curve_queue,
    append_flag,
    append_note,
    build_curve_meta,
    build_issue_index,
    build_tag_group_map,
    load_active_df,
    load_curves_df,
    load_flags_df,
    load_group_map_df,
    load_notes_df,
    load_static_df,
    load_valuations_df,
)
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Detail - QA", layout="wide")
inject_global_styles()
display_banner()
page_intro("DETAIL", "Full transparency for a single URL.", show_logo=False)

static_df = load_static_df()
active_df = load_active_df()
valuations_df = load_valuations_df()
curves_df = load_curves_df()
group_map_df = load_group_map_df()
tag_group_map = build_tag_group_map(group_map_df)
curve_meta = build_curve_meta(curves_df)
issue_df = build_issue_index(static_df, active_df, valuations_df, tag_group_map, curve_meta)

urls = sorted(
    {
        *static_df.get("url", pd.Series(dtype=str)).dropna().tolist(),
        *active_df.get("url", pd.Series(dtype=str)).dropna().tolist(),
    }
)

selected_default = st.session_state.get("ops_selected_url")
if selected_default and selected_default not in urls:
    urls.append(selected_default)

section_heading("Pick a URL", "Paste a URL or choose from the list.")
input_col, pick_col = st.columns([2, 3])
with input_col:
    manual_url = st.text_input("Paste URL", value=selected_default or "")
with pick_col:
    selected_url = st.selectbox("Or select", options=urls, index=urls.index(selected_default) if selected_default in urls else 0)

if manual_url.strip():
    selected_url = manual_url.strip()

if not selected_url:
    st.info("Select a URL to view details.")
    st.stop()

st.session_state["ops_selected_url"] = selected_url

static_row = static_df[static_df["url"] == selected_url]
active_row = active_df[active_df["url"] == selected_url]
valuation_row = valuations_df[valuations_df["url"] == selected_url]
issue_row = issue_df[issue_df["url"] == selected_url]
notes_df = load_notes_df()
flags_df = load_flags_df()

if static_row.empty and active_row.empty:
    st.warning("URL not found in either static or active datasets.")
    st.stop()

if not issue_row.empty:
    issue_summary = issue_row.iloc[0].to_dict()
else:
    issue_summary = {"severity": "green", "issue_summary": ""}

def _value(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    value = frame.iloc[0].get(column)
    return "" if pd.isna(value) else str(value).strip()


header_cols = st.columns([3, 2])
with header_cols[0]:
    title = " ".join(
        part
        for part in [
            _value(active_row, "year") or _value(static_row, "year"),
            _value(active_row, "make") or _value(static_row, "make"),
            _value(active_row, "model") or _value(static_row, "model"),
            _value(active_row, "variant") or _value(static_row, "variant"),
        ]
        if part
    )
    st.markdown(f"## {title or 'Listing'}")
    st.caption(selected_url)
with header_cols[1]:
    st.markdown("**Issues**")
    st.write(issue_summary.get("issue_summary", "None"))
    st.markdown("**Severity**")
    st.write(issue_summary.get("severity", "green"))

section_heading("Auction State", "Live auction context from the active snapshot.")
if active_row.empty:
    st.info("No active snapshot available for this URL.")
else:
    st.dataframe(active_row, use_container_width=True, hide_index=True)

section_heading("Static Details", "Normalized identity + spec fields.")
if static_row.empty:
    st.info("No static record available for this URL.")
else:
    st.dataframe(static_row, use_container_width=True, hide_index=True)

section_heading("AI Verdict", "Latest pricing decision if available.")
if valuation_row.empty:
    st.info("No valuation row available yet. Run AI pricing to populate.")
else:
    st.dataframe(valuation_row, use_container_width=True, hide_index=True)

section_heading("Curve Coverage", "Curve availability for this canonical tag.")
canonical_tag = ""
if not static_row.empty:
    canonical_tag = str(static_row.iloc[0].get("canonical_tag", "")).strip()
if not canonical_tag:
    st.info("No canonical tag available for this URL.")
else:
    group_id = tag_group_map.get(canonical_tag)
    if not group_id:
        st.warning("No group_id mapping found for this canonical tag.")
    else:
        meta = curve_meta.get(group_id)
        if not meta:
            st.warning("No curve rows found for this group_id.")
        else:
            st.write(
                {
                    "canonical_tag": canonical_tag,
                    "group_id": group_id,
                    "anchor_years": meta.anchor_years,
                    "km_anchors": meta.km_anchors,
                    "last_updated": meta.last_updated,
                }
            )

section_heading("Fix Actions", "Make changes the moment you spot a problem.")

actions_left, actions_right = st.columns([2, 2])

with actions_left:
    st.markdown("**Notes**")
    note_text = st.text_area("Add a note", value="", height=100)
    if st.button("Save note", key="detail_save_note"):
        if note_text.strip():
            append_note(selected_url, note_text.strip())
            st.success("Note saved.")
        else:
            st.warning("Note is empty.")

    if not notes_df.empty and "url" in notes_df.columns:
        notes = notes_df[notes_df["url"] == selected_url].copy()
        if not notes.empty:
            st.markdown("**Existing notes**")
            st.dataframe(notes.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)

with actions_right:
    st.markdown("**Flags**")
    flag_choice = st.selectbox(
        "Mark listing", options=["", "NON_VEHICLE", "WITHDRAWN", "BROKEN_URL"], key="detail_flag_choice"
    )
    flag_reason = st.text_input("Reason (optional)", value="", key="detail_flag_reason")
    if st.button("Save flag", key="detail_save_flag"):
        if flag_choice:
            append_flag(selected_url, flag_choice, flag_reason)
            st.success("Flag saved.")
        else:
            st.warning("Pick a flag before saving.")

    if not flags_df.empty and "url" in flags_df.columns:
        flags = flags_df[flags_df["url"] == selected_url].copy()
        if not flags.empty:
            st.markdown("**Flag history**")
            st.dataframe(flags.sort_values("timestamp", ascending=False), use_container_width=True, hide_index=True)

    st.markdown("**Curve queue**")
    if st.button("Add to needs-curve queue", key="detail_curve_queue"):
        if canonical_tag:
            append_curve_queue(selected_url, canonical_tag)
            st.success("Queued for curve work.")
        else:
            st.warning("Canonical tag is missing. Cannot queue.")

section_heading("Quick Links", "Jump to other tools fast.")
links = st.columns(3)
with links[0]:
    link_button = getattr(st, "link_button", None)
    if callable(link_button):
        link_button("Open listing", selected_url)
    else:
        st.markdown(f"[Open listing]({selected_url})")
with links[1]:
    if st.button("Open curves", key="detail_open_curves"):
        st.session_state["ops_selected_tag"] = canonical_tag
        try:
            st.switch_page("pages/03_CURVES.py")
        except Exception:
            st.info("Open the Curves page from the sidebar to view this tag.")
with links[2]:
    if st.button("Open mappings", key="detail_open_mappings"):
        try:
            st.switch_page("pages/04_MAPPINGS.py")
        except Exception:
            st.info("Open the Mappings page from the sidebar to edit rules.")
