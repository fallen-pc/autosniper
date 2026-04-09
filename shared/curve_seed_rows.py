from __future__ import annotations

import pandas as pd


CURVE_COLUMNS = (
    "canonical_tag",
    "anchor_year",
    "km_bucket",
    "price_low",
    "price_mid",
    "price_high",
)
CURVE_KEY_COLUMNS = ("anchor_year", "km_bucket")
CURVE_PRICE_COLUMNS = ("price_low", "price_mid", "price_high")
LEGACY_CONFLICT_COLUMNS = (
    "base_curve_tag",
    "anchor_year",
    "km_bucket",
    "source_tag",
    "price_low",
    "price_mid",
    "price_high",
)


def build_legacy_curve_seed_rows(
    *,
    base_curve_tag: str,
    curves_df: pd.DataFrame,
    member_tags: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if curves_df.empty or not member_tags:
        return pd.DataFrame(columns=list(CURVE_COLUMNS)), pd.DataFrame(columns=list(LEGACY_CONFLICT_COLUMNS))

    legacy_rows = curves_df[curves_df["canonical_tag"].astype(str).str.strip().isin(member_tags)].copy()
    if legacy_rows.empty:
        return pd.DataFrame(columns=list(CURVE_COLUMNS)), pd.DataFrame(columns=list(LEGACY_CONFLICT_COLUMNS))

    working = legacy_rows[list(CURVE_COLUMNS)].copy()
    working["source_tag"] = working["canonical_tag"].astype(str).str.strip()
    working["canonical_tag"] = str(base_curve_tag or "").strip()
    for column in CURVE_KEY_COLUMNS + CURVE_PRICE_COLUMNS:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working = working.dropna(subset=list(CURVE_KEY_COLUMNS) + list(CURVE_PRICE_COLUMNS)).copy()
    if working.empty:
        return pd.DataFrame(columns=list(CURVE_COLUMNS)), pd.DataFrame(columns=list(LEGACY_CONFLICT_COLUMNS))

    working["anchor_year"] = working["anchor_year"].astype(int)
    working["km_bucket"] = working["km_bucket"].astype(int)
    for column in CURVE_PRICE_COLUMNS:
        working[column] = working[column].astype(int)

    conflicts: list[pd.DataFrame] = []
    for (_anchor_year, _km_bucket), subset in working.groupby(list(CURVE_KEY_COLUMNS), sort=True):
        price_variants = subset[list(CURVE_PRICE_COLUMNS)].drop_duplicates()
        if len(price_variants) <= 1:
            continue
        conflict_rows = subset[
            ["anchor_year", "km_bucket", "source_tag", "price_low", "price_mid", "price_high"]
        ].drop_duplicates()
        conflict_rows.insert(0, "base_curve_tag", str(base_curve_tag or "").strip())
        conflicts.append(conflict_rows[list(LEGACY_CONFLICT_COLUMNS)])

    if conflicts:
        conflict_df = pd.concat(conflicts, ignore_index=True)
        conflict_df = conflict_df.sort_values(["anchor_year", "km_bucket", "source_tag"]).reset_index(drop=True)
        return pd.DataFrame(columns=list(CURVE_COLUMNS)), conflict_df

    deduped = working.drop_duplicates(subset=list(CURVE_COLUMNS), keep="first")
    deduped = deduped[list(CURVE_COLUMNS)].sort_values(["anchor_year", "km_bucket"]).reset_index(drop=True)
    return deduped, pd.DataFrame(columns=list(LEGACY_CONFLICT_COLUMNS))
