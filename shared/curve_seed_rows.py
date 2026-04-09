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
LEGACY_CONFLICT_SUMMARY_COLUMNS = (
    "base_curve_tag",
    "anchor_year",
    "km_bucket",
    "source_tags",
    "lowest_mid_source_tag",
    "lowest_mid_price",
    "highest_mid_source_tag",
    "highest_mid_price",
    "mid_gap",
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


def summarize_legacy_curve_conflicts(conflict_df: pd.DataFrame) -> pd.DataFrame:
    if conflict_df.empty:
        return pd.DataFrame(columns=list(LEGACY_CONFLICT_SUMMARY_COLUMNS))

    working = conflict_df.copy()
    for column in ("anchor_year", "km_bucket", "price_mid"):
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    working["source_tag"] = working.get("source_tag", "").fillna("").astype(str).str.strip()
    working["base_curve_tag"] = working.get("base_curve_tag", "").fillna("").astype(str).str.strip()
    working = working.dropna(subset=["anchor_year", "km_bucket", "price_mid"]).copy()
    if working.empty:
        return pd.DataFrame(columns=list(LEGACY_CONFLICT_SUMMARY_COLUMNS))

    working["anchor_year"] = working["anchor_year"].astype(int)
    working["km_bucket"] = working["km_bucket"].astype(int)
    working["price_mid"] = working["price_mid"].astype(int)

    summary_rows: list[dict[str, object]] = []
    for (base_curve_tag, anchor_year, km_bucket), subset in working.groupby(
        ["base_curve_tag", "anchor_year", "km_bucket"],
        sort=True,
    ):
        ordered = subset.sort_values(["price_mid", "source_tag"], ascending=[True, True]).reset_index(drop=True)
        lowest_row = ordered.iloc[0]
        highest_row = ordered.iloc[-1]
        summary_rows.append(
            {
                "base_curve_tag": str(base_curve_tag),
                "anchor_year": int(anchor_year),
                "km_bucket": int(km_bucket),
                "source_tags": ", ".join(sorted({value for value in ordered["source_tag"].tolist() if value})),
                "lowest_mid_source_tag": str(lowest_row["source_tag"]),
                "lowest_mid_price": int(lowest_row["price_mid"]),
                "highest_mid_source_tag": str(highest_row["source_tag"]),
                "highest_mid_price": int(highest_row["price_mid"]),
                "mid_gap": int(highest_row["price_mid"] - lowest_row["price_mid"]),
            }
        )

    summary_df = pd.DataFrame(summary_rows, columns=list(LEGACY_CONFLICT_SUMMARY_COLUMNS))
    return summary_df.sort_values(["anchor_year", "km_bucket"]).reset_index(drop=True)
