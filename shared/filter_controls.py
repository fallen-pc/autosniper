from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, MutableMapping, Optional, Tuple

import pandas as pd
import streamlit as st

TIME_FILTER_OPTIONS: Mapping[str, Tuple[Optional[float], Optional[float]]] = {
    "All": (None, None),
    "< 24h": (0.0, 24.0),
    "24-48h": (24.0, 48.0),
    "48-72h": (48.0, 72.0),
    "> 72h": (72.0, None),
}

TIME_DESCRIPTIONS: Mapping[str, str] = {
    "All": "any time window",
    "< 24h": "the next 24 hours",
    "24-48h": "24 to 48 hours from now",
    "48-72h": "48 to 72 hours from now",
    "> 72h": "more than 72 hours away",
}

ENGINE_ISSUE_KEYWORDS = [
    "engine light",
    "rough idle",
    "engine oil leak",
    "smoke",
    "seized",
    "blown",
    "won't start",
    "does not start",
    "engine does not turn",
    "no compression",
]


@dataclass
class VehicleFilterToggles:
    hide_engine_defects: bool = True
    hide_unregistered: bool = False
    vic_only: bool = False


def render_time_filter(
    *,
    container: Optional[st.delta_generator.DeltaGenerator] = None,
    label: str = "Time remaining filter",
    default_option: str = "< 24h",
    horizontal: bool = False,
) -> tuple[str, tuple[Optional[float], Optional[float]]]:
    """Render the standard time filter radio and return the selection."""
    component = container or st.sidebar
    options = list(TIME_FILTER_OPTIONS.keys())
    default = default_option if default_option in TIME_FILTER_OPTIONS else options[0]
    default_index = options.index(default)
    choice = component.radio(
        label,
        options=options,
        index=default_index,
        horizontal=horizontal,
    )
    return choice, TIME_FILTER_OPTIONS[choice]


def describe_time_selection(choice: str) -> str:
    return TIME_DESCRIPTIONS.get(choice, choice)


def render_vehicle_filter_toggles(
    *,
    container: Optional[st.delta_generator.DeltaGenerator] = None,
    defaults: Optional[MutableMapping[str, bool]] = None,
    key_prefix: str | None = None,
) -> VehicleFilterToggles:
    """Render the shared vehicle filter checkboxes."""
    component = container or st.sidebar
    values = defaults or {}
    prefix = key_prefix or ""
    hide_engine_defects = component.checkbox(
        "Hide vehicles with engine defects",
        value=values.get("hide_engine_defects", True),
        key=f"{prefix}hide_engine_defects",
    )
    hide_unregistered = component.checkbox(
        "Hide unregistered vehicles",
        value=values.get("hide_unregistered", False),
        key=f"{prefix}hide_unregistered",
    )
    vic_only = component.checkbox(
        "Show only VIC listings",
        value=values.get("vic_only", False),
        key=f"{prefix}vic_only",
    )
    return VehicleFilterToggles(
        hide_engine_defects=hide_engine_defects,
        hide_unregistered=hide_unregistered,
        vic_only=vic_only,
    )


def apply_vehicle_filters(
    df: pd.DataFrame,
    toggles: VehicleFilterToggles,
    *,
    condition_column: str = "general_condition",
    plates_column: str = "no_of_plates",
    location_column: str = "location",
) -> pd.DataFrame:
    """Apply shared vehicle filters to a dataframe."""
    filtered = df.copy()

    if toggles.hide_engine_defects and condition_column in filtered.columns:
        condition_series = filtered[condition_column].astype(str).str.lower()
        mask = condition_series.apply(
            lambda text: any(keyword in text for keyword in ENGINE_ISSUE_KEYWORDS)
        )
        filtered = filtered[~mask]

    if toggles.hide_unregistered and plates_column in filtered.columns:
        def _is_unregistered(value: object) -> bool:
            try:
                return int(float(str(value).strip())) == 0
            except (TypeError, ValueError, AttributeError):
                return False

        mask = filtered[plates_column].apply(_is_unregistered)
        filtered = filtered[~mask]

    if toggles.vic_only and location_column in filtered.columns:
        mask = filtered[location_column].astype(str).str.upper().str.contains("VIC", na=False)
        filtered = filtered[mask]

    return filtered
