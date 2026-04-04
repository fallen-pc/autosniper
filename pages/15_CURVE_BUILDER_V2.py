from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib import colors as mcolors
import pandas as pd
import streamlit as st

from scripts.curve_validator import build_curve_warnings
from scripts.generate_curve_candidates import load_tagged_sold_data
from scripts.process_curve_candidates import DEFAULT_AUTOTRADER_SOURCE, load_autotrader_market
from shared.curve_builder_v2 import prepare_active_market_for_proposal, propose_curve_from_evidence
from shared.curve_groups_v2 import (
    get_anchor_override_years,
    get_supported_curve_row,
    list_supported_base_curve_tags,
    load_curve_anchor_overrides_v2,
    load_curve_groups_v2,
    load_supported_curve_universe_v1,
    tags_for_base_curve,
)
from shared.curves import CURVE_COLUMNS, load_curves, save_curves
from shared.data_loader import dataset_path
from shared.manual_curve_evidence import load_manual_curve_evidence, prepare_manual_curve_evidence
from shared.styling import display_banner, inject_global_styles, page_intro, section_heading


CURVES_PATH = dataset_path("curves.csv")
SOLD_PATH = dataset_path("sold_cars.csv")
REQUIRED_KM = [30000, 60000, 100000, 150000, 200000]


st.set_page_config(page_title="Curve Builder V2", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "CURVE BUILDER V2",
    "Edit broader base curves while keeping detailed match tags separate. This page writes only V2 base curve rows.",
    show_logo=False,
)


@st.cache_data(show_spinner=False)
def _load_supported_universe() -> pd.DataFrame:
    return load_supported_curve_universe_v1()


@st.cache_data(show_spinner=False)
def _load_curve_groups() -> pd.DataFrame:
    return load_curve_groups_v2()


@st.cache_data(show_spinner=False)
def _load_anchor_overrides() -> pd.DataFrame:
    return load_curve_anchor_overrides_v2()


@st.cache_data(show_spinner=False)
def _load_sold_evidence() -> pd.DataFrame:
    sold_df, _stats = load_tagged_sold_data(SOLD_PATH)
    return sold_df


@st.cache_data(show_spinner=False)
def _load_active_evidence(_version: int) -> pd.DataFrame:
    return load_autotrader_market(DEFAULT_AUTOTRADER_SOURCE)


@st.cache_data(show_spinner=False)
def _load_manual_carsales_evidence(_version: int) -> pd.DataFrame:
    return prepare_manual_curve_evidence(load_manual_curve_evidence())


def _suggest_anchor_years(base_curve_tag: str, evidence_df: pd.DataFrame, overrides_df: pd.DataFrame | None = None) -> list[int]:
    override_years = get_anchor_override_years(base_curve_tag, overrides_df)
    if override_years:
        return override_years
    if evidence_df.empty or "year_numeric" not in evidence_df.columns:
        return [2020]
    years = pd.to_numeric(evidence_df["year_numeric"], errors="coerce").dropna().astype(int)
    if years.empty:
        return [2020]
    year_min = int(years.min())
    year_max = int(years.max())
    if year_min == year_max:
        return [year_min]
    mid = int(round((year_min + year_max) / 2.0))
    return sorted({year_min, mid, year_max})


def _blank_grid(base_curve_tag: str, anchor_years: list[int]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for anchor_year in anchor_years:
        for km_bucket in REQUIRED_KM:
            rows.append(
                {
                    "canonical_tag": base_curve_tag,
                    "anchor_year": int(anchor_year),
                    "km_bucket": int(km_bucket),
                    "price_low": None,
                    "price_mid": None,
                    "price_high": None,
                }
            )
    return pd.DataFrame(rows, columns=list(CURVE_COLUMNS))


def _prepare_editor_rows(
    base_curve_tag: str,
    curves_df: pd.DataFrame,
    member_tags: list[str],
    evidence_df: pd.DataFrame,
    overrides_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, str]:
    base_rows = curves_df[curves_df["canonical_tag"].astype(str).str.strip() == base_curve_tag].copy()
    if not base_rows.empty:
        return base_rows[list(CURVE_COLUMNS)].copy(), "Loaded existing V2 base curve rows."

    override_years = get_anchor_override_years(base_curve_tag, overrides_df)
    if override_years:
        return (
            _blank_grid(base_curve_tag, override_years),
            f"Using configured V2 anchor override: {', '.join(str(value) for value in override_years)}.",
        )

    legacy_rows = curves_df[curves_df["canonical_tag"].astype(str).str.strip().isin(member_tags)].copy()
    if not legacy_rows.empty:
        legacy_rows = legacy_rows[list(CURVE_COLUMNS)].copy()
        legacy_rows["canonical_tag"] = base_curve_tag
        legacy_rows = legacy_rows.drop_duplicates(subset=["canonical_tag", "anchor_year", "km_bucket"], keep="first")
        return legacy_rows.sort_values(["anchor_year", "km_bucket"]).reset_index(drop=True), "Loaded legacy curve rows as a starting point."

    return _blank_grid(base_curve_tag, _suggest_anchor_years(base_curve_tag, evidence_df, overrides_df)), "No saved rows yet. Starting from a blank grid."


def _load_comparison_curve_rows(base_curve_tag: str, curves_df: pd.DataFrame, member_tags: list[str]) -> tuple[pd.DataFrame, str]:
    saved_rows = curves_df[curves_df["canonical_tag"].astype(str).str.strip() == base_curve_tag].copy()
    if not saved_rows.empty:
        return saved_rows[list(CURVE_COLUMNS)].copy(), "saved_v2"

    legacy_rows = curves_df[curves_df["canonical_tag"].astype(str).str.strip().isin(member_tags)].copy()
    if not legacy_rows.empty:
        legacy_rows = legacy_rows[list(CURVE_COLUMNS)].copy()
        legacy_rows["canonical_tag"] = base_curve_tag
        legacy_rows = legacy_rows.drop_duplicates(subset=["canonical_tag", "anchor_year", "km_bucket"], keep="first")
        return legacy_rows.sort_values(["anchor_year", "km_bucket"]).reset_index(drop=True), "legacy_fallback"

    return pd.DataFrame(columns=list(CURVE_COLUMNS)), "none"


def _build_completeness_frame(editor_df: pd.DataFrame) -> pd.DataFrame:
    if editor_df.empty:
        return pd.DataFrame()
    summary_rows: list[dict[str, object]] = []
    for anchor_year, subset in editor_df.groupby("anchor_year", sort=True):
        present = sorted(pd.to_numeric(subset["km_bucket"], errors="coerce").dropna().astype(int).unique().tolist())
        missing = [value for value in REQUIRED_KM if value not in present]
        summary_rows.append(
            {
                "anchor_year": int(anchor_year),
                "points_present": len(present),
                "points_required": len(REQUIRED_KM),
                "missing_km": ", ".join(str(value) for value in missing),
                "complete": len(missing) == 0,
            }
        )
    return pd.DataFrame(summary_rows)


def _extract_anchor_years(df: pd.DataFrame | object) -> list[int]:
    if not isinstance(df, pd.DataFrame) or df.empty or "anchor_year" not in df.columns:
        return []
    return sorted(pd.to_numeric(df["anchor_year"], errors="coerce").dropna().astype(int).unique().tolist())


def _build_source_tag_breakdown(sold_subset: pd.DataFrame, active_subset: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    all_tags = sorted(
        set(sold_subset.get("canonical_tag", pd.Series(dtype="object")).dropna().astype(str).tolist())
        | set(active_subset.get("canonical_tag", pd.Series(dtype="object")).dropna().astype(str).tolist())
    )
    for tag in all_tags:
        sold_count = int((sold_subset["canonical_tag"].fillna("").astype(str) == tag).sum()) if not sold_subset.empty else 0
        active_count = int((active_subset["canonical_tag"].fillna("").astype(str) == tag).sum()) if not active_subset.empty else 0
        rows.append(
            {
                "match_tag": tag,
                "sold_rows": sold_count,
                "active_rows": active_count,
                "total_rows": sold_count + active_count,
            }
        )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["total_rows", "sold_rows", "active_rows", "match_tag"], ascending=[False, False, False, True]).reset_index(drop=True)


def _filter_evidence_rows(
    df: pd.DataFrame,
    *,
    selected_tags: list[str],
    year_min: int,
    year_max: int,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    if selected_tags:
        working = working[working["canonical_tag"].fillna("").astype(str).isin(selected_tags)].copy()
    if "year_numeric" in working.columns:
        years = pd.to_numeric(working["year_numeric"], errors="coerce")
        working = working[years.between(year_min, year_max, inclusive="both").fillna(False)].copy()
    return working


def _prepare_sold_listing_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    for column in ["year_numeric", "odometer_numeric", "price_numeric"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    display_cols = [
        column
        for column in [
            "canonical_tag",
            "variant",
            "year_numeric",
            "odometer_numeric",
            "price_numeric",
            "location",
            "general_condition",
            "date_sold",
            "url",
        ]
        if column in working.columns
    ]
    renamed = working[display_cols].rename(
        columns={
            "canonical_tag": "match_tag",
            "year_numeric": "year",
            "odometer_numeric": "km",
            "price_numeric": "price",
        }
    )
    return renamed.sort_values(["year", "km", "price"], ascending=[False, True, True], na_position="last").reset_index(drop=True)


def _prepare_active_listing_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    for column in ["year_numeric", "odometer_numeric", "price_numeric"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    display_cols = [
        column
        for column in [
            "canonical_tag",
            "variant",
            "year_numeric",
            "odometer_numeric",
            "price_numeric",
            "location",
            "status",
            "first_seen",
            "last_seen",
            "url",
        ]
        if column in working.columns
    ]
    renamed = working[display_cols].rename(
        columns={
            "canonical_tag": "match_tag",
            "year_numeric": "year",
            "odometer_numeric": "km",
            "price_numeric": "price",
        }
    )
    return renamed.sort_values(["year", "km", "price"], ascending=[False, True, True], na_position="last").reset_index(drop=True)


def _prepare_manual_carsales_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    for column in ["year_numeric", "odometer_numeric", "price_numeric"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    display_cols = [
        column
        for column in [
            "year_numeric",
            "variant",
            "price_numeric",
            "odometer_numeric",
            "engine",
            "location",
            "source",
            "notes",
        ]
        if column in working.columns
    ]
    renamed = working[display_cols].rename(
        columns={
            "year_numeric": "year",
            "odometer_numeric": "km",
            "price_numeric": "price",
        }
    )
    return renamed.sort_values(["year", "km", "price"], ascending=[False, True, True], na_position="last").reset_index(drop=True)


def _build_unclassified_near_miss_rows(
    market_df: pd.DataFrame,
    *,
    make_value: str,
    model_value: str,
    year_min: int,
    year_max: int,
) -> pd.DataFrame:
    if market_df.empty:
        return pd.DataFrame()
    working = market_df.copy()
    canonical_series = working.get("canonical_tag", pd.Series("", index=working.index, dtype="object"))
    working = working[canonical_series.fillna("").astype(str).str.strip() == "UNCLASSIFIED"].copy()
    if working.empty:
        return working
    make_norm = str(make_value or "").strip().lower()
    model_norm = str(model_value or "").strip().lower()
    if make_norm:
        working = working[working.get("make", pd.Series("", index=working.index)).fillna("").astype(str).str.strip().str.lower() == make_norm].copy()
    if model_norm:
        working = working[working.get("model", pd.Series("", index=working.index)).fillna("").astype(str).str.strip().str.lower() == model_norm].copy()
    if working.empty:
        return working
    if "year_numeric" in working.columns:
        years = pd.to_numeric(working["year_numeric"], errors="coerce")
        working = working[years.between(year_min, year_max, inclusive="both").fillna(False)].copy()
    return working


def _prepare_near_miss_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    for column in ["year_numeric", "odometer_numeric", "price_numeric"]:
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    display_cols = [
        column
        for column in [
            "year_numeric",
            "variant",
            "body_type",
            "transmission",
            "fuel_type",
            "odometer_numeric",
            "price_numeric",
            "canonical_reason",
            "location",
            "url",
        ]
        if column in working.columns
    ]
    renamed = working[display_cols].rename(
        columns={
            "year_numeric": "year",
            "odometer_numeric": "km",
            "price_numeric": "price",
            "canonical_reason": "reason",
        }
    )
    return renamed.sort_values(["year", "price", "km"], ascending=[False, False, True], na_position="last").reset_index(drop=True)


def _assign_anchor_year_bucket(df: pd.DataFrame, anchor_years: list[int]) -> pd.DataFrame:
    if df.empty or not anchor_years or "year_numeric" not in df.columns:
        return pd.DataFrame() if df.empty else df.copy()
    working = df.copy()
    years = pd.to_numeric(working["year_numeric"], errors="coerce")
    working = working[years.notna()].copy()
    if working.empty:
        return working
    year_values = years.loc[working.index].astype(int)
    anchor_list = sorted({int(value) for value in anchor_years})
    working["plot_anchor_year"] = year_values.apply(
        lambda year_value: min(anchor_list, key=lambda anchor: abs(anchor - int(year_value)))
    )
    return working


def _lighten_color(color_value: object, amount: float = 0.55) -> tuple[float, float, float]:
    r, g, b = mcolors.to_rgb(color_value)
    return (
        r + ((1.0 - r) * amount),
        g + ((1.0 - g) * amount),
        b + ((1.0 - b) * amount),
    )


def _normalize_evidence_value(field_name: str, value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if field_name == "fuel_type":
        if text in {"petrol", "unleaded", "ulp", "gasoline", "premium"}:
            return "petrol"
    if field_name == "body_type":
        if text in {"hatch", "hatchback"}:
            return "hatch"
        if text in {"sedan", "saloon"}:
            return "sedan"
    if field_name == "transmission":
        if text in {"automatic", "auto", "cvt", "dct"}:
            return "auto"
        if text == "manual":
            return "manual"
    return text


def _build_evidence_health(
    sold_subset: pd.DataFrame,
    active_subset: pd.DataFrame,
    *,
    selected_tags: list[str],
) -> tuple[dict[str, object], list[str]]:
    combined = pd.concat([sold_subset, active_subset], ignore_index=True, sort=False) if not sold_subset.empty or not active_subset.empty else pd.DataFrame()
    if combined.empty:
        return (
            {
                "total_rows": 0,
                "sold_rows": 0,
                "active_rows": 0,
                "source_tags": len(selected_tags),
                "year_span": 0,
                "odometer_std": 0.0,
                "price_spread_pct": 0.0,
                "dominant_tag_share_pct": 0.0,
            },
            ["No evidence rows match the current filters."],
        )

    years = pd.to_numeric(combined.get("year_numeric"), errors="coerce").dropna()
    odometers = pd.to_numeric(combined.get("odometer_numeric"), errors="coerce").dropna()
    prices = pd.to_numeric(combined.get("price_numeric"), errors="coerce").dropna()
    tag_counts = combined.get("canonical_tag", pd.Series(dtype="object")).fillna("").astype(str).value_counts()

    year_span = int(years.max() - years.min()) if not years.empty else 0
    odometer_std = float(odometers.std(ddof=0) or 0.0) if not odometers.empty else 0.0
    if not prices.empty and float(prices.median() or 0.0) > 0:
        price_spread_pct = float((prices.max() - prices.min()) / prices.median())
    else:
        price_spread_pct = 0.0
    dominant_tag_share_pct = float((tag_counts.iloc[0] / len(combined)) * 100.0) if not tag_counts.empty else 0.0

    warnings: list[str] = []
    if len(combined) < 20:
        warnings.append("Low total evidence after filters. This base curve may still be too thin.")
    if year_span > 8:
        warnings.append(f"Wide year span ({year_span} years). Check that this base curve is not mixing generations.")
    if odometer_std < 20000:
        warnings.append("Odometer spread is narrow. The curve may be unstable across km buckets.")
    if len(tag_counts) > 1 and dominant_tag_share_pct >= 80.0:
        warnings.append(f"One source tag dominates {dominant_tag_share_pct:.0f}% of the evidence.")

    for field_name, label in [("fuel_type", "fuel"), ("body_type", "body"), ("transmission", "transmission")]:
        if field_name not in combined.columns:
            continue
        values = sorted(
            {
                _normalize_evidence_value(field_name, value)
                for value in combined[field_name].dropna().tolist()
                if _normalize_evidence_value(field_name, value)
            }
        )
        if len(values) > 1:
            warnings.append(f"Mixed {label} values detected: {', '.join(values[:5])}.")

    health = {
        "total_rows": int(len(combined)),
        "sold_rows": int(len(sold_subset)),
        "active_rows": int(len(active_subset)),
        "source_tags": int(len(selected_tags)),
        "year_span": year_span,
        "odometer_std": odometer_std,
        "price_spread_pct": price_spread_pct,
        "dominant_tag_share_pct": dominant_tag_share_pct,
    }
    return health, warnings


def _build_year_breakdown(sold_subset: pd.DataFrame, active_subset: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for label, df in [("sold", sold_subset), ("active", active_subset)]:
        if df.empty or "year_numeric" not in df.columns:
            continue
        years = pd.to_numeric(df["year_numeric"], errors="coerce").dropna().astype(int)
        if years.empty:
            continue
        counts = years.value_counts().sort_index()
        for year_value, count in counts.items():
            rows.append({"year": int(year_value), "source": label, "rows": int(count)})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["year", "source"]).reset_index(drop=True)


def _build_curve_comparison(current_df: pd.DataFrame, edited_df: pd.DataFrame, *, base_curve_tag: str) -> tuple[pd.DataFrame, dict[str, object]]:
    current = current_df.copy() if current_df is not None else pd.DataFrame(columns=list(CURVE_COLUMNS))
    edited = edited_df.copy() if edited_df is not None else pd.DataFrame(columns=list(CURVE_COLUMNS))
    for frame in (current, edited):
        if frame.empty:
            continue
        frame["canonical_tag"] = base_curve_tag
        for column in ["anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    current = current[list(CURVE_COLUMNS)] if not current.empty else pd.DataFrame(columns=list(CURVE_COLUMNS))
    edited = edited[list(CURVE_COLUMNS)] if not edited.empty else pd.DataFrame(columns=list(CURVE_COLUMNS))

    merged = current.merge(
        edited,
        on=["canonical_tag", "anchor_year", "km_bucket"],
        how="outer",
        suffixes=("_current", "_edited"),
    )
    for price_column in ["price_low", "price_mid", "price_high"]:
        current_col = f"{price_column}_current"
        edited_col = f"{price_column}_edited"
        merged[f"{price_column}_delta"] = pd.to_numeric(merged[edited_col], errors="coerce") - pd.to_numeric(merged[current_col], errors="coerce")
    max_mid_delta = pd.to_numeric(merged.get("price_mid_delta"), errors="coerce").abs().max() if not merged.empty else 0.0
    if pd.isna(max_mid_delta):
        max_mid_delta = 0.0
    summary = {
        "current_rows": int(len(current)),
        "edited_rows": int(len(edited)),
        "changed_cells": int(
            sum(
                merged[f"{column}_delta"].fillna(0).ne(0).sum()
                for column in ["price_low", "price_mid", "price_high"]
            )
        ),
        "max_mid_delta": float(max_mid_delta),
    }
    return merged.sort_values(["anchor_year", "km_bucket"], ascending=[True, True], na_position="last"), summary


def _build_saved_status_frame(supported_df: pd.DataFrame, curves_df: pd.DataFrame) -> pd.DataFrame:
    if supported_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for _, row in supported_df.iterrows():
        base_curve_tag = str(row.get("base_curve_tag", "") or "").strip()
        if not base_curve_tag:
            continue
        saved_rows = curves_df[curves_df["canonical_tag"].astype(str).str.strip() == base_curve_tag].copy() if not curves_df.empty else pd.DataFrame()
        anchor_years = (
            sorted(pd.to_numeric(saved_rows["anchor_year"], errors="coerce").dropna().astype(int).unique().tolist())
            if not saved_rows.empty and "anchor_year" in saved_rows.columns
            else []
        )
        rows.append(
            {
                "base_curve_tag": base_curve_tag,
                "status": "saved" if not saved_rows.empty else "not_saved",
                "saved_rows": int(len(saved_rows)),
                "anchor_years": ", ".join(str(value) for value in anchor_years),
                "make": str(row.get("make", "") or ""),
                "model": str(row.get("model", "") or ""),
                "series": str(row.get("series", "") or ""),
                "scope_status": str(row.get("status", "") or ""),
                "priority": row.get("priority"),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["priority"] = pd.to_numeric(frame["priority"], errors="coerce")
    return frame.sort_values(["status", "priority", "base_curve_tag"], ascending=[True, True, True], na_position="last").reset_index(drop=True)


supported_df = _load_supported_universe()
groups_df = _load_curve_groups()
anchor_overrides_df = _load_anchor_overrides()
sold_df = _load_sold_evidence()
active_source_version = DEFAULT_AUTOTRADER_SOURCE.stat().st_mtime_ns if DEFAULT_AUTOTRADER_SOURCE.exists() else 0
active_df = _load_active_evidence(active_source_version)
manual_carsales_path = dataset_path("quality/manual_curve_evidence.csv")
manual_carsales_version = manual_carsales_path.stat().st_mtime_ns if manual_carsales_path.exists() else 0
manual_carsales_df = _load_manual_carsales_evidence(manual_carsales_version)
curves_df = load_curves()
saved_status_df = _build_saved_status_frame(supported_df, curves_df)

status_filter = st.selectbox("Scope", options=["live_now", "hold", "all"], index=0)
if status_filter == "all":
    selectable_tags = list_supported_base_curve_tags(supported_df=supported_df)
else:
    selectable_tags = list_supported_base_curve_tags(statuses=[status_filter], supported_df=supported_df)

if not selectable_tags:
    st.error("No supported V2 base curves are configured yet.")
    st.stop()

default_tag = st.session_state.get("curve_builder_v2_tag")
default_index = selectable_tags.index(default_tag) if default_tag in selectable_tags else 0
selected_base_curve = st.selectbox("Select base_curve_tag", options=selectable_tags, index=default_index)
st.session_state["curve_builder_v2_tag"] = selected_base_curve

curve_info = get_supported_curve_row(selected_base_curve, supported_df=supported_df)
member_tags = tags_for_base_curve(selected_base_curve, groups_df=groups_df)

section_heading("Saved V2 Curves", "This shows which approved V2 base curves already exist in curves.csv and which ones still need to be built.")
saved_metric_cols = st.columns(3)
saved_metric_cols[0].metric(
    "Saved V2 Curves",
    f"{0 if saved_status_df.empty else int(saved_status_df['status'].eq('saved').sum()):,}",
)
saved_metric_cols[1].metric(
    "Not Saved Yet",
    f"{0 if saved_status_df.empty else int(saved_status_df['status'].eq('not_saved').sum()):,}",
)
saved_metric_cols[2].metric(
    "Live Scope Tags",
    f"{0 if saved_status_df.empty else int(saved_status_df['scope_status'].eq('live_now').sum()):,}",
)
if saved_status_df.empty:
    st.info("No V2 curve status data is available yet.")
else:
    st.dataframe(saved_status_df, use_container_width=True, hide_index=True)

sold_subset = sold_df[sold_df["canonical_tag"].fillna("").astype(str).isin(member_tags)].copy() if member_tags else pd.DataFrame()
active_subset = active_df[active_df["canonical_tag"].fillna("").astype(str).isin(member_tags)].copy() if member_tags else pd.DataFrame()
manual_carsales_subset = (
    manual_carsales_df[manual_carsales_df["base_curve_tag"].fillna("").astype(str).eq(selected_base_curve)].copy()
    if not manual_carsales_df.empty
    else pd.DataFrame()
)
evidence_frames = [df for df in [sold_subset, active_subset, manual_carsales_subset] if not df.empty]
evidence_df = pd.concat(evidence_frames, ignore_index=True, sort=False) if evidence_frames else pd.DataFrame()
source_breakdown_df = _build_source_tag_breakdown(sold_subset, active_subset)

section_heading("Base Curve Scope", "This page edits one broader pricing curve and shows which detailed tags feed into it.")
scope_left, scope_right = st.columns([2, 3])
with scope_left:
    st.write(f"Base curve: `{selected_base_curve}`")
    st.write(f"Make/model: `{curve_info.get('make', '')} {curve_info.get('model', '')}`")
    st.write(f"Status: `{curve_info.get('status', '')}`")
    st.write(f"Notes: `{curve_info.get('notes', '')}`")
with scope_right:
    st.write("Source match tags:")
    if member_tags:
        st.code("\n".join(member_tags), language="text")
    else:
        st.info("No detailed tags are mapped into this base curve yet.")

metric_cols = st.columns(4)
metric_cols[0].metric("Source Tags", f"{len(member_tags):,}")
metric_cols[1].metric("Sold Evidence Rows", f"{len(sold_subset):,}")
metric_cols[2].metric("Autotrader Market Rows", f"{len(active_subset):,}")
metric_cols[3].metric(
    "Saved Base Rows",
    f"{len(curves_df[curves_df['canonical_tag'].astype(str).str.strip() == selected_base_curve]):,}" if not curves_df.empty else "0",
)
support_metric_cols = st.columns(2)
support_metric_cols[0].metric("Manual Carsales Rows", f"{len(manual_carsales_subset):,}")
support_metric_cols[1].metric("Total Visible Evidence", f"{len(evidence_df):,}")
if not manual_carsales_subset.empty:
    st.success("This curve is currently Carsales-led. Manual Carsales rows are the primary pricing source; Autotrader is support/confidence only.")
else:
    st.caption("Autotrader market rows above only include rows already matched into this base curve. Nearby unclassified rows are shown separately and are excluded from the proposer.")

section_heading("Matched Evidence Review", "Inspect exactly which sold and Autotrader rows are feeding this base curve before you shape the pricing grid.")
filter_left, filter_mid, filter_right = st.columns([2, 1, 1])
with filter_left:
    selected_match_tags = st.multiselect(
        "Filter source match tags",
        options=member_tags,
        default=member_tags,
    )
year_values = pd.to_numeric(evidence_df.get("year_numeric"), errors="coerce").dropna().astype(int) if not evidence_df.empty and "year_numeric" in evidence_df.columns else pd.Series(dtype="int64")
year_floor = int(year_values.min()) if not year_values.empty else 2000
year_ceiling = int(year_values.max()) if not year_values.empty else 2025
with filter_mid:
    filter_year_min = st.number_input("Year from", min_value=1980, max_value=2035, value=year_floor, step=1)
with filter_right:
    filter_year_max = st.number_input("Year to", min_value=1980, max_value=2035, value=year_ceiling, step=1)

if filter_year_min > filter_year_max:
    st.error("`Year from` must be less than or equal to `Year to`.")
    st.stop()

filtered_sold_subset = _filter_evidence_rows(
    sold_subset,
    selected_tags=selected_match_tags,
    year_min=int(filter_year_min),
    year_max=int(filter_year_max),
)
filtered_active_subset = _filter_evidence_rows(
    active_subset,
    selected_tags=selected_match_tags,
    year_min=int(filter_year_min),
    year_max=int(filter_year_max),
)
if manual_carsales_subset.empty:
    filtered_manual_carsales_subset = pd.DataFrame()
else:
    manual_years = pd.to_numeric(manual_carsales_subset.get("year_numeric"), errors="coerce")
    filtered_manual_carsales_subset = manual_carsales_subset[
        manual_years.between(int(filter_year_min), int(filter_year_max), inclusive="both").fillna(False)
    ].copy()
trimmed_active_subset, trimmed_active_count = prepare_active_market_for_proposal(filtered_active_subset)
configured_anchor_years = get_anchor_override_years(selected_base_curve, anchor_overrides_df)
suggested_anchor_years = _suggest_anchor_years(
    selected_base_curve,
    filtered_manual_carsales_subset
    if not filtered_manual_carsales_subset.empty
    else filtered_active_subset
    if not filtered_active_subset.empty
    else filtered_sold_subset,
    anchor_overrides_df,
)
evidence_health, evidence_warnings = _build_evidence_health(
    filtered_sold_subset,
    filtered_active_subset,
    selected_tags=selected_match_tags,
)
year_breakdown_df = _build_year_breakdown(filtered_sold_subset, filtered_active_subset)

breakdown_left, breakdown_right = st.columns([2, 3])
with breakdown_left:
    st.caption("Evidence counts by source tag")
    if source_breakdown_df.empty:
        st.info("No grouped source-tag evidence found yet.")
    else:
        if selected_match_tags:
            shown_breakdown = source_breakdown_df[source_breakdown_df["match_tag"].isin(selected_match_tags)].copy()
        else:
            shown_breakdown = source_breakdown_df.copy()
        st.dataframe(shown_breakdown, use_container_width=True, hide_index=True)
with breakdown_right:
    breakdown_metrics = st.columns(5)
    breakdown_metrics[0].metric("Filtered Sold Rows", f"{len(filtered_sold_subset):,}")
    breakdown_metrics[1].metric("Filtered Autotrader Rows", f"{len(filtered_active_subset):,}")
    breakdown_metrics[2].metric("Filtered Carsales Rows", f"{len(filtered_manual_carsales_subset):,}")
    breakdown_metrics[3].metric(
        "Filtered Match Tags",
        f"{len(selected_match_tags):,}",
    )
    breakdown_metrics[4].metric(
        "Year Window",
        f"{int(filter_year_min)}-{int(filter_year_max)}",
    )

section_heading("Evidence Health", "Use this to decide whether the base curve is clean enough to trust before editing prices.")
health_cols = st.columns(4)
health_cols[0].metric("Total Evidence", f"{int(evidence_health['total_rows']):,}")
health_cols[1].metric("Year Span", f"{int(evidence_health['year_span'])}y")
health_cols[2].metric("Odometer Std", f"{int(round(float(evidence_health['odometer_std']))):,} km")
health_cols[3].metric("Dominant Tag Share", f"{float(evidence_health['dominant_tag_share_pct']):.0f}%")

health_cols_2 = st.columns(3)
health_cols_2[0].metric("Source Tags", f"{int(evidence_health['source_tags']):,}")
health_cols_2[1].metric("Sold Rows", f"{int(evidence_health['sold_rows']):,}")
health_cols_2[2].metric("Price Spread", f"{float(evidence_health['price_spread_pct']):.2f}x")

if evidence_warnings:
    for warning in evidence_warnings:
        st.warning(warning)
else:
    st.success("No obvious evidence-mix problems detected in the current filters.")

chart_left, chart_right = st.columns(2)
with chart_left:
    st.caption("Rows by source tag")
    if source_breakdown_df.empty:
        st.info("No source-tag breakdown available.")
    else:
        chart_df = source_breakdown_df.copy()
        if selected_match_tags:
            chart_df = chart_df[chart_df["match_tag"].isin(selected_match_tags)].copy()
        st.bar_chart(chart_df.set_index("match_tag")[["sold_rows", "active_rows"]], use_container_width=True)
with chart_right:
    st.caption("Rows by year")
    if year_breakdown_df.empty:
        st.info("No year breakdown available.")
    else:
        pivot_df = year_breakdown_df.pivot(index="year", columns="source", values="rows").fillna(0)
        st.bar_chart(pivot_df, use_container_width=True)

sold_tab, active_tab, carsales_tab = st.tabs(["Matched Sold Listings", "Matched Autotrader Listings", "Manual Carsales Listings"])
with sold_tab:
    sold_table_df = _prepare_sold_listing_table(filtered_sold_subset)
    if sold_table_df.empty:
        st.info("No sold listings match the current filters.")
    else:
        st.dataframe(sold_table_df, use_container_width=True, hide_index=True)
with active_tab:
    active_table_df = _prepare_active_listing_table(filtered_active_subset)
    if active_table_df.empty:
        st.info("No Autotrader listings match the current filters.")
    else:
        st.dataframe(active_table_df, use_container_width=True, hide_index=True)
with carsales_tab:
    carsales_table_df = _prepare_manual_carsales_table(filtered_manual_carsales_subset)
    if carsales_table_df.empty:
        st.info("No manual Carsales listings are stored for this base curve in the current year window.")
    else:
        st.dataframe(carsales_table_df, use_container_width=True, hide_index=True)

near_miss_df = _build_unclassified_near_miss_rows(
    active_df,
    make_value=str(curve_info.get("make", "")),
    model_value=str(curve_info.get("model", "")),
    year_min=int(filter_year_min),
    year_max=int(filter_year_max),
)
near_miss_table_df = _prepare_near_miss_table(near_miss_df)
near_miss_reason_counts = (
    near_miss_df["canonical_reason"].fillna("").astype(str).value_counts().rename_axis("reason").reset_index(name="rows")
    if not near_miss_df.empty and "canonical_reason" in near_miss_df.columns
    else pd.DataFrame()
)
section_heading("Unclassified Near Misses", "These recent Autotrader rows share the same make/model and year window but did not match a supported tag. They are excluded from the curve evidence unless you decide they reveal a tagging gap.")
near_cols = st.columns(3)
near_cols[0].metric("Near-Miss Rows", f"{len(near_miss_df):,}")
near_cols[1].metric(
    "Top Reason",
    str(near_miss_reason_counts.iloc[0]["reason"]) if not near_miss_reason_counts.empty else "none",
)
near_cols[2].metric(
    "Distinct Reasons",
    f"{near_miss_reason_counts['reason'].nunique():,}" if not near_miss_reason_counts.empty else "0",
)
if near_miss_df.empty:
    st.success("No same make/model unclassified Autotrader rows were found in the current year window.")
else:
    near_left, near_right = st.columns([1, 2])
    with near_left:
        st.caption("Reasons")
        st.dataframe(near_miss_reason_counts, use_container_width=True, hide_index=True)
    with near_right:
        st.caption("Sample rows")
        st.dataframe(near_miss_table_df.head(50), use_container_width=True, hide_index=True)

editor_seed, seed_message = _prepare_editor_rows(
    selected_base_curve,
    curves_df,
    member_tags,
    evidence_df,
    anchor_overrides_df,
)
editor_state_key = f"curve_builder_v2_editor::{selected_base_curve}"
proposal_note_key = f"curve_builder_v2_proposal_note::{selected_base_curve}"
proposal_meta_key = f"curve_builder_v2_proposal_meta::{selected_base_curve}"
if editor_state_key not in st.session_state:
    st.session_state[editor_state_key] = editor_seed.copy()
if proposal_note_key not in st.session_state:
    st.session_state[proposal_note_key] = seed_message
if proposal_meta_key not in st.session_state:
    st.session_state[proposal_meta_key] = {}

current_editor_state = st.session_state.get(editor_state_key)
current_editor_years = _extract_anchor_years(current_editor_state if isinstance(current_editor_state, pd.DataFrame) else pd.DataFrame(current_editor_state))
seed_anchor_years = _extract_anchor_years(editor_seed)
if configured_anchor_years and current_editor_years != seed_anchor_years:
    st.session_state[editor_state_key] = editor_seed.copy()
    st.session_state[proposal_note_key] = seed_message
    st.session_state[proposal_meta_key] = {}

section_heading("Edit Base Curve Rows", "You are editing V2 base-curve rows, not the original detailed match tags.")
show_deterministic_proposer = filtered_manual_carsales_subset.empty
if show_deterministic_proposer:
    action_left, action_mid, action_right = st.columns([1, 1, 3])
else:
    action_left, action_right = st.columns([1, 4])
    action_mid = None
with action_left:
    if st.button("Reset editor", key=f"curve_builder_v2_reset::{selected_base_curve}"):
        st.session_state[editor_state_key] = editor_seed.copy()
        st.session_state[proposal_note_key] = seed_message
        st.session_state[proposal_meta_key] = {}
        st.rerun()
reuse_editor_anchor_years = False
if show_deterministic_proposer:
    with action_mid:
        reuse_editor_anchor_years = st.checkbox(
            "Reuse editor years",
            value=False,
            key=f"curve_builder_v2_reuse_years::{selected_base_curve}",
            help="Leave this off for clean V2 anchors derived from the filtered evidence. Turn it on only if you want to preserve the current grid years.",
        )
        if st.button("Propose deterministic", key=f"curve_builder_v2_propose::{selected_base_curve}"):
            current_editor_df = st.session_state.get(editor_state_key, editor_seed.copy())
            current_anchor_years = (
                pd.to_numeric(pd.DataFrame(current_editor_df).get("anchor_year"), errors="coerce").dropna().astype(int).unique().tolist()
                if isinstance(current_editor_df, pd.DataFrame)
                else []
            )
            proposed_df, metadata = propose_curve_from_evidence(
                base_curve_tag=selected_base_curve,
                active_market_df=filtered_active_subset,
                sold_df=filtered_sold_subset,
                anchor_years=sorted(current_anchor_years) if reuse_editor_anchor_years and current_anchor_years else suggested_anchor_years,
            )
            if proposed_df.empty:
                st.error("The proposer could not build a curve from the current filtered evidence.")
            else:
                st.session_state[editor_state_key] = proposed_df.copy()
                st.session_state[proposal_meta_key] = {
                    "anchor_years": list(metadata.anchor_years),
                    "active_rows_used": int(metadata.active_rows_used),
                    "active_rows_trimmed": int(metadata.active_rows_trimmed),
                    "sold_rows_observed": int(metadata.sold_rows_observed),
                    "notes": metadata.notes,
                }
                st.session_state[proposal_note_key] = (
                    f"{metadata.notes} Anchor years: {', '.join(str(value) for value in metadata.anchor_years)}. "
                    f"Autotrader rows used: {metadata.active_rows_used}. "
                    f"Outliers trimmed: {metadata.active_rows_trimmed}. "
                    f"Sold rows observed: {metadata.sold_rows_observed}."
                )
                st.rerun()
with action_right:
    if configured_anchor_years:
        st.caption(f"Configured V2 anchor years: {', '.join(str(value) for value in configured_anchor_years)}")
    else:
        st.caption(f"Suggested V2 anchor years from current evidence: {', '.join(str(value) for value in suggested_anchor_years)}")
    if show_deterministic_proposer:
        st.caption(str(st.session_state.get(proposal_note_key) or seed_message))
    else:
        st.caption("Manual Carsales evidence is present for this curve, so deterministic proposing is hidden. Edit and save the curve directly against the Carsales rows.")

edited = st.data_editor(
    st.session_state[editor_state_key],
    num_rows="dynamic",
    use_container_width=True,
    key=f"curve_builder_v2_grid::{selected_base_curve}",
    column_config={
        "canonical_tag": st.column_config.TextColumn("canonical_tag", disabled=True),
        "anchor_year": st.column_config.NumberColumn("anchor_year", step=1, required=True),
        "km_bucket": st.column_config.NumberColumn("km_bucket", step=1000, required=True),
        "price_low": st.column_config.NumberColumn("price_low", step=100, min_value=1),
        "price_mid": st.column_config.NumberColumn("price_mid", step=100, min_value=1),
        "price_high": st.column_config.NumberColumn("price_high", step=100, min_value=1),
    },
)

edited = edited.copy()
edited["canonical_tag"] = selected_base_curve
st.session_state[editor_state_key] = edited.copy()
warnings_df = build_curve_warnings(edited[list(CURVE_COLUMNS)].copy())

proposal_meta = st.session_state.get(proposal_meta_key) or {}
section_heading("Proposal Diagnostics", "This tells you what the deterministic proposer actually used, so you can trust or challenge it quickly.")
diag_cols = st.columns(4)
diag_cols[0].metric(
    "Autotrader Rows Used",
    f"{int(proposal_meta.get('active_rows_used', len(trimmed_active_subset))):,}",
)
diag_cols[1].metric(
    "Outliers Trimmed",
    f"{int(proposal_meta.get('active_rows_trimmed', trimmed_active_count)):,}",
)
diag_cols[2].metric(
    "Sold Rows Observed",
    f"{int(proposal_meta.get('sold_rows_observed', len(filtered_sold_subset))):,}",
)
diag_cols[3].metric(
    "Proposal Anchors",
    ", ".join(str(value) for value in proposal_meta.get("anchor_years", suggested_anchor_years)) or "none",
)

comparison_current_df, comparison_curve_source = _load_comparison_curve_rows(selected_base_curve, curves_df, member_tags)
comparison_df, comparison_summary = _build_curve_comparison(
    comparison_current_df,
    edited[list(CURVE_COLUMNS)].copy(),
    base_curve_tag=selected_base_curve,
)

section_heading("Current Vs Edited", "Review the saved base curve against the current editor state before you overwrite anything.")
compare_cols = st.columns(4)
compare_cols[0].metric("Saved Rows", f"{comparison_summary['current_rows']:,}")
compare_cols[1].metric("Editor Rows", f"{comparison_summary['edited_rows']:,}")
compare_cols[2].metric("Changed Cells", f"{comparison_summary['changed_cells']:,}")
compare_cols[3].metric("Max Mid Delta", f"{int(round(comparison_summary['max_mid_delta'])):,}")

compare_left, compare_right = st.columns(2)
with compare_left:
    if comparison_curve_source == "saved_v2":
        st.caption("Current saved base curve")
    elif comparison_curve_source == "legacy_fallback":
        st.caption("Legacy fallback curve")
    else:
        st.caption("Current saved base curve")
    if comparison_current_df.empty:
        st.info("No saved V2 base curve or legacy fallback curve exists yet for this tag.")
    else:
        st.dataframe(
            comparison_current_df.sort_values(["anchor_year", "km_bucket"]),
            use_container_width=True,
            hide_index=True,
        )
with compare_right:
    st.caption("Difference table")
    if comparison_df.empty:
        st.info("No comparison data available yet.")
    else:
        compare_display = comparison_df[
            [
                "anchor_year",
                "km_bucket",
                "price_low_current",
                "price_low_edited",
                "price_low_delta",
                "price_mid_current",
                "price_mid_edited",
                "price_mid_delta",
                "price_high_current",
                "price_high_edited",
                "price_high_delta",
            ]
        ].copy()
        st.dataframe(compare_display, use_container_width=True, hide_index=True)

validation_left, validation_right = st.columns(2)
with validation_left:
    section_heading("Completeness", "Each anchor year should cover the required km buckets.")
    completeness_df = _build_completeness_frame(edited)
    if completeness_df.empty:
        st.info("No rows to validate yet.")
    else:
        st.dataframe(completeness_df, use_container_width=True, hide_index=True)
with validation_right:
    section_heading("Validation", "These warnings use the same validation logic as the existing curve checks.")
    if warnings_df.empty:
        st.success("No validation warnings detected.")
    else:
        st.dataframe(warnings_df, use_container_width=True, hide_index=True)

if st.button("Save V2 base curve", type="primary"):
    if not warnings_df.empty:
        st.error("Fix the validation warnings before saving.")
    else:
        incoming = edited[list(CURVE_COLUMNS)].copy()
        base = curves_df.copy()
        if not base.empty:
            base = base[base["canonical_tag"].astype(str).str.strip() != selected_base_curve].copy()
        merged = pd.concat([base, incoming], ignore_index=True)
        save_curves(merged)
        st.success(f"Saved {len(incoming)} V2 base-curve rows to {CURVES_PATH}.")
        st.cache_data.clear()
        st.rerun()

current_scope = comparison_current_df.copy()
if not current_scope.empty:
    current_scope["anchor_year"] = pd.to_numeric(current_scope["anchor_year"], errors="coerce")
    current_scope["km_bucket"] = pd.to_numeric(current_scope["km_bucket"], errors="coerce")
    current_scope["price_mid"] = pd.to_numeric(current_scope["price_mid"], errors="coerce")
    current_scope = current_scope.dropna(subset=["anchor_year", "km_bucket", "price_mid"])

curve_scope = edited.copy()
curve_scope["anchor_year"] = pd.to_numeric(curve_scope["anchor_year"], errors="coerce")
curve_scope["km_bucket"] = pd.to_numeric(curve_scope["km_bucket"], errors="coerce")
curve_scope["price_mid"] = pd.to_numeric(curve_scope["price_mid"], errors="coerce")
curve_scope = curve_scope.dropna(subset=["anchor_year", "km_bucket", "price_mid"])

all_plot_anchor_years = sorted(
    {
        int(value)
        for value in pd.concat(
            [
                current_scope["anchor_year"] if not current_scope.empty else pd.Series(dtype="float64"),
                curve_scope["anchor_year"] if not curve_scope.empty else pd.Series(dtype="float64"),
            ],
            ignore_index=True,
        ).dropna().astype(int).tolist()
    }
)

section_heading(
    "Curve Comparison Plot",
    "One chart shows sold evidence, manual Carsales evidence, trimmed Autotrader evidence, and both saved and editor curves. Toggle anchor years to isolate the exact year buckets you want to inspect.",
)
st.caption("Visible anchor years")
toggle_cols = st.columns(max(len(all_plot_anchor_years), 1))
selected_plot_anchor_years: list[int] = []
for index, anchor_year in enumerate(all_plot_anchor_years):
    toggle_key = f"curve_builder_v2_plot_anchor_year::{selected_base_curve}::{int(anchor_year)}"
    with toggle_cols[index]:
        checked = st.checkbox(str(int(anchor_year)), value=True, key=toggle_key)
    if checked:
        selected_plot_anchor_years.append(int(anchor_year))

if not selected_plot_anchor_years:
    st.info("Select at least one anchor year to draw the comparison plot.")
else:
    sold_plot_df = _assign_anchor_year_bucket(filtered_sold_subset, all_plot_anchor_years)
    sold_plot_df = sold_plot_df[sold_plot_df.get("plot_anchor_year").isin(selected_plot_anchor_years)].copy() if not sold_plot_df.empty else sold_plot_df
    carsales_plot_df = _assign_anchor_year_bucket(filtered_manual_carsales_subset, all_plot_anchor_years)
    carsales_plot_df = carsales_plot_df[carsales_plot_df.get("plot_anchor_year").isin(selected_plot_anchor_years)].copy() if not carsales_plot_df.empty else carsales_plot_df
    active_plot_df = _assign_anchor_year_bucket(trimmed_active_subset, all_plot_anchor_years)
    active_plot_df = active_plot_df[active_plot_df.get("plot_anchor_year").isin(selected_plot_anchor_years)].copy() if not active_plot_df.empty else active_plot_df

    chart_meta_cols = st.columns(4)
    chart_meta_cols[0].metric("Visible Sold Points", f"{len(sold_plot_df):,}")
    chart_meta_cols[1].metric("Visible Carsales Points", f"{len(carsales_plot_df):,}")
    chart_meta_cols[2].metric("Visible Autotrader Points", f"{len(active_plot_df):,}")
    chart_meta_cols[3].metric("Visible Anchor Years", ", ".join(str(value) for value in selected_plot_anchor_years))

    fig = plt.figure(figsize=(11, 6.5))
    ax = plt.gca()

    if not sold_plot_df.empty:
        ax.scatter(
            pd.to_numeric(sold_plot_df["odometer_numeric"], errors="coerce"),
            pd.to_numeric(sold_plot_df["price_numeric"], errors="coerce"),
            s=24,
            alpha=0.55,
            c="#374151",
            label="Sold evidence",
        )
    if not carsales_plot_df.empty:
        ax.scatter(
            pd.to_numeric(carsales_plot_df["odometer_numeric"], errors="coerce"),
            pd.to_numeric(carsales_plot_df["price_numeric"], errors="coerce"),
            s=34,
            alpha=0.82,
            c="#16a34a",
            marker="D",
            label="Carsales evidence (manual)",
        )
    if not active_plot_df.empty:
        ax.scatter(
            pd.to_numeric(active_plot_df["odometer_numeric"], errors="coerce"),
            pd.to_numeric(active_plot_df["price_numeric"], errors="coerce"),
            s=24,
            alpha=0.7,
            c="#06b6d4",
            label="Autotrader evidence (trimmed)",
        )

    warm_palette = ["#dc2626", "#ea580c", "#f59e0b", "#d97706", "#b45309", "#9a3412"]
    color_by_year = {
        int(anchor_year): warm_palette[index % len(warm_palette)]
        for index, anchor_year in enumerate(all_plot_anchor_years)
    }

    if not current_scope.empty:
        for anchor_year, subset in current_scope.groupby("anchor_year", sort=True):
            anchor_year_int = int(anchor_year)
            if anchor_year_int not in selected_plot_anchor_years:
                continue
            subset = subset.sort_values("km_bucket")
            baseline_label_prefix = "Saved" if comparison_curve_source == "saved_v2" else "Legacy"
            ax.plot(
                subset["km_bucket"],
                subset["price_mid"],
                linewidth=1.8,
                linestyle="--",
                alpha=0.95,
                color=_lighten_color(color_by_year[anchor_year_int], amount=0.45),
                label=f"{baseline_label_prefix} {anchor_year_int}",
            )

    if not curve_scope.empty:
        editor_label_prefix = "Proposed" if proposal_meta else "Editor"
        for anchor_year, subset in curve_scope.groupby("anchor_year", sort=True):
            anchor_year_int = int(anchor_year)
            if anchor_year_int not in selected_plot_anchor_years:
                continue
            subset = subset.sort_values("km_bucket")
            ax.plot(
                subset["km_bucket"],
                subset["price_mid"],
                marker="o",
                markersize=5,
                linewidth=2.8,
                alpha=0.98,
                color=color_by_year[anchor_year_int],
                label=f"{editor_label_prefix} {anchor_year_int}",
            )

    for km_bucket in REQUIRED_KM:
        ax.axvline(km_bucket, linestyle="--", linewidth=1, alpha=0.12, color="#94a3b8")
    ax.set_title(f"{selected_base_curve} - selected anchor-year buckets")
    ax.set_xlabel("KM")
    ax.set_ylabel("Price ($)")
    ax.legend(ncol=2)
    st.pyplot(fig)
    st.caption("Evidence points are assigned to the nearest selected anchor-year bucket so you can compare each curve year against its own relevant listings. Manual Carsales points are the primary reference for manually built curves; Autotrader remains a support layer.")
