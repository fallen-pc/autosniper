import pandas as pd
import streamlit as st
from shared.navigation import render_sidebar_navigation
from shared.runtime import is_vps_runtime

from shared.csv_utils import read_csv_or_empty
from shared.curves import list_curve_tags, resolve_curve_canonical_tag
from shared.governance import build_curve_coverage_report, summarize_curve_coverage
from shared.ops_utils import build_curve_meta, load_active_df, load_curves_df, load_static_df
from shared.data_loader import dataset_path
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Curves - Library", layout="wide")
render_sidebar_navigation()
inject_global_styles()
display_banner()
page_intro("CURVES LIBRARY", "Inspect saved resale curves and identify missing coverage.", show_logo=False)

active_df = load_active_df()
static_df = load_static_df()
curves_df = load_curves_df()
curve_meta = build_curve_meta(curves_df)
group_map_path = dataset_path("restricted_group_map.csv")
group_map_df = read_csv_or_empty(group_map_path)
coverage_df = build_curve_coverage_report(static_df, group_map_df, curves_df)
coverage_summary = summarize_curve_coverage(coverage_df)

if curves_df.empty:
    st.warning("No curves available yet. Build curves to populate the library.")

metric_a, metric_b, metric_c = st.columns(3)
metric_a.metric("Tags checked", f"{coverage_summary['observed_tags']:,}")
metric_b.metric("Tags with saved curves", f"{coverage_summary['covered_tags']:,}")
metric_c.metric("Tags without curves", f"{coverage_summary['missing_tags']:,}")

st.caption(
    "Coverage checks the union of tags in static listings, the restricted group map and the saved curve library, "
    "including aliases. These are vehicle specification tags, not counts of active vehicles. "
    "A saved curve does not guarantee that a particular vehicle falls within its year and kilometre range."
)

active_counts = {}
if not active_df.empty and "canonical_tag" in active_df.columns:
    active_counts = (
        active_df["canonical_tag"].dropna().astype(str).str.strip().value_counts().to_dict()
    )

rows = []
tag_sources = set(active_counts.keys())
tag_sources.update(list_curve_tags(curves_df))
tag_sources.update(coverage_df.get("canonical_tag", pd.Series(dtype=str)).tolist())
canonical_tags = sorted({tag for tag in tag_sources if tag and tag != "UNCLASSIFIED"})
for tag in canonical_tags:
    meta = curve_meta.get(tag)
    resolved_tag = resolve_curve_canonical_tag(tag, curves_df=curves_df)
    curve_rows = curves_df[curves_df["canonical_tag"] == resolved_tag] if resolved_tag and not curves_df.empty else pd.DataFrame()
    rows.append(
        {
            "canonical_tag": tag,
            "active_count": active_counts.get(tag, 0),
            "curve_rows": len(curve_rows),
            "anchor_years": ", ".join(str(val) for val in meta.anchor_years) if meta else "",
            "curve_source": resolved_tag if not curve_rows.empty else "No saved curve",
        }
    )

library_df = pd.DataFrame(rows, columns=["canonical_tag", "active_count", "curve_rows", "anchor_years", "curve_source"])

missing_df = coverage_df[~coverage_df["has_curve"]].copy() if not coverage_df.empty else pd.DataFrame()
section_heading("Coverage Gaps", "Tags in the checked sources without a saved curve. Review vehicle scope before requesting new coverage.")
if missing_df.empty:
    st.success("All tags in the checked sources have a saved curve. Vehicle year and kilometre limits still apply.")
else:
    st.dataframe(
        missing_df[
            ["canonical_tag", "observed_rows", "static_rows", "group_map_rows", "sources"]
        ],
        use_container_width=True,
        hide_index=True,
    )

section_heading("Curves Library", "Search a vehicle specification tag, then choose it to inspect the saved values.")
st.caption(
    "Active feed rows count exact tag matches in the active feed; zero means no matching rows in that feed. "
    "Aliases can share a saved curve. Grid rows are saved year/kilometre price points, not vehicles or sale evidence."
)
search = st.text_input("Search vehicle tag", value="")
filtered_df = library_df.copy()
if search:
    filtered_df = filtered_df[filtered_df["canonical_tag"].str.contains(search, case=False, na=False, regex=False)]

if filtered_df.empty:
    st.info("No tags match the current search. Clear or change the search to see the library.")
    st.stop()

st.dataframe(
    filtered_df,
    hide_index=True,
    use_container_width=True,
    column_config={
        "canonical_tag": "Vehicle tag",
        "active_count": "Active feed rows",
        "curve_rows": "Saved grid rows",
        "anchor_years": "Anchor years",
        "curve_source": "Saved curve tag",
    },
)
options = filtered_df["canonical_tag"].tolist()
previous_tag = st.session_state.get("ops_selected_tag")
selected_tag = st.selectbox(
    "Vehicle tag to inspect", options,
    index=options.index(previous_tag) if previous_tag in options else 0,
)
st.session_state["ops_selected_tag"] = selected_tag
row = filtered_df[filtered_df["canonical_tag"] == selected_tag].iloc[0]
section_heading("Curve Detail", "Saved resale price points for the selected specification.")
st.text(f"Vehicle tag: {selected_tag}")
st.text(f"Saved curve tag: {row['curve_source']}")
st.caption("Per-curve update date: Not recorded. This library cannot establish when its pricing evidence was last reviewed.")
count_col, grid_col = st.columns(2)
count_col.metric("Active feed rows", int(row["active_count"]))
grid_col.metric("Saved grid rows", int(row["curve_rows"]))
st.text(f"Anchor years: {row['anchor_years'] or 'None saved'}")
resolved_tag = resolve_curve_canonical_tag(selected_tag, curves_df=curves_df)
selected_rows = curves_df[curves_df["canonical_tag"] == resolved_tag] if not curves_df.empty else pd.DataFrame()
if selected_rows.empty:
    st.warning("No saved curve for this tag. Confirm the vehicle is in buying scope before requesting coverage from Listing Detail.")
else:
    st.dataframe(
        selected_rows[["anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]]
        .sort_values(["anchor_year", "km_bucket"]),
        hide_index=True, use_container_width=True,
        column_config={
            "anchor_year": "Anchor year", "km_bucket": "Kilometre bucket",
            "price_low": st.column_config.NumberColumn("Low resale ($)", format="$%d"),
            "price_mid": st.column_config.NumberColumn("Mid resale ($)", format="$%d"),
            "price_high": st.column_config.NumberColumn("High resale ($)", format="$%d"),
        },
    )

if is_vps_runtime():
    st.info(
        "Curve editing is available in the development workspace. To change a curve, give the operator the "
        "saved curve tag shown above for review in Curve Builder V2 and release to this site. "
        "For missing coverage on an in-scope vehicle, use Add to needs-curve queue in Listing Detail."
    )
else:
    if st.button("Open Curve Builder V2", key="curves_open_builder_v2"):
        st.session_state["curve_builder_v2_tag"] = resolved_tag
        st.switch_page("pages/15_CURVE_BUILDER_V2.py")
