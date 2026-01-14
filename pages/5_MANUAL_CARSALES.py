from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from shared.curves import CURVE_COLUMNS, load_curves, save_curves
from shared.grouping import GROUP_IDS
from shared.spec import (
    build_pipe_mapping,
    get_spec_error,
    get_group_spec,
    is_series_allowed,
    load_spec,
    normalize_mapping_key,
)
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="Curve Builder", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "CURVE BUILDER",
    "Maintain the anchor curves used for restricted-market pricing. Add or edit anchor points for each group.",
)


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _fill_medians(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    for index, row in working.iterrows():
        median = _coerce_int(row.get("price_median"))
        if median is not None:
            continue
        low = _coerce_int(row.get("price_low"))
        high = _coerce_int(row.get("price_high"))
        if low is not None and high is not None:
            working.at[index, "price_median"] = int(round((low + high) / 2.0))
    return working


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    for column in CURVE_COLUMNS:
        if column not in working.columns:
            working[column] = None
    return working[list(CURVE_COLUMNS)]


def _norm_key(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


RAW_GROUP_KEY_MAP = {
    ("hilux", "dualcab_ute_sr5"): "toyota_hilux_dualcab_ute_diesel_auto_sr5_4x4",
    ("golf", "hatch_petrol_auto"): "volkswagen_golf_hatch_petrol_auto_base",
    ("golf", "hatch_petrol_auto_base"): "volkswagen_golf_hatch_petrol_auto_base",
    ("commodore", "sedan_petrol_auto_v6"): "holden_commodore_sedan_petrol_auto_v6",
    ("commodore", "wagon_petrol_auto_v6"): "holden_commodore_wagon_petrol_auto_v6",
    ("cruze", "hatch_petrol_auto"): "holden_cruze_hatch_petrol_auto_4cyl",
    ("cruze", "hatch_petrol_auto_18"): "holden_cruze_hatch_petrol_auto_4cyl",
    ("territory", "suv_diesel_auto"): "ford_territory_suv_diesel_auto_4cyl",
    ("i30", "hatch_petrol_auto"): "hyundai_i30_hatch_petrol_auto_na_active_elite",
    ("corolla", "hatch_petrol_auto"): "toyota_corolla_hatch_petrol_auto",
    ("corolla", "sedan_petrol_auto"): "toyota_corolla_sedan_petrol_auto",
    ("3series", "sedan_petrol_auto_4cyl"): "bmw_3series_sedan_petrol_auto_4cyl_20",
    ("3series", "sedan_petrol_auto_4cyl_20"): "bmw_3series_sedan_petrol_auto_4cyl_20",
    ("captiva", "suv_diesel_auto"): "holden_captiva_suv_diesel_auto_4cyl",
    ("ranger", "dualcab_ute_diesel_auto"): "ford_ranger_dualcab_ute_diesel_auto",
    ("cx5", "suv_petrol_auto_20"): "mazda_cx5_suv_petrol_auto_20",
    ("cx5", "suv_petrol_auto_25"): "mazda_cx5_suv_petrol_auto_25",
    ("navara", "dualcab_ute_diesel_auto"): "nissan_navara_dualcab_ute_diesel_auto",
    ("mazda3", "hatch_petrol_auto"): "mazda_3_hatch_petrol_auto_20_na",
}
GROUP_KEY_MAP = {
    (_norm_key(model), _norm_key(group_key)): group_id
    for (model, group_key), group_id in RAW_GROUP_KEY_MAP.items()
}

SPEC_DATA = load_spec()
spec_error = get_spec_error(SPEC_DATA)
if spec_error == "pyyaml_missing":
    st.warning("Spec checks disabled: install `pyyaml` to enable config/spec_v1.yaml validation.")
    SPEC_DATA = {}
SPEC_PIPE_MAPPING = build_pipe_mapping(SPEC_DATA)

curves_df = _ensure_columns(load_curves())

st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Curve data</div>
            <div class="section-subtitle">
                Curves are keyed by <strong>group_id</strong> and <strong>anchor_year</strong>. Each anchor year can
                have multiple km points.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

edited_df = st.data_editor(
    curves_df,
    num_rows="dynamic",
    use_container_width=True,
)

col_save, col_refresh = st.columns([1, 1])
with col_save:
    if st.button("Save curves", type="primary"):
        cleaned = _fill_medians(_ensure_columns(edited_df))
        cleaned["created_at"] = cleaned["created_at"].fillna(
            datetime.utcnow().isoformat(timespec="seconds")
        )
        save_curves(cleaned)
        st.success("Curves saved.")

with col_refresh:
    if st.button("Reload"):
        rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
        if rerun:
            rerun()


st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Add anchor point</div>
            <div class="section-subtitle">
                Add a single anchor row quickly. Median is auto-calculated if low/high are provided.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

with st.form("add_curve_form", clear_on_submit=True):
    group_id = st.selectbox("Group ID", GROUP_IDS)
    series = st.text_input("Series (optional)", value="")
    anchor_year = st.number_input("Anchor year", min_value=1990, max_value=2100, value=2020, step=1)
    km_anchor = st.number_input("KM anchor", min_value=0, max_value=400000, value=100000, step=5000)
    price_low = st.number_input("Price low", min_value=0, max_value=200000, value=0, step=500)
    price_high = st.number_input("Price high", min_value=0, max_value=200000, value=0, step=500)
    price_median = st.number_input("Price median (optional)", min_value=0, max_value=200000, value=0, step=500)
    source = st.text_input("Source", value="carsales_sell_tool")
    submitted = st.form_submit_button("Add anchor")

if submitted:
    median_value = price_median or None
    if median_value is None or median_value == 0:
        if price_low > 0 and price_high > 0:
            median_value = int(round((price_low + price_high) / 2.0))
    new_row = {
        "group_id": group_id,
        "series": series.strip() or None,
        "anchor_year": int(anchor_year),
        "km_anchor": int(km_anchor),
        "price_low": int(price_low) if price_low > 0 else None,
        "price_high": int(price_high) if price_high > 0 else None,
        "price_median": int(median_value) if median_value else None,
        "source": source or "carsales_sell_tool",
        "created_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    updated = pd.concat([curves_df, pd.DataFrame([new_row])], ignore_index=True)
    updated = _fill_medians(_ensure_columns(updated))
    save_curves(updated)
    st.success("Anchor added.")


st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Paste pipe rows</div>
            <div class="section-subtitle">
                Format: <code>model | group_key | series | year | km | price</code>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

pipe_rows = st.text_area("Pipe rows", height=160, placeholder="i30 | hatch_petrol_auto | PD.V4 | 2022 | 50000 | 22900")
if st.button("Import pipe rows"):
    rows = []
    errors = []
    for line_no, line in enumerate(pipe_rows.splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) != 6:
            errors.append(f"Line {line_no}: expected 6 fields, got {len(parts)}.")
            continue
        model_key, group_key, series_key, year_text, km_text, price_text = parts
        if not model_key or not group_key:
            errors.append(f"Line {line_no}: model/group_key missing.")
            continue
        model_norm = _norm_key(model_key)
        group_norm = _norm_key(group_key)
        series_norm = series_key.strip() or None
        try:
            year_val = int(float(year_text))
            km_val = int(float(km_text))
            price_val = int(float(price_text))
        except ValueError:
            errors.append(f"Line {line_no}: year/km/price must be numeric.")
            continue
        resolved_group = None
        spec_group = None
        if SPEC_PIPE_MAPPING:
            mapping_key = normalize_mapping_key(f"{model_key}|{group_key}")
            resolved_group = SPEC_PIPE_MAPPING.get(mapping_key)
            if resolved_group:
                spec_group = get_group_spec(SPEC_DATA, resolved_group)
        if not resolved_group and group_key in GROUP_IDS:
            resolved_group = group_key
        if not resolved_group:
            resolved_group = GROUP_KEY_MAP.get((model_norm, group_norm))
        if not spec_group and SPEC_DATA:
            spec_group = get_group_spec(SPEC_DATA, resolved_group) if resolved_group else None
        if not resolved_group:
            errors.append(f"Line {line_no}: unknown group mapping for {model_key} | {group_key}.")
            continue
        if spec_group and spec_group.get("series_allowed"):
            if not series_norm:
                errors.append(f"Line {line_no}: series required for {resolved_group}.")
                continue
            if not is_series_allowed(spec_group, series_norm):
                errors.append(
                    f"Line {line_no}: series {series_norm} not allowed for {resolved_group}."
                )
                continue
        rows.append(
            {
                "group_id": resolved_group,
                "series": series_norm,
                "anchor_year": year_val,
                "km_anchor": km_val,
                "price_low": None,
                "price_high": None,
                "price_median": price_val,
                "source": "curve_pipe_import",
                "created_at": datetime.utcnow().isoformat(timespec="seconds"),
            }
        )
    if rows:
        merged = pd.concat([curves_df, pd.DataFrame(rows)], ignore_index=True)
        merged = _fill_medians(_ensure_columns(merged))
        save_curves(merged)
        st.success(f"Imported {len(rows)} curve row(s).")
    if errors:
        st.warning("Import issues:\n" + "\n".join(errors))
