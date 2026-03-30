from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Iterable

import pandas as pd


CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CURVE_GROUPS_V2_PATH = CONFIG_DIR / "curve_groups_v2.csv"
SUPPORTED_CURVE_UNIVERSE_V1_PATH = CONFIG_DIR / "supported_curve_universe_v1.csv"
CURVE_ANCHOR_OVERRIDES_V2_PATH = CONFIG_DIR / "curve_anchor_overrides_v2.csv"

GROUP_COLUMNS = ("match_tag", "base_curve_tag", "group_status", "reason")
UNIVERSE_COLUMNS = (
    "base_curve_tag",
    "make",
    "model",
    "body",
    "fuel",
    "transmission",
    "series",
    "status",
    "priority",
    "notes",
)
ANCHOR_OVERRIDE_COLUMNS = (
    "base_curve_tag",
    "anchor_years",
    "notes",
)


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


@lru_cache(maxsize=1)
def load_curve_groups_v2(path: Path | None = None) -> pd.DataFrame:
    csv_path = path or CURVE_GROUPS_V2_PATH
    if not csv_path.exists():
        return pd.DataFrame(columns=list(GROUP_COLUMNS))
    df = pd.read_csv(csv_path, low_memory=False)
    for column in GROUP_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    for column in GROUP_COLUMNS:
        df[column] = df[column].fillna("").astype(str).str.strip()
    df = df[df["match_tag"].ne("") & df["base_curve_tag"].ne("")].copy()
    df = df.drop_duplicates(subset=["match_tag"], keep="last").reset_index(drop=True)
    return df[list(GROUP_COLUMNS)].copy()


@lru_cache(maxsize=1)
def load_supported_curve_universe_v1(path: Path | None = None) -> pd.DataFrame:
    csv_path = path or SUPPORTED_CURVE_UNIVERSE_V1_PATH
    if not csv_path.exists():
        return pd.DataFrame(columns=list(UNIVERSE_COLUMNS))
    df = pd.read_csv(csv_path, low_memory=False)
    for column in UNIVERSE_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    for column in UNIVERSE_COLUMNS:
        df[column] = df[column].fillna("").astype(str).str.strip()
    if "priority" in df.columns:
        df["priority"] = pd.to_numeric(df["priority"], errors="coerce")
    df = df[df["base_curve_tag"].ne("")].copy()
    df = df.drop_duplicates(subset=["base_curve_tag"], keep="last").reset_index(drop=True)
    return df[list(UNIVERSE_COLUMNS)].copy()


@lru_cache(maxsize=1)
def load_curve_anchor_overrides_v2(path: Path | None = None) -> pd.DataFrame:
    csv_path = path or CURVE_ANCHOR_OVERRIDES_V2_PATH
    if not csv_path.exists():
        return pd.DataFrame(columns=list(ANCHOR_OVERRIDE_COLUMNS))
    df = pd.read_csv(csv_path, low_memory=False)
    for column in ANCHOR_OVERRIDE_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    for column in ANCHOR_OVERRIDE_COLUMNS:
        df[column] = df[column].fillna("").astype(str).str.strip()
    df = df[df["base_curve_tag"].ne("") & df["anchor_years"].ne("")].copy()
    df = df.drop_duplicates(subset=["base_curve_tag"], keep="last").reset_index(drop=True)
    return df[list(ANCHOR_OVERRIDE_COLUMNS)].copy()


def resolve_base_curve_tag(match_tag: object, groups_df: pd.DataFrame | None = None) -> str:
    tag = _normalize_text(match_tag)
    if not tag:
        return ""
    groups = groups_df if groups_df is not None else load_curve_groups_v2()
    if groups.empty:
        return tag
    match_rows = groups[groups["match_tag"] == tag]
    if match_rows.empty:
        return tag
    return _normalize_text(match_rows.iloc[0]["base_curve_tag"]) or tag


def tags_for_base_curve(base_curve_tag: object, groups_df: pd.DataFrame | None = None) -> list[str]:
    tag = _normalize_text(base_curve_tag)
    if not tag:
        return []
    groups = groups_df if groups_df is not None else load_curve_groups_v2()
    if groups.empty:
        return []
    subset = groups[groups["base_curve_tag"] == tag]
    return sorted({_normalize_text(value) for value in subset["match_tag"].tolist() if _normalize_text(value)})


def list_supported_base_curve_tags(
    *,
    statuses: Iterable[str] | None = None,
    supported_df: pd.DataFrame | None = None,
) -> list[str]:
    universe = supported_df if supported_df is not None else load_supported_curve_universe_v1()
    if universe.empty:
        return []
    working = universe.copy()
    if statuses:
        normalized = {str(value).strip().lower() for value in statuses if str(value).strip()}
        if normalized:
            working = working[working["status"].fillna("").astype(str).str.lower().isin(normalized)].copy()
    if "priority" in working.columns:
        working["priority"] = pd.to_numeric(working["priority"], errors="coerce")
        working = working.sort_values(["priority", "base_curve_tag"], ascending=[True, True], na_position="last")
    return working["base_curve_tag"].dropna().astype(str).tolist()


def get_supported_curve_row(base_curve_tag: object, supported_df: pd.DataFrame | None = None) -> dict[str, object]:
    tag = _normalize_text(base_curve_tag)
    universe = supported_df if supported_df is not None else load_supported_curve_universe_v1()
    if universe.empty or not tag:
        return {}
    subset = universe[universe["base_curve_tag"] == tag]
    if subset.empty:
        return {}
    row = subset.iloc[0].to_dict()
    return {str(key): value for key, value in row.items()}


def get_anchor_override_years(base_curve_tag: object, overrides_df: pd.DataFrame | None = None) -> list[int]:
    tag = _normalize_text(base_curve_tag)
    overrides = overrides_df if overrides_df is not None else load_curve_anchor_overrides_v2()
    if overrides.empty or not tag:
        return []
    subset = overrides[overrides["base_curve_tag"] == tag]
    if subset.empty:
        return []
    raw_value = _normalize_text(subset.iloc[0]["anchor_years"])
    if not raw_value:
        return []
    parts = [part.strip() for part in re.split(r"[|,;/\s]+", raw_value) if part.strip()]
    years: list[int] = []
    for part in parts:
        try:
            years.append(int(part))
        except ValueError:
            continue
    return sorted({year for year in years if 1900 <= year <= 2100})
