"""Build restricted active/sold datasets keyed by canonical_tag."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Tuple

import pandas as pd

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.atomic_csv import append_dataframe_csv_atomic, write_dataframe_csv_atomic
    from shared.audit import append_audit_snapshot
    from shared.data_loader import dataset_path
    from shared.canonical_tagging import AMBIG_DRIVETRAIN, UNCLASSIFIED, tag_dataframe
    from shared.schema import ACTIVE_LISTING_SCHEMA, SOLD_LISTING_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields
else:  # pragma: no cover
    from scripts.atomic_csv import append_dataframe_csv_atomic, write_dataframe_csv_atomic
    from shared.audit import append_audit_snapshot
    from shared.data_loader import dataset_path
    from shared.canonical_tagging import AMBIG_DRIVETRAIN, UNCLASSIFIED, tag_dataframe
    from shared.schema import ACTIVE_LISTING_SCHEMA, SOLD_LISTING_SCHEMA
    from shared.sold_cleaning import normalize_listing_fields


ACTIVE_SOURCE = dataset_path("active_vehicle_details.csv")
SOLD_SOURCE = dataset_path("sold_cars.csv")
ACTIVE_RESTRICTED = dataset_path("active_vehicle_details_restricted.csv")
SOLD_RESTRICTED = dataset_path("sold_cars_restricted.csv")
GROUP_MAP_PATH = dataset_path("restricted_group_map.csv")
ENRICHMENT_BACKLOG_PATH = dataset_path("quality/enrichment_backlog.csv")
SCOPE_NAME = "toyota_v1"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def _assign_groups(
    df: pd.DataFrame, source: str, *, require_price: bool
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df.copy(), pd.DataFrame(
            columns=["url", "canonical_tag", "reason_code", "source"]
        )

    working = tag_dataframe(
        df, source=source, require_price=require_price, filter_unclassified=False, append_log=True
    )
    if "canonical_tag" not in working.columns:
        working["canonical_tag"] = UNCLASSIFIED
    if "canonical_reason" not in working.columns:
        working["canonical_reason"] = ""

    working["reason_code"] = working["canonical_reason"]

    mapping = working[["url", "canonical_tag", "reason_code"]].copy()
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
    write_dataframe_csv_atomic(restricted, path, index=False)


def _normalized_assignment_series(df: pd.DataFrame, column: str) -> pd.Series:
    return _column_or_blank(df, column).fillna("").astype(str).str.strip()


def _persist_canonical_assignments(
    source_df: pd.DataFrame,
    tagged_df: pd.DataFrame,
    path: Path,
) -> int:
    """Persist refreshed tags back to the source without changing its row set."""
    if source_df.empty or tagged_df.empty or "url" not in source_df.columns or "url" not in tagged_df.columns:
        return 0

    assignment_columns = ["url", "canonical_tag", "canonical_reason"]
    assignments = tagged_df.reindex(columns=assignment_columns).copy()
    assignments["url"] = assignments["url"].fillna("").astype(str).str.strip()
    assignments = assignments[assignments["url"].ne("")].drop_duplicates("url", keep="last")
    if assignments.empty:
        return 0

    working = source_df.copy()
    working["url"] = working["url"].fillna("").astype(str).str.strip()
    for column in ("canonical_tag", "canonical_reason"):
        if column not in working.columns:
            working[column] = ""

    assignment_lookup = assignments.set_index("url")
    matched_mask = working["url"].isin(assignment_lookup.index)
    if not matched_mask.any():
        return 0

    before_tag = _normalized_assignment_series(working, "canonical_tag")
    before_reason = _normalized_assignment_series(working, "canonical_reason")
    matched_urls = working.loc[matched_mask, "url"]
    working.loc[matched_mask, "canonical_tag"] = matched_urls.map(assignment_lookup["canonical_tag"]).to_numpy()
    working.loc[matched_mask, "canonical_reason"] = matched_urls.map(assignment_lookup["canonical_reason"]).to_numpy()
    after_tag = _normalized_assignment_series(working, "canonical_tag")
    after_reason = _normalized_assignment_series(working, "canonical_reason")
    changed_mask = before_tag.ne(after_tag) | before_reason.ne(after_reason)
    changed_count = int(changed_mask.sum())
    if changed_count:
        write_dataframe_csv_atomic(working, path, index=False)
    return changed_count


def _column_or_blank(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series("", index=df.index, dtype="object")


def _append_enrichment_backlog(df: pd.DataFrame, source: str) -> None:
    if df.empty:
        return
    now = _utc_now()
    timestamp = now.isoformat(timespec="seconds")
    dataset_date = now.date().isoformat()
    working = df.copy()
    working["make_norm"] = _column_or_blank(working, "make").astype(str).str.lower().str.strip()
    working["model_norm"] = _column_or_blank(working, "model").astype(str).str.lower().str.strip()
    working["canonical_reason"] = _column_or_blank(working, "canonical_reason").astype(str).str.strip()

    rows: list[dict[str, object]] = []

    ambig = working[working["canonical_reason"] == AMBIG_DRIVETRAIN]
    if not ambig.empty:
        counts = ambig.groupby("model_norm").size()
        for model, count in counts.items():
            rows.append(
                {
                    "timestamp": timestamp,
                    "dataset_date": dataset_date,
                    "scope": SCOPE_NAME,
                    "source": source,
                    "category": "ambig_drivetrain",
                    "model": model or "unknown",
                    "count": int(count),
                }
            )

    hilux = working[working["model_norm"] == "hilux"]
    if not hilux.empty:
        text_fields = ["variant", "title", "body_type", "drivetrain", "series"]
        text_blob = (
            hilux[[field for field in text_fields if field in hilux.columns]]
            .fillna("")
            .astype(str)
            .agg(" ".join, axis=1)
            .str.lower()
        )
        hi_rider_mask = text_blob.str.contains(r"\b(?:4x2|2wd|hi[- ]?rider)\b", na=False)
        if hi_rider_mask.any():
            rows.append(
                {
                    "timestamp": timestamp,
                    "dataset_date": dataset_date,
                    "scope": SCOPE_NAME,
                    "source": source,
                    "category": "hilux_4x2_hi_rider",
                    "model": "hilux",
                    "count": int(hi_rider_mask.sum()),
                }
            )
        cab_mask = _column_or_blank(hilux, "body_type").astype(str).str.lower().str.contains("cab chassis", na=False)
        if cab_mask.any():
            rows.append(
                {
                    "timestamp": timestamp,
                    "dataset_date": dataset_date,
                    "scope": SCOPE_NAME,
                    "source": source,
                    "category": "hilux_cab_chassis",
                    "model": "hilux",
                    "count": int(cab_mask.sum()),
                }
            )

    if not rows:
        return

    ENRICHMENT_BACKLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = ENRICHMENT_BACKLOG_PATH.exists()
    if file_exists:
        existing = pd.read_csv(ENRICHMENT_BACKLOG_PATH, low_memory=False)
        if not existing.empty:
            existing_key = set(
                zip(
                    existing.get("dataset_date", "").astype(str),
                    existing.get("scope", "").astype(str),
                    existing.get("source", "").astype(str),
                    existing.get("category", "").astype(str),
                    existing.get("model", "").astype(str),
                    existing.get("count", "").astype(str),
                )
            )
            rows = [
                row
                for row in rows
                if (
                    str(row.get("dataset_date")),
                    str(row.get("scope")),
                    str(row.get("source")),
                    str(row.get("category")),
                    str(row.get("model")),
                    str(row.get("count")),
                )
                not in existing_key
            ]
    if not rows:
        return
    append_dataframe_csv_atomic(pd.DataFrame(rows), ENRICHMENT_BACKLOG_PATH, index=False)


def build_restricted_datasets() -> None:
    active_df = pd.read_csv(ACTIVE_SOURCE, low_memory=False) if ACTIVE_SOURCE.exists() else pd.DataFrame()
    sold_source_df = pd.read_csv(SOLD_SOURCE, low_memory=False) if SOLD_SOURCE.exists() else pd.DataFrame()

    active_df = _prepare_frame(active_df)
    sold_df = _prepare_frame(sold_source_df)

    if "date_sold" not in active_df.columns and "time_remaining_or_date_sold" in active_df.columns:
        active_df["date_sold"] = active_df["time_remaining_or_date_sold"]

    sold_df = _filter_sold(sold_df)
    active_with_groups, active_map = _assign_groups(active_df, "active", require_price=False)
    sold_with_groups, sold_map = _assign_groups(sold_df, "sold", require_price=True)
    sold_source_retagged = _persist_canonical_assignments(
        sold_source_df,
        sold_with_groups,
        SOLD_SOURCE,
    )

    active_restricted = active_with_groups[
        active_with_groups["canonical_tag"] != UNCLASSIFIED
    ].copy()
    sold_restricted = sold_with_groups[
        sold_with_groups["canonical_tag"] != UNCLASSIFIED
    ].copy()

    _write_restricted(active_restricted, ACTIVE_LISTING_SCHEMA, ACTIVE_RESTRICTED)
    _write_restricted(sold_restricted, SOLD_LISTING_SCHEMA, SOLD_RESTRICTED)

    group_map = pd.concat([active_map, sold_map], ignore_index=True)
    write_dataframe_csv_atomic(group_map, GROUP_MAP_PATH, index=False)

    append_audit_snapshot(active_restricted, ACTIVE_RESTRICTED)
    append_audit_snapshot(sold_restricted, SOLD_RESTRICTED)
    append_audit_snapshot(group_map, GROUP_MAP_PATH)
    _append_enrichment_backlog(active_with_groups, "active")
    _append_enrichment_backlog(sold_with_groups, "sold")

    print(
        "Restricted datasets updated:",
        f"active={len(active_restricted)}",
        f"sold={len(sold_restricted)}",
        f"map={len(group_map)}",
        f"sold_source_retagged={sold_source_retagged}",
    )


if __name__ == "__main__":
    build_restricted_datasets()
