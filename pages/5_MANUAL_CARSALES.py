from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from shared.curves import CURVE_COLUMNS, load_curves, save_curves
from shared.canonical_tagging import load_allowed_variants
from shared.spec import get_spec_error, load_spec
from shared.pipe_keys import format_pipe_key, parse_pipe_key
from shared.styling import clean_html, display_banner, inject_global_styles, page_intro


st.set_page_config(page_title="Curve Builder", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "CURVE BUILDER",
    "Maintain the anchor curves used for restricted-market pricing. Add or edit anchor points for each group.",
    show_logo=False,
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


def _toyota_group_key_allowed(model_key: str, group_key: str, year_val: int | None) -> bool:
    if model_key not in {"corolla", "camry", "hilux", "rav4"}:
        return True
    if year_val is None:
        return False
    group_text = group_key.replace("-", "_").lower()
    body = ""
    fuel = ""
    transmission = ""
    if "hatch" in group_text:
        body = "hatch"
    if "sedan" in group_text:
        body = "sedan"
    if "dualcab" in group_text or "dual cab" in group_text or "ute" in group_text:
        body = "dualcab_ute"
    if "suv" in group_text or "wagon" in group_text:
        body = "suv"
    if "petrol" in group_text:
        fuel = "petrol"
    if "diesel" in group_text:
        fuel = "diesel"
    if "hybrid" in group_text:
        fuel = "hybrid"
    if "auto" in group_text:
        transmission = "auto"
    if "manual" in group_text:
        transmission = "manual"
    candidates = [
        variant
        for variant in load_allowed_variants()
        if variant.model == model_key and variant.year_min <= year_val <= variant.year_max
    ]
    if body:
        candidates = [variant for variant in candidates if variant.body == body]
    if fuel:
        candidates = [variant for variant in candidates if variant.fuel == fuel]
    if transmission:
        candidates = [variant for variant in candidates if variant.transmission == transmission]
    return bool(candidates)


SPEC_DATA = load_spec()
spec_error = get_spec_error(SPEC_DATA)
if spec_error == "pyyaml_missing":
    st.warning("Spec checks disabled: install `pyyaml` to enable config/spec_v1.yaml validation.")
    SPEC_DATA = {}

curves_df = _ensure_columns(load_curves())

st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Curve data</div>
            <div class="section-subtitle">
                Curves are keyed by <strong>model | group_key | series | anchor_year</strong>. Each anchor year can
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
    column_config={
        "price_per_km_bucket": st.column_config.NumberColumn(
            "price_per_km_bucket",
            disabled=True,
        ),
    },
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
    group_id = st.text_input(
        "Group key (model | group_key | series | anchor_year)",
        value="",
        placeholder="camry | sedan_petrol_auto | ASV70R | 2020",
    )
    km_anchor = st.number_input("KM anchor", min_value=0, max_value=400000, value=100000, step=5000)
    price_low = st.number_input("Price low", min_value=0, max_value=200000, value=0, step=500)
    price_high = st.number_input("Price high", min_value=0, max_value=200000, value=0, step=500)
    price_median = st.number_input("Price median (optional)", min_value=0, max_value=200000, value=0, step=500)
    source = st.text_input("Source", value="carsales_sell_tool")
    submitted = st.form_submit_button("Add anchor")

if submitted:
    parsed = parse_pipe_key(group_id)
    if not parsed:
        st.error("Group key must be in the format: model | group_key | series | anchor_year.")
        st.stop()
    _, _, series_value, anchor_year_value = parsed
    if anchor_year_value is None:
        st.error("Group key anchor_year must be a valid year.")
        st.stop()
    median_value = price_median or None
    if median_value is None or median_value == 0:
        if price_low > 0 and price_high > 0:
            median_value = int(round((price_low + price_high) / 2.0))
    new_row = {
        "group_id": group_id,
        "series": series_value or None,
        "anchor_year": int(anchor_year_value),
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
        group_norm = group_key.strip().lower().replace("-", "_")
        series_norm = series_key.strip() or None
        try:
            year_val = int(float(year_text))
            km_val = int(float(km_text))
            price_val = int(float(price_text))
        except ValueError:
            errors.append(f"Line {line_no}: year/km/price must be numeric.")
            continue
        if not series_norm:
            errors.append(f"Line {line_no}: series missing.")
            continue
        if not _toyota_group_key_allowed(model_norm, group_norm, year_val):
            errors.append(
                f"Line {line_no}: group_key not allowed for Toyota {model_key} {year_val}."
            )
            continue
        resolved_group = format_pipe_key(model_norm, group_norm, series_norm, year_val)
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
