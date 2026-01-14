"""Build VIC-only restricted active/sold datasets for Top-12 model groups."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from shared.data_loader import DATA_DIR
    from shared.grouping import assign_group_id
    from shared.schema import ACTIVE_LISTING_SCHEMA, SOLD_LISTING_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields
else:  # pragma: no cover
    from shared.data_loader import DATA_DIR
    from shared.grouping import assign_group_id
    from shared.schema import ACTIVE_LISTING_SCHEMA, SOLD_LISTING_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields


ACTIVE_SOURCE = DATA_DIR / "active_vehicle_details.csv"
SOLD_SOURCE = DATA_DIR / "sold_cars.csv"
ACTIVE_RESTRICTED = DATA_DIR / "active_vehicle_details_restricted.csv"
SOLD_RESTRICTED = DATA_DIR / "sold_cars_restricted.csv"
GROUP_MAP_PATH = DATA_DIR / "restricted_group_map.csv"


def _has_value(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return text != "" and text.lower() != "nan"


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    working = normalize_listing_fields(df)
    if "url" in working.columns:
        working["url"] = working["url"].astype(str).str.strip()
    return working


def _assign_groups(df: pd.DataFrame, source: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df.copy(), pd.DataFrame(columns=["url", "group_id", "reason_code", "source"])
    group_ids: list[str | None] = []
    reasons: list[str] = []
    for _, row in df.iterrows():
        group_id, reason = assign_group_id(row)
        group_ids.append(group_id)
        reasons.append(reason)
    working = df.copy()
    working["group_id"] = group_ids
    working["reason_code"] = reasons

    mapping = working[["url", "group_id", "reason_code"]].copy()
    mapping["source"] = source
    return working, mapping


def _filter_sold(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if "price" not in df.columns:
        return df.iloc[0:0]
    if "date_sold" not in df.columns:
        return df.iloc[0:0]
    price_mask = df["price"].apply(_has_value)
    date_mask = df["date_sold"].apply(_has_value)
    return df[price_mask & date_mask].copy()


def _write_restricted(df: pd.DataFrame, schema: Iterable[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    restricted = df.reindex(columns=list(schema))
    restricted.to_csv(path, index=False)


def build_restricted_datasets() -> None:
    active_df = pd.read_csv(ACTIVE_SOURCE) if ACTIVE_SOURCE.exists() else pd.DataFrame()
    sold_df = pd.read_csv(SOLD_SOURCE) if SOLD_SOURCE.exists() else pd.DataFrame()

    active_df = _prepare_frame(active_df)
    sold_df = _prepare_frame(sold_df)

    if "date_sold" not in active_df.columns and "time_remaining_or_date_sold" in active_df.columns:
        active_df["date_sold"] = active_df["time_remaining_or_date_sold"]

    sold_df = _filter_sold(sold_df)

    active_with_groups, active_map = _assign_groups(active_df, "active")
    sold_with_groups, sold_map = _assign_groups(sold_df, "sold")

    active_restricted = active_with_groups[active_with_groups["group_id"].notna()].copy()
    sold_restricted = sold_with_groups[sold_with_groups["group_id"].notna()].copy()

    _write_restricted(active_restricted, ACTIVE_LISTING_SCHEMA, ACTIVE_RESTRICTED)
    _write_restricted(sold_restricted, SOLD_LISTING_SCHEMA, SOLD_RESTRICTED)

    group_map = pd.concat([active_map, sold_map], ignore_index=True)
    group_map.to_csv(GROUP_MAP_PATH, index=False)

    print(
        "Restricted datasets updated:",
        f"active={len(active_restricted)}",
        f"sold={len(sold_restricted)}",
        f"map={len(group_map)}",
    )


if __name__ == "__main__":
    build_restricted_datasets()
