from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from shared.curves import CURVE_COLUMNS, curve_model, load_curves, save_curves
from shared.pipe_keys import parse_pipe_key
from shared.spec import get_group_spec, load_spec
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

if curve_model() == "v2":
    st.caption("Curve model: v2 (canonical_tag, anchor_year, km_bucket).")
    curves_df = load_curves()
    if curves_df.empty or "canonical_tag" not in curves_df.columns:
        st.info("curves_v2.csv is empty. Use the Curve Builder to add rows.")
        st.stop()

    tag_options = sorted(
        {str(tag).strip() for tag in curves_df["canonical_tag"].dropna().tolist() if str(tag).strip()}
    )
    selected_tag = st.selectbox("canonical_tag", tag_options, index=0)
    tag_rows = curves_df[curves_df["canonical_tag"] == selected_tag].copy()

    st.markdown("### Edit rows")
    editor_df = tag_rows[
        ["canonical_tag", "anchor_year", "km_bucket", "price_low", "price_mid", "price_high"]
    ].copy()
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
        merged = pd.concat([curves_df, edited], ignore_index=True)
        save_curves(merged)
        st.success("Saved updates.")
    st.stop()


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

def _base_group_key(group_id: str) -> tuple[str, str, str]:
    parsed = parse_pipe_key(group_id)
    if not parsed:
        return ("", "", "")
    model, group_key, series, _ = parsed
    return (model, group_key, series)


def _expected_km_anchors(spec_data: dict, group_id: str) -> list[int]:
    if not spec_data or not group_id:
        return []
    # try canonical tag via spec lookup, else pipe group
    spec_group = get_group_spec(spec_data, group_id)
    if not spec_group:
        return []
    requirements = spec_group.get("curve_requirements") or {}
    return [int(km) for km in requirements.get("km_anchors", []) if km]


def _plot_curve_group(curves_df: pd.DataFrame, base_group: tuple[str, str, str]) -> None:
    model, group_key, series = base_group
    if not model:
        st.info("Select a curve group to plot.")
        return
    subset = curves_df.copy()
    subset["base_key"] = subset["group_id"].apply(lambda gid: _base_group_key(str(gid)))
    subset = subset[subset["base_key"] == base_group].copy()
    if subset.empty:
        st.info("No curve rows found for this group.")
        return

    import matplotlib.pyplot as plt

    plt.figure(figsize=(10, 4))
    years = sorted({int(y) for y in subset["anchor_year"].dropna()})
    colors = ["#6c757d", "#495057", "#1f77b4", "#ff7f0e", "#2ca02c"]
    for idx, year in enumerate(years):
        year_subset = subset[subset["anchor_year"] == year].copy()
        year_subset = year_subset.sort_values("km_anchor")
        x = year_subset["km_anchor"].astype(int).tolist()
        y = year_subset["price_median"].astype(float).tolist()
        plt.plot(x, y, linewidth=2, color=colors[idx % len(colors)], label=str(year))
        plt.scatter(x, y, s=28, color=colors[idx % len(colors)])

    expected = _expected_km_anchors(SPEC_DATA, subset.iloc[0]["group_id"])
    if not expected:
        expected = sorted({int(km) for km in subset["km_anchor"].dropna()})
    for km in expected:
        plt.axvline(x=km, color="#d0d0d0", linewidth=0.8, linestyle=":")

    plt.xlabel("Kilometres")
    plt.ylabel("Resale price ($)")
    plt.grid(alpha=0.2)
    plt.legend(loc="best", frameon=False)
    plt.tight_layout()
    st.pyplot(plt.gcf(), clear_figure=True, use_container_width=True)


def _curve_completeness(curves_df: pd.DataFrame, base_group: tuple[str, str, str]) -> pd.DataFrame:
    model, group_key, series = base_group
    subset = curves_df.copy()
    subset["base_key"] = subset["group_id"].apply(lambda gid: _base_group_key(str(gid)))
    subset = subset[subset["base_key"] == base_group].copy()
    if subset.empty:
        return pd.DataFrame()
    expected = _expected_km_anchors(SPEC_DATA, subset.iloc[0]["group_id"])
    if not expected:
        expected = sorted({int(km) for km in subset["km_anchor"].dropna()})
    rows = []
    for year in sorted({int(y) for y in subset["anchor_year"].dropna()}):
        year_km = set(subset[subset["anchor_year"] == year]["km_anchor"].dropna().astype(int).tolist())
        present = len(year_km & set(expected))
        rows.append(
            {
                "anchor_year": year,
                "anchors_present": present,
                "anchors_expected": len(expected),
                "missing": max(0, len(expected) - present),
            }
        )
    return pd.DataFrame(rows)


st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Curve editor (interactive)</div>
            <div class="section-subtitle">
                Pick a curve group, edit ranges, and see the plotted anchors with completeness status.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

curve_groups = sorted({str(gid) for gid in curves_df["group_id"].dropna().astype(str).tolist()})
base_groups = sorted({ _base_group_key(gid) for gid in curve_groups if gid })
base_groups = [bg for bg in base_groups if bg != ("", "", "")]
base_labels = [f"{m} | {g} | {s}" for (m, g, s) in base_groups]

if not base_labels:
    st.info("No curve groups available to edit.")
    selected_base = ("", "", "")
else:
    selected_idx = st.selectbox(
        "Curve group (model | group_key | series)",
        list(range(len(base_labels))),
        format_func=lambda idx: base_labels[idx],
        key="curve_editor_group",
    )
    selected_base = base_groups[selected_idx]

if selected_base != ("", "", ""):
    st.caption(f"Group key: {selected_base[0]} | {selected_base[1]} | {selected_base[2]}")
    _plot_curve_group(curves_df, selected_base)
    completeness_df = _curve_completeness(curves_df, selected_base)
    if not completeness_df.empty:
        st.dataframe(completeness_df, width="stretch", hide_index=True)

    # Editable table for this group
    editor_df = curves_df.copy()
    editor_df["base_key"] = editor_df["group_id"].apply(lambda gid: _base_group_key(str(gid)))
    editor_df = editor_df[editor_df["base_key"] == selected_base].copy()
    editor_df = editor_df.drop(columns=["base_key"])
    editor_df = editor_df.sort_values(["anchor_year", "km_anchor"])

    st.markdown("**Edit curve points**")
    edited_group = st.data_editor(
        editor_df,
        num_rows="dynamic",
        use_container_width=True,
        key="curve_editor_table",
    )
    if st.button("Save curve group changes", type="primary"):
        cleaned = _fill_medians(_ensure_columns(pd.concat([curves_df, edited_group], ignore_index=True)))
        # Deduplicate on group_id + anchor_year + km_anchor (keep last)
        cleaned = cleaned.drop_duplicates(
            subset=["group_id", "anchor_year", "km_anchor"], keep="last"
        )
        save_curves(cleaned)
        st.success("Curve group saved.")

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
            <div class="section-title">Corolla hatch petrol auto (multi-year)</div>
            <div class="section-subtitle">
                Overlay of all anchor-year curves for the Corolla hatch petrol auto group.
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

def _plot_corolla_hatch_multi_year(curves_df: pd.DataFrame) -> None:
    base_prefix = "corolla | hatch_petrol_auto"
    subset = curves_df[curves_df["group_id"].astype(str).str.startswith(base_prefix)].copy()
    if subset.empty:
        st.info("No Corolla hatch petrol auto curves found.")
        return
    # Build group_id -> points
    groups = {}
    labels = {}
    anchor_year_points = {}
    for _, row in subset.iterrows():
        gid = str(row.get("group_id") or "")
        parsed = parse_pipe_key(gid)
        if not parsed:
            continue
        model, group_key, series, anchor_year = parsed
        if model != "corolla" or group_key != "hatch_petrol_auto":
            continue
        groups.setdefault(gid, []).append((int(row["km_anchor"]), float(row["price_median"])))
        labels[gid] = f"{series} {anchor_year}"
        anchor_year_points.setdefault(int(anchor_year), []).append(
            (int(row["km_anchor"]), float(row["price_median"]))
        )

    if not groups:
        st.info("No Corolla hatch petrol auto curves found.")
        return

    import matplotlib.pyplot as plt

    plt.figure(figsize=(10, 4))
    anchor_color = "#6c757d"
    interp_color = "#1f77b4"
    for gid in sorted(groups.keys()):
        pts = sorted(groups[gid], key=lambda x: x[0])
        x = [p[0] for p in pts]
        y = [p[1] for p in pts]
        plt.plot(x, y, linewidth=2, color=anchor_color, label=labels.get(gid, gid))
        plt.scatter(x, y, s=28, color=anchor_color)

    # Interpolate years between anchors 2013->2017 and 2017->2020 (if present).
    def _plot_interp_between(lower_year: int, upper_year: int, years: list[int]) -> None:
        if lower_year not in anchor_year_points or upper_year not in anchor_year_points:
            return
        lower_pts = sorted(anchor_year_points[lower_year], key=lambda x: x[0])
        upper_pts = sorted(anchor_year_points[upper_year], key=lambda x: x[0])
        lower_map = {km: price for km, price in lower_pts}
        upper_map = {km: price for km, price in upper_pts}
        common_km = sorted(set(lower_map) & set(upper_map))
        if not common_km:
            return
        for year in years:
            ratio = (year - lower_year) / float(upper_year - lower_year)
            interp = []
            for km in common_km:
                interp_price = lower_map[km] + ratio * (upper_map[km] - lower_map[km])
                interp.append((km, interp_price))
            x = [p[0] for p in interp]
            y = [p[1] for p in interp]
            plt.plot(
                x,
                y,
                linewidth=2,
                color=interp_color,
                linestyle="--",
                label=f"{year} (interp)",
            )
            plt.scatter(x, y, s=22, color=interp_color)

    _plot_interp_between(2013, 2017, [2014, 2015, 2016])
    _plot_interp_between(2017, 2020, [2018, 2019])

    plt.xlabel("Kilometres")
    plt.ylabel("Resale price ($)")
    plt.grid(alpha=0.2)
    plt.legend(loc="best", frameon=False)
    plt.tight_layout()
    st.pyplot(plt.gcf(), clear_figure=True, use_container_width=True)

_plot_corolla_hatch_multi_year(curves_df)


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
