import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from shared.data_loader import dataset_path
from shared.curves import (
    list_curve_tags,
    load_curve_aliases,
    load_curves,
    resolve_curve_canonical_tag,
    save_curves,
)
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


CURVES_PATH = dataset_path("curves.csv")
REQUIRED_KM = [30000, 60000, 100000, 150000, 200000]


st.set_page_config(page_title="Curve Builder", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "CURVE BUILDER",
    "Canonical curves only. Edit rows for canonical_tag + anchor_year + km_bucket and write governed updates to restricted/curves.csv.",
    show_logo=False,
)

curves = load_curves()
curve_aliases = load_curve_aliases()

canonical_tags = sorted(
    {
        tag
        for tag in list_curve_tags(curves, include_aliases=True)
        if tag and tag != "UNCLASSIFIED"
    }
)

preferred_tag = st.session_state.get("curve_builder_tag")
preferred_tag = str(preferred_tag or "").strip()
default_index = canonical_tags.index(preferred_tag) if preferred_tag in canonical_tags else 0

left, right = st.columns([2, 2])
with left:
    selected_tag = st.selectbox(
        "Select canonical_tag",
        options=canonical_tags if canonical_tags else [],
        index=default_index if canonical_tags else 0,
    )
with right:
    new_tag = st.text_input("Or enter a new tag", value="")

if new_tag.strip():
    selected_tag = new_tag.strip()

if not selected_tag:
    st.info("Add a canonical_tag to start building curves.")
    st.stop()

resolved_tag = resolve_curve_canonical_tag(selected_tag, curve_aliases)
is_alias = bool(selected_tag and resolved_tag and selected_tag != resolved_tag)

if is_alias:
    st.info(f"`{selected_tag}` resolves to base curve `{resolved_tag}`. Saving edits will update the shared base curve.")

tag_rows = curves[curves["canonical_tag"] == resolved_tag].copy()
if tag_rows.empty:
    tag_rows = pd.DataFrame(
        columns=["canonical_tag", "anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]
    )

section_heading("Edit Curve Rows", "Work on one canonical tag at a time.")
editor_df = tag_rows[
    ["canonical_tag", "anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]
].copy()
if editor_df.empty:
    editor_df = pd.DataFrame(
        [
            {
                "canonical_tag": resolved_tag or selected_tag,
                "anchor_year": 2020,
                "km_bucket": 30000,
                "price_low": None,
                "price_mid": None,
                "price_high": None,
            }
        ]
    )

edited = st.data_editor(
    editor_df,
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "canonical_tag": st.column_config.TextColumn("canonical_tag", required=True),
        "anchor_year": st.column_config.NumberColumn("anchor_year", step=1, required=True),
        "km_bucket": st.column_config.NumberColumn("km_bucket", step=1000, required=True),
        "price_low": st.column_config.NumberColumn("price_low", step=100),
        "price_mid": st.column_config.NumberColumn("price_mid", step=100),
        "price_high": st.column_config.NumberColumn("price_high", step=100),
    },
)

if st.button("Save curves.csv", type="primary"):
    key_cols = ["canonical_tag", "anchor_year", "km_bucket"]
    incoming = edited.copy()
    incoming["canonical_tag"] = incoming["canonical_tag"].fillna("").astype(str).str.strip()
    incoming["canonical_tag"] = incoming["canonical_tag"].replace("", resolved_tag or selected_tag)
    incoming["canonical_tag"] = incoming["canonical_tag"].apply(
        lambda value: resolve_curve_canonical_tag(value, curve_aliases)
    )
    incoming["_key"] = incoming[key_cols].astype(str).agg("|".join, axis=1)
    base = curves.copy()
    if not base.empty:
        base["_key"] = base[key_cols].astype(str).agg("|".join, axis=1)
        base = base[~base["_key"].isin(set(incoming["_key"]))].copy()
        base = base.drop(columns=["_key"])
    incoming = incoming.drop(columns=["_key"])
    merged = pd.concat([base, incoming], ignore_index=True)
    save_curves(merged)
    st.success(f"Saved {len(incoming)} rows to {CURVES_PATH}")
    curves = load_curves()
    curve_aliases = load_curve_aliases()
    tag_rows = curves[curves["canonical_tag"] == resolved_tag].copy()

section_heading("Completeness", "Check required km anchors for each year.")
summary_rows = []
if not tag_rows.empty:
    for year in sorted(tag_rows["anchor_year"].dropna().unique().tolist()):
        year_rows = tag_rows[tag_rows["anchor_year"] == year]
        present = sorted(year_rows["km_bucket"].dropna().astype(int).unique().tolist())
        missing = [k for k in REQUIRED_KM if k not in present]
        summary_rows.append(
            {
                "anchor_year": int(year),
                "points_present": len(present),
                "points_required": len(REQUIRED_KM),
                "missing_km": ",".join(str(val) for val in missing),
                "complete": len(missing) == 0,
            }
        )

if summary_rows:
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
else:
    st.info("No rows yet for this tag.")

section_heading("Plot", "Visualize the current mid-price curve by anchor year.")
if not tag_rows.empty:
    fig = plt.figure()
    ax = plt.gca()
    for km in REQUIRED_KM:
        ax.axvline(km, linestyle="--", linewidth=1, alpha=0.3)
    for year in sorted(tag_rows["anchor_year"].dropna().unique().tolist()):
        sub = tag_rows[tag_rows["anchor_year"] == year].sort_values("km_bucket")
        ax.plot(sub["km_bucket"], sub["price_mid"], marker="o", linewidth=2, label=str(year))
        ax.scatter(sub["km_bucket"], sub["price_mid"], s=25)
    ax.set_title(selected_tag if not is_alias else f"{selected_tag} -> {resolved_tag}")
    ax.set_xlabel("KM")
    ax.set_ylabel("Price ($)")
    ax.legend()
    st.pyplot(fig)
else:
    st.info("No data to plot.")
