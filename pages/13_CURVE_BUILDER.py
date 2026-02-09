import streamlit as st
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import matplotlib.pyplot as plt

from shared.data_loader import dataset_path
from shared.curves import curve_dataset_name, curve_model, load_curves, save_curves
from shared.spec import load_spec, get_group_spec

# ----------------------------
# CONFIG
# ----------------------------
CURVES_PATH = dataset_path(curve_dataset_name())
GROUP_MAP_PATH = dataset_path("restricted_group_map.csv")
REQUIRED_KM = [50000, 120000, 200000, 260000]
DEFAULT_BUCKET_WEIGHTS = {
    50000: 0.60,
    120000: 0.25,
    200000: 0.10,
    260000: 0.05,
}
DEFAULT_SOURCE = "carsales_curve"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_curves_schema(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "group_id",
        "series",
        "anchor_year",
        "km_anchor",
        "price_low",
        "price_high",
        "price_median",
        "price_per_km_bucket",
        "source",
        "created_at",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    return df[cols]


def _load_curves() -> pd.DataFrame:
    df = load_curves()
    df = _ensure_curves_schema(df)
    df["group_id"] = df["group_id"].astype(str).str.strip()
    df["series"] = df["series"].astype(str).str.strip()
    df["anchor_year"] = pd.to_numeric(df["anchor_year"], errors="coerce").astype("Int64")
    df["km_anchor"] = pd.to_numeric(df["km_anchor"], errors="coerce").astype("Int64")
    for c in ["price_low", "price_high", "price_median", "price_per_km_bucket"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["source"] = df["source"].astype(str).str.strip()
    df["created_at"] = df["created_at"].astype(str).str.strip()
    return df


def _upsert_curve_rows(curves: pd.DataFrame, rows: list[dict]) -> pd.DataFrame:
    keys = ["group_id", "series", "anchor_year", "km_anchor"]
    new_df = pd.DataFrame(rows)
    new_df = _ensure_curves_schema(new_df)
    new_df = new_df.drop_duplicates(subset=keys, keep="last")

    if curves.empty:
        base = curves.copy()
    else:
        base = curves.copy()

    if not base.empty:
        base_keys = list(zip(base["group_id"], base["series"], base["anchor_year"], base["km_anchor"]))
        new_keys = set(zip(new_df["group_id"], new_df["series"], new_df["anchor_year"], new_df["km_anchor"]))
        keep_mask = [k not in new_keys for k in base_keys]
        base = base.loc[keep_mask].copy()

    out = pd.concat([base, new_df], ignore_index=True)
    out = out.sort_values(["group_id", "series", "anchor_year", "km_anchor"], na_position="last")
    out = out.reset_index(drop=True)
    return out


def _expected_years(spec_data: dict, canonical_tag: str) -> list[int]:
    if not spec_data or not canonical_tag:
        return []
    spec_group = get_group_spec(spec_data, canonical_tag)
    if not spec_group:
        return []
    requirements = spec_group.get("curve_requirements") or {}
    years = requirements.get("anchor_years") or []
    return [int(y) for y in years if y]


def _get_existing_points(curves: pd.DataFrame, group_id: str, series: str, anchor_year: int) -> pd.DataFrame:
    if curves.empty:
        return pd.DataFrame()
    sub = curves[
        (curves["group_id"] == group_id)
        & (curves["series"] == series)
        & (curves["anchor_year"] == anchor_year)
        & (curves["km_anchor"].isin(REQUIRED_KM))
    ].copy()
    return sub


def _plot_curves(curves: pd.DataFrame, group_id: str, series: str, years: list[int]) -> None:
    fig = plt.figure()
    ax = plt.gca()

    for km in REQUIRED_KM:
        ax.axvline(km, linestyle="--", linewidth=1)

    for y in years:
        sub = _get_existing_points(curves, group_id, series, y)
        if sub.empty:
            continue
        sub = sub.sort_values("km_anchor")
        x = sub["km_anchor"].astype(float).to_list()
        ax.plot(x, sub["price_median"].to_list(), marker="o", linewidth=2, label=f"{y} median")
        if sub["price_low"].notna().any() and sub["price_high"].notna().any():
            ax.plot(x, sub["price_low"].to_list(), linestyle=":", linewidth=1, label=f"{y} low")
            ax.plot(x, sub["price_high"].to_list(), linestyle=":", linewidth=1, label=f"{y} high")

    ax.set_title(f"{group_id}  |  {series}")
    ax.set_xlabel("KM")
    ax.set_ylabel("Price ($)")
    ax.legend()
    st.pyplot(fig)


def _completeness_table(curves: pd.DataFrame, group_id: str, series: str, years: list[int]) -> pd.DataFrame:
    rows = []
    for y in years:
        sub = _get_existing_points(curves, group_id, series, y)
        present = sorted(sub["km_anchor"].dropna().astype(int).unique().tolist()) if not sub.empty else []
        missing = [k for k in REQUIRED_KM if k not in present]
        rows.append(
            {
                "anchor_year": y,
                "points_present": len(present),
                "points_required": len(REQUIRED_KM),
                "missing_km": "|".join(map(str, missing)) if missing else "",
                "complete": len(missing) == 0,
            }
        )
    return pd.DataFrame(rows)


st.set_page_config(page_title="Curve Builder", layout="wide")
st.title("CURVE BUILDER")
st.caption(
    "Enter low/high ranges for anchor points. Writes to curves.csv in authoritative format. "
    "Plots med/low/high and shows completeness."
)

if curve_model() == "v2":
    st.caption("Curve model: v2 (canonical_tag, anchor_year, km_bucket).")
    curves = load_curves()

    if GROUP_MAP_PATH.exists():
        map_df = pd.read_csv(GROUP_MAP_PATH)
        map_df["canonical_tag"] = map_df.get("canonical_tag", "").astype(str).str.strip()
        map_df = map_df[map_df["canonical_tag"] != ""]
        tag_candidates = map_df["canonical_tag"].dropna().unique().tolist()
    else:
        tag_candidates = []

    if "canonical_tag" in curves.columns:
        tag_candidates.extend(curves["canonical_tag"].dropna().astype(str).str.strip().tolist())

    canonical_tags = sorted({tag for tag in tag_candidates if tag and tag != "UNCLASSIFIED"})
    if not canonical_tags:
        st.error("No canonical tags available. Add entries to curves_v2.csv first.")
        st.stop()

    selected_tag = st.selectbox("Select canonical_tag", options=canonical_tags, index=0)
    tag_rows = curves[curves["canonical_tag"] == selected_tag].copy()
    if tag_rows.empty:
        tag_rows = pd.DataFrame(
            columns=["canonical_tag", "anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]
        )

    st.markdown("### Edit curve rows")
    editor_df = tag_rows[
        ["canonical_tag", "anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]
    ].copy()
    if editor_df.empty:
        editor_df = pd.DataFrame(
            [
                {
                    "canonical_tag": selected_tag,
                    "anchor_year": 2020,
                    "km_bucket": 30000,
                    "price_low": None,
                    "price_mid": None,
                    "price_high": None,
                }
            ]
        )

    edited = st.data_editor(
        editor_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "canonical_tag": st.column_config.TextColumn("canonical_tag", required=True),
            "anchor_year": st.column_config.NumberColumn("anchor_year", step=1, required=True),
            "km_bucket": st.column_config.NumberColumn("km_bucket", step=1000, required=True),
            "price_low": st.column_config.NumberColumn("price_low", step=100),
            "price_mid": st.column_config.NumberColumn("price_mid", step=100),
            "price_high": st.column_config.NumberColumn("price_high", step=100),
        },
    )

    if st.button("Save curves_v2.csv", type="primary"):
        merged = pd.concat([curves, edited], ignore_index=True)
        save_curves(merged)
        st.success(f"Saved {len(edited)} rows to {CURVES_PATH}")
        curves = load_curves()

    st.markdown("### Completeness")
    REQUIRED_KM_V2 = [30000, 60000, 100000, 150000, 200000]
    summary_rows = []
    for year in sorted(tag_rows["anchor_year"].dropna().unique().tolist()):
        year_rows = tag_rows[tag_rows["anchor_year"] == year]
        present = sorted(year_rows["km_bucket"].dropna().astype(int).unique().tolist())
        missing = [k for k in REQUIRED_KM_V2 if k not in present]
        summary_rows.append(
            {
                "anchor_year": int(year),
                "points_present": len(present),
                "points_required": len(REQUIRED_KM_V2),
                "missing_km": ",".join(str(val) for val in missing),
                "complete": len(missing) == 0,
            }
        )
    if summary_rows:
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No rows yet for this tag.")

    st.markdown("### Plot")
    if not tag_rows.empty:
        fig = plt.figure()
        ax = plt.gca()
        for km in REQUIRED_KM_V2:
            ax.axvline(km, linestyle="--", linewidth=1, alpha=0.3)
        for year in sorted(tag_rows["anchor_year"].dropna().unique().tolist()):
            sub = tag_rows[tag_rows["anchor_year"] == year].sort_values("km_bucket")
            ax.plot(sub["km_bucket"], sub["price_mid"], marker="o", linewidth=2, label=str(year))
            ax.scatter(sub["km_bucket"], sub["price_mid"], s=25)
        ax.set_title(selected_tag)
        ax.set_xlabel("KM")
        ax.set_ylabel("Price ($)")
        ax.legend()
        st.pyplot(fig)
    else:
        st.info("No data to plot.")

    st.markdown("### Raw rows (this tag)")
    st.dataframe(tag_rows, use_container_width=True, hide_index=True)
    st.stop()

spec_data = load_spec()
curves = _load_curves()

if not GROUP_MAP_PATH.exists():
    st.error(f"Missing {GROUP_MAP_PATH}. Run restricted dataset build.")
    st.stop()

map_df = pd.read_csv(GROUP_MAP_PATH)
map_df["canonical_tag"] = map_df["canonical_tag"].astype(str).str.strip()
map_df["group_id"] = map_df["group_id"].astype(str).str.strip()
map_df = map_df[map_df["canonical_tag"].ne("")]

# Select canonical tag
canonical_tags = sorted(map_df["canonical_tag"].dropna().unique().tolist())
if not canonical_tags:
    st.error("No canonical tags available.")
    st.stop()

preferred_tag = st.session_state.get("curve_builder_tag")
default_index = canonical_tags.index(preferred_tag) if preferred_tag in canonical_tags else 0
selected_tag = st.selectbox("Select canonical_tag", options=canonical_tags, index=default_index)
row = map_df.loc[map_df["canonical_tag"] == selected_tag].iloc[0]

# Group info
c1, c2, c3 = st.columns([2, 2, 2])
c1.markdown("**Canonical tag**")
c1.code(selected_tag)
c2.markdown("**group_id**")
c2.code(str(row["group_id"]))
series_val = ""
# Best effort to find series from existing curve rows
series_match = curves[curves["group_id"] == str(row["group_id"])].copy()
if not series_match.empty:
    series_val = str(series_match.iloc[0]["series"] or "").strip()
c3.markdown("**series**")
c3.code(series_val if series_val else "(empty)")

# Anchor years
years = _expected_years(spec_data, selected_tag)
if not years:
    st.info("No anchor years found in spec. Enter three years manually.")
    y1, y2, y3 = st.columns(3)
    year_early = y1.number_input("Anchor year 1", min_value=1990, max_value=2030, value=2015, step=1)
    year_mid = y2.number_input("Anchor year 2", min_value=1990, max_value=2030, value=2018, step=1)
    year_late = y3.number_input("Anchor year 3", min_value=1990, max_value=2030, value=2020, step=1)
    years = [int(year_early), int(year_mid), int(year_late)]

# Completeness summary
st.markdown("### Completeness")
audit = _completeness_table(curves, str(row["group_id"]), series_val, years)
complete_years = int(audit["complete"].sum()) if not audit.empty else 0
total_years = len(years)
overall_pct = 0 if total_years == 0 else int(round((complete_years / total_years) * 100))
st.progress(overall_pct / 100, text=f"{overall_pct}% ({complete_years}/{total_years} anchor years complete)")
st.dataframe(audit, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("### Enter / edit ranges")

with st.form("curve_input_form"):
    created_at = st.text_input("created_at (leave default)", value=_now_iso())
    source = st.text_input("source", value=DEFAULT_SOURCE)

    input_rows = []
    for y in years:
        st.markdown(f"#### Anchor year: {y}")
        existing = _get_existing_points(curves, str(row["group_id"]), series_val, int(y))
        existing_map = {}
        if not existing.empty:
            for _, r in existing.iterrows():
                existing_map[int(r["km_anchor"])] = r

        cols = st.columns(len(REQUIRED_KM))
        for i, km in enumerate(REQUIRED_KM):
            ex = existing_map.get(km, None)
            default_low = "" if ex is None or pd.isna(ex.get("price_low")) else str(int(ex["price_low"]))
            default_high = "" if ex is None or pd.isna(ex.get("price_high")) else str(int(ex["price_high"]))
            with cols[i]:
                st.markdown(f"**{km:,} km**")
                low = st.text_input(f"low_{y}_{km}", value=default_low)
                high = st.text_input(f"high_{y}_{km}", value=default_high)
            input_rows.append({"anchor_year": y, "km_anchor": km, "low_raw": low, "high_raw": high})

    save = st.form_submit_button("Save to curves.csv (upsert)")

if save:
    rows_to_write = []
    errors = []
    for r in input_rows:
        y = int(r["anchor_year"])
        km = int(r["km_anchor"])
        low_raw = str(r["low_raw"]).strip()
        high_raw = str(r["high_raw"]).strip()
        if low_raw == "" or high_raw == "":
            continue
        try:
            low = float(low_raw.replace(",", ""))
            high = float(high_raw.replace(",", ""))
        except Exception:
            errors.append(f"Bad number at year {y}, km {km}: low='{low_raw}' high='{high_raw}'")
            continue
        if high < low:
            errors.append(f"High < low at year {y}, km {km}: {low}-{high}")
            continue
        median = (low + high) / 2.0
        bucket = float(DEFAULT_BUCKET_WEIGHTS.get(km, 0.0))
        rows_to_write.append(
            {
                "group_id": str(row["group_id"]),
                "series": series_val,
                "anchor_year": y,
                "km_anchor": km,
                "price_low": low,
                "price_high": high,
                "price_median": median,
                "price_per_km_bucket": bucket,
                "source": source,
                "created_at": created_at,
            }
        )

    if errors:
        st.error("Fix these issues before saving:\n- " + "\n- ".join(errors))
    elif not rows_to_write:
        st.warning("Nothing to save (all inputs blank).")
    else:
        out = _upsert_curve_rows(curves, rows_to_write)
        save_curves(out)
        st.success(f"Saved {len(rows_to_write)} rows to {CURVES_PATH}")
        curves = _load_curves()
        audit = _completeness_table(curves, str(row["group_id"]), series_val, years)

st.markdown("---")
st.markdown("### Plot")
_plot_curves(curves, str(row["group_id"]), series_val, years)

st.markdown("---")
st.markdown("### Raw rows in curves.csv for this group")
sub_all = curves[(curves["group_id"] == str(row["group_id"])) & (curves["series"] == series_val)].copy()
sub_all = sub_all.sort_values(["anchor_year", "km_anchor"])
st.dataframe(sub_all, use_container_width=True, hide_index=True)
