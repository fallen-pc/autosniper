from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st

from shared.csv_utils import read_csv_or_empty
from shared.curves import list_curve_tags, load_curves
from shared.data_loader import dataset_path
from shared.ops_utils import load_active_df, load_valuations_df, parse_percent


STATE_KEY = "global_filter_states"
VEHICLE_TYPE_KEY = "global_filter_vehicle_types"
MARGIN_KEY = "global_filter_margin_threshold"
CURVE_KEY = "global_filter_curve_coverage"

CURVE_OPTIONS = ["All", "With curve", "Without curve"]
DEFAULT_FILTERS = {
    STATE_KEY: [],
    VEHICLE_TYPE_KEY: [],
    MARGIN_KEY: 0.0,
    CURVE_KEY: "All",
}


def _safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _extract_state(value: object) -> str:
    text = _safe_text(value).upper()
    if not text:
        return ""
    match = re.search(r"\b(NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\b", text)
    return match.group(1) if match else ""


def _extract_vehicle_type(value: object) -> str:
    text = _safe_text(value).strip().lower()
    if not text:
        return ""
    normalised = text.replace("-", " ").replace("_", " ")
    tokens = normalised.split()
    if not tokens:
        return ""
    if "hatch" in tokens:
        return "Hatch"
    if "sedan" in tokens:
        return "Sedan"
    if "wagon" in tokens:
        return "Wagon"
    if "suv" in tokens:
        return "SUV"
    if "ute" in tokens or "utility" in tokens:
        return "Ute"
    if "van" in tokens:
        return "Van"
    if "coupe" in tokens:
        return "Coupe"
    if "convertible" in tokens or "cabriolet" in tokens:
        return "Convertible"
    return " ".join(token.capitalize() for token in tokens[:2])


@st.cache_data(ttl=300)
def _load_sidebar_filter_source() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    active_df = load_active_df()
    if not active_df.empty:
        frames.append(active_df.copy())

    valuations_df = load_valuations_df()
    if not active_df.empty and not valuations_df.empty and "url" in valuations_df.columns:
        merged = active_df.merge(valuations_df, on="url", how="left", suffixes=("", "_ai"))
        frames = [merged]

    if not frames:
        fallback = dataset_path("active_vehicle_details.csv")
        if Path(fallback).exists():
            frames.append(read_csv_or_empty(fallback))

    if not frames:
        return pd.DataFrame()

    df = frames[0].copy()
    state_source = None
    for column in ("location_state", "state", "rego_state", "location", "yard"):
        if column in df.columns:
            state_source = df[column]
            break
    if state_source is not None:
        df["_global_state"] = state_source.apply(_extract_state)
    else:
        df["_global_state"] = ""

    vehicle_type_source = None
    for column in ("body_type", "body", "vehicle_type"):
        if column in df.columns:
            vehicle_type_source = df[column]
            break
    if vehicle_type_source is not None:
        df["_global_vehicle_type"] = vehicle_type_source.apply(_extract_vehicle_type)
    else:
        df["_global_vehicle_type"] = ""

    margin_source = None
    for column in ("profit_margin_value", "profit_margin_percent"):
        if column in df.columns:
            margin_source = df[column]
            break
    if margin_source is not None:
        df["_global_margin"] = margin_source.apply(parse_percent)
    else:
        df["_global_margin"] = None

    curve_tags = list_curve_tags(load_curves())
    if "canonical_tag" in df.columns:
        df["_global_has_curve"] = (
            df["canonical_tag"].fillna("").astype(str).str.strip().isin(curve_tags)
        )
    else:
        df["_global_has_curve"] = False
    return df


def render_global_sidebar_filters() -> None:
    for key, default_value in DEFAULT_FILTERS.items():
        st.session_state.setdefault(key, default_value)

    source_df = _load_sidebar_filter_source()
    state_options = []
    vehicle_type_options = []
    if not source_df.empty:
        state_options = sorted(
            {value for value in source_df["_global_state"].dropna().astype(str).tolist() if value}
        )
        vehicle_type_options = sorted(
            {
                value
                for value in source_df["_global_vehicle_type"].dropna().astype(str).tolist()
                if value
            }
        )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Global Filters")
    st.sidebar.caption("Applied across dashboard, AI analysis, missed opportunities, and radar.")
    st.sidebar.multiselect(
        "State",
        options=state_options,
        key=STATE_KEY,
    )
    st.sidebar.multiselect(
        "Vehicle Type",
        options=vehicle_type_options,
        key=VEHICLE_TYPE_KEY,
    )
    st.sidebar.slider(
        "Margin Threshold %",
        min_value=0.0,
        max_value=40.0,
        step=1.0,
        key=MARGIN_KEY,
    )
    st.sidebar.selectbox(
        "Curve Coverage",
        options=CURVE_OPTIONS,
        key=CURVE_KEY,
    )


def get_global_filter_values() -> dict[str, object]:
    return {
        key: st.session_state.get(key, default_value)
        for key, default_value in DEFAULT_FILTERS.items()
    }


def apply_global_sidebar_filters(
    df: pd.DataFrame,
    *,
    state_columns: Sequence[str] | None = None,
    vehicle_type_columns: Sequence[str] | None = None,
    margin_columns: Sequence[str] | None = None,
    canonical_tag_column: str = "canonical_tag",
    curve_tags: Iterable[str] | None = None,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    filters = get_global_filter_values()
    filtered = df.copy()

    state_columns = state_columns or ("location_state", "state", "rego_state", "location", "yard")
    vehicle_type_columns = vehicle_type_columns or ("body_type", "body", "vehicle_type")
    margin_columns = margin_columns or ("profit_margin_value", "profit_margin_percent", "delta_pct")

    state_series = None
    for column in state_columns:
        if column in filtered.columns:
            state_series = filtered[column].apply(_extract_state)
            break
    if state_series is None:
        state_series = pd.Series("", index=filtered.index)

    vehicle_type_series = None
    for column in vehicle_type_columns:
        if column in filtered.columns:
            vehicle_type_series = filtered[column].apply(_extract_vehicle_type)
            break
    if vehicle_type_series is None:
        vehicle_type_series = pd.Series("", index=filtered.index)

    margin_series = None
    for column in margin_columns:
        if column in filtered.columns:
            margin_series = filtered[column].apply(parse_percent)
            break
    if margin_series is None:
        margin_series = pd.Series([None] * len(filtered), index=filtered.index, dtype=object)

    if filters[STATE_KEY]:
        filtered = filtered[state_series.isin(filters[STATE_KEY])]
        state_series = state_series.loc[filtered.index]
        vehicle_type_series = vehicle_type_series.loc[filtered.index]
        margin_series = margin_series.loc[filtered.index]

    if filters[VEHICLE_TYPE_KEY]:
        filtered = filtered[vehicle_type_series.isin(filters[VEHICLE_TYPE_KEY])]
        state_series = state_series.loc[filtered.index]
        vehicle_type_series = vehicle_type_series.loc[filtered.index]
        margin_series = margin_series.loc[filtered.index]

    margin_threshold = float(filters[MARGIN_KEY] or 0.0)
    if margin_threshold > 0:
        filtered = filtered[margin_series.fillna(-9999) >= margin_threshold]
        state_series = state_series.loc[filtered.index]
        vehicle_type_series = vehicle_type_series.loc[filtered.index]

    curve_filter = filters[CURVE_KEY]
    if curve_filter != "All":
        curve_set = set(curve_tags) if curve_tags is not None else list_curve_tags(load_curves())
        if canonical_tag_column in filtered.columns:
            has_curve = (
                filtered[canonical_tag_column].fillna("").astype(str).str.strip().isin(curve_set)
            )
        else:
            has_curve = pd.Series(False, index=filtered.index)
        filtered = filtered[has_curve] if curve_filter == "With curve" else filtered[~has_curve]

    return filtered
