import pandas as pd
import streamlit as st

from shared.curves import curve_dataset_name, curve_model
from shared.ops_utils import (
    build_curve_meta,
    build_tag_group_map,
    load_active_df,
    load_curves_df,
    load_group_map_df,
)
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Curves - Builder", layout="wide")
inject_global_styles()
display_banner()
page_intro("CURVES LIBRARY", "Coverage, gaps, and quick links into the curve editor.", show_logo=False)

active_df = load_active_df()
curves_df = load_curves_df()
group_map_df = load_group_map_df()
tag_group_map = build_tag_group_map(group_map_df)
curve_meta = build_curve_meta(curves_df)

if curves_df.empty:
    st.warning(f"No {curve_dataset_name()} available yet. Build curves to populate the library.")

active_counts = {}
if not active_df.empty and "canonical_tag" in active_df.columns:
    active_counts = (
        active_df["canonical_tag"].astype(str).str.strip().value_counts().to_dict()
    )

missing_map = {}

rows = []
tag_sources = set(active_counts.keys())
if not group_map_df.empty and "canonical_tag" in group_map_df.columns:
    tag_sources.update(group_map_df["canonical_tag"].astype(str).str.strip().tolist())
canonical_tags = sorted({tag for tag in tag_sources if tag and tag != "UNCLASSIFIED"})
for tag in canonical_tags:
    group_id = tag if curve_model() == "v2" else tag_group_map.get(tag, "")
    meta = curve_meta.get(group_id)
    curve_rows = curves_df[curves_df["group_id"] == group_id] if group_id else pd.DataFrame()
    rows.append(
        {
            "canonical_tag": tag,
            "group_id": group_id,
            "active_count": active_counts.get(tag, 0),
            "curve_rows": len(curve_rows),
            "anchor_years": ", ".join(str(val) for val in meta.anchor_years) if meta else "",
            "last_updated": meta.last_updated if meta else None,
            "missing_anchors": missing_map.get(group_id, ""),
        }
    )

library_df = pd.DataFrame(rows)
if curve_model() == "v2" and "group_id" in library_df.columns:
    library_df = library_df.drop(columns=["group_id"])

section_heading("Curves Library", "Search by canonical_tag and jump into the editor.")
search = st.text_input("Search canonical_tag", value="")
filtered_df = library_df.copy()
if search:
    filtered_df = filtered_df[filtered_df["canonical_tag"].str.contains(search, case=False, na=False)]

left, right = st.columns([3, 2])

with left:
    if filtered_df.empty:
        st.info("No curve rows match the current search.")
    else:
        table_df = filtered_df.copy()
        table_df.insert(0, "Select", False)
        edited = st.data_editor(
            table_df,
            hide_index=True,
            use_container_width=True,
            disabled=[col for col in table_df.columns if col != "Select"],
            column_config={"Select": st.column_config.CheckboxColumn("Select")},
        )
        selected = edited[edited["Select"]]
        if len(selected) == 1:
            st.session_state["ops_selected_tag"] = selected.iloc[0]["canonical_tag"]
        elif len(selected) > 1:
            st.info("Select one row to view details in the side panel.")

with right:
    section_heading("Curve Detail", "Quick link to the curve builder.")
    selected_tag = st.session_state.get("ops_selected_tag")
    if not selected_tag:
        st.info("Select a row to view curve details.")
    else:
        selected = filtered_df[filtered_df["canonical_tag"] == selected_tag]
        if selected.empty:
            st.warning("Selected tag is not in the filtered list.")
        else:
            row = selected.iloc[0]
            st.write(
                {
                    "canonical_tag": row.get("canonical_tag"),
                    "curve_key": row.get("canonical_tag") if curve_model() == "v2" else row.get("group_id"),
                    "active_count": row.get("active_count"),
                    "curve_rows": row.get("curve_rows"),
                    "anchor_years": row.get("anchor_years"),
                    "last_updated": row.get("last_updated"),
                    "missing_anchors": row.get("missing_anchors"),
                }
            )
            if st.button("Open curve builder", key="curves_open_builder"):
                st.session_state["curve_builder_tag"] = row.get("canonical_tag")
                try:
                    st.switch_page("pages/13_CURVE_BUILDER.py")
                except Exception:
                    st.info("Open the Curve Builder page from the sidebar to edit curves.")
