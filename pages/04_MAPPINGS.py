from pathlib import Path
import pandas as pd
import streamlit as st

from shared.csv_utils import read_csv_or_empty
from shared.ops_utils import load_static_df
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


st.set_page_config(page_title="Mappings - Builder", layout="wide")
inject_global_styles()
display_banner()
page_intro("MAPPING STUDIO", "Edit normalization + tag rules without touching code.", show_logo=False)

NORMALISATION_PATH = Path("config/toyota_normalisation_rules.csv")
ALLOWED_PATH = Path("config/toyota_allowed_variants.csv")

static_df = load_static_df()


def _load_csv(path: Path) -> pd.DataFrame:
    return read_csv_or_empty(path)


def _save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _affected_count(row: pd.Series) -> int:
    field = _normalize_text(row.get("field"))
    raw = _normalize_text(row.get("raw"))
    if not field or not raw or static_df.empty:
        return 0
    if field == "model" and "model" in static_df.columns:
        return int((static_df["model"].astype(str).str.lower() == raw).sum())
    if field == "body" and "body_type" in static_df.columns:
        return int((static_df["body_type"].astype(str).str.lower() == raw).sum())
    if field == "transmission" and "transmission" in static_df.columns:
        return int((static_df["transmission"].astype(str).str.lower() == raw).sum())
    if field == "fuel" and "fuel_type" in static_df.columns:
        return int((static_df["fuel_type"].astype(str).str.lower() == raw).sum())
    if field == "badge" and "variant" in static_df.columns:
        return int(static_df["variant"].astype(str).str.lower().str.contains(raw, na=False).sum())
    return 0


section_heading("Normalization Rules", "Map raw tokens to clean values.")
normalisation_df = _load_csv(NORMALISATION_PATH)
if normalisation_df.empty:
    st.warning("No normalization rules found. Add your first mapping row below.")
else:
    normalisation_df = normalisation_df.copy()

if not normalisation_df.empty:
    normalisation_df["affected_count"] = normalisation_df.apply(_affected_count, axis=1)

edited_norm = st.data_editor(
    normalisation_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    disabled=["affected_count"] if not normalisation_df.empty else None,
)

if st.button("Save normalization rules", key="save_norm_rules"):
    working = edited_norm.copy()
    for col in ("field", "raw", "normalised"):
        if col in working.columns:
            working[col] = working[col].apply(_normalize_text)
    _save_csv(working, NORMALISATION_PATH)
    st.success(f"Saved {len(working):,} normalization rules.")

section_heading("Allowed Variants", "Canonical tag definitions and badge aliases.")
allowed_df = _load_csv(ALLOWED_PATH)

if allowed_df.empty:
    st.warning("No allowed variants found. Add your first canonical tag row below.")
else:
    allowed_df = allowed_df.copy()
    if "canonical_tag" in allowed_df.columns and "canonical_tag" in static_df.columns:
        tag_counts = static_df["canonical_tag"].astype(str).str.strip().value_counts().to_dict()
        allowed_df["listings_matching"] = allowed_df["canonical_tag"].astype(str).str.strip().map(tag_counts).fillna(0).astype(int)

edited_allowed = st.data_editor(
    allowed_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    disabled=["listings_matching"] if "listings_matching" in allowed_df.columns else None,
)

if st.button("Save allowed variants", key="save_allowed_variants"):
    working = edited_allowed.copy()
    for col in working.columns:
        if col in {"listings_matching"}:
            continue
        working[col] = working[col].apply(_normalize_text)
    if "listings_matching" in working.columns:
        working = working.drop(columns=["listings_matching"])
    _save_csv(working, ALLOWED_PATH)
    st.success(f"Saved {len(working):,} allowed variant rows.")
