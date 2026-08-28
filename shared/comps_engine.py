"""Comparable sales engine used to predict final auction prices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

import numpy as np
import pandas as pd


_VARIANT_NOISE = frozenset(
    {
        "4x2", "4x4", "4wd", "2wd", "rwd", "fwd", "awd",
        "auto", "manual", "turbo", "diesel", "petrol", "hybrid",
        "cab", "crew", "extra", "double", "single", "king",
        "sedan", "hatch", "hatchback", "wagon", "ute", "suv",
        "van", "coupe", "convertible",
    }
)


def _variant_family(text: object) -> str:
    """Return a normalised trim-grade token for variant matching.

    Takes the first space-delimited token that isn't a generic body/drivetrain
    descriptor.  Returns empty string when variant is absent or uninformative.
    """
    if text is None:
        return ""
    tokens = str(text).lower().strip().split()
    for token in tokens:
        clean = token.strip("()-/")
        if clean and clean not in _VARIANT_NOISE and not clean.isdigit():
            return clean
    return ""


def parse_currency(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if (ch.isdigit() or ch == "." or ch == "-"))
    if not digits:
        return None
    try:
        return float(digits.replace(",", ""))
    except ValueError:
        return None


def parse_numeric(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


@dataclass
class CompsEngineConfig:
    min_comps: int = 5
    preferred_comps: int = 40
    year_window: int = 3
    severity_window: int = 15
    odometer_ratio: float = 0.6  # +/-60% spread
    recent_days: int = 180
    year_adjustment: float = 700.0
    odo_adjustment_per_10k: float = 280.0
    severity_adjustment: float = 80.0
    state_penalty: float = 200.0
    decay_halflife_days: float = 365.0  # time-decay half-life for comp weighting


class CompsEngine:
    """Predict final prices by blending historical comparable sales."""

    def __init__(self, data: pd.DataFrame, config: CompsEngineConfig | None = None):
        self.config = config or CompsEngineConfig()
        self.data = self._prepare_dataset(data)

    @staticmethod
    def _prepare_dataset(frame: pd.DataFrame) -> pd.DataFrame:
        working = frame.copy()
        if "sale_price" in working.columns:
            working["sale_price_value"] = working["sale_price"].apply(parse_currency)
        else:
            working["sale_price_value"] = pd.NA
        if "price" in working.columns:
            working["price_value"] = working["price"].apply(parse_currency)
            working["sale_price_value"] = working["sale_price_value"].fillna(working["price_value"])
            working.drop(columns=["price_value"], inplace=True)
        working["odometer_numeric"] = working["odometer_reading"].apply(parse_numeric)
        working["year_numeric"] = working["year"].apply(parse_numeric)
        working["repair_severity"] = working["repair_severity"].fillna(0).astype(float)
        working["date_sold"] = pd.to_datetime(working["date_sold"], errors="coerce")
        working = working.dropna(subset=["sale_price_value", "date_sold", "make", "model"])
        working["make"] = working["make"].astype(str).str.upper()
        working["model"] = working["model"].astype(str).str.title()
        working["body_type"] = (
            working["body_type"] if "body_type" in working.columns
            else pd.Series("", index=working.index)
        ).astype(str).str.title()
        working["transmission"] = (
            working["transmission"] if "transmission" in working.columns
            else pd.Series("", index=working.index)
        ).astype(str).str.title()
        if "location_state" in working.columns:
            location_base = working["location_state"]
        elif "location" in working.columns:
            location_base = working["location"]
        else:
            location_base = pd.Series("", index=working.index)
        working["location_state"] = location_base.astype(str).str.strip()
        working["location_state"] = working["location_state"].replace("", np.nan)
        variant_col = working["variant"] if "variant" in working.columns else pd.Series("", index=working.index)
        working["variant_family"] = variant_col.apply(_variant_family)
        return working.reset_index(drop=True)

    def _initial_pool(self, row: pd.Series) -> pd.DataFrame:
        data = self.data
        mask = (data["make"] == row["make"]) & (data["model"] == row["model"])
        if "url" in data.columns and "url" in row and isinstance(row["url"], str):
            mask &= data["url"] != row["url"]
        pool = data.loc[mask].copy()
        subject_date = row["date_sold"]
        if pd.notna(subject_date):
            pool = pool[pool["date_sold"] <= subject_date]

        # Prefer same variant family (e.g. "sr5" vs "sr") to avoid cross-spec contamination.
        # Fall back to full make/model pool only when the variant pool is too thin.
        subject_variant = _variant_family(row.get("variant", ""))
        if subject_variant and "variant_family" in pool.columns:
            variant_pool = pool[pool["variant_family"] == subject_variant]
            if len(variant_pool) >= self.config.min_comps:
                return variant_pool

        return pool

    def _filtered_pool(self, row: pd.Series) -> pd.DataFrame:
        pool = self._initial_pool(row)
        if pool.empty:
            return pool
        cfg = self.config

        year = row.get("year_numeric")
        severity = row.get("repair_severity", 0)
        odometer = row.get("odometer_numeric")

        factors = (1.0, 1.5, 2.0)
        fallback = pool
        for factor in factors:
            filtered = pool.copy()
            if pd.notna(year):
                window = cfg.year_window * factor
                filtered = filtered[filtered["year_numeric"].between(year - window, year + window, inclusive="both")]
            if pd.notna(severity):
                window = cfg.severity_window * factor
                filtered = filtered[
                    filtered["repair_severity"].between(severity - window, severity + window, inclusive="both")
                ]
            if pd.notna(odometer):
                ratio = cfg.odometer_ratio * factor
                lower = odometer * (1 - ratio)
                upper = odometer * (1 + ratio)
                filtered = filtered[
                    filtered["odometer_numeric"].between(lower, upper, inclusive="both")
                ]
            if not filtered.empty:
                fallback = filtered
            if not filtered.empty and len(filtered) >= cfg.min_comps:
                return filtered
        return fallback

    def _adjust_price(self, comp: pd.Series, subject: pd.Series) -> float:
        cfg = self.config
        price = comp["sale_price_value"]
        if pd.isna(price):
            return np.nan
        adj = 0.0
        subj_year = subject.get("year_numeric")
        comp_year = comp.get("year_numeric")
        if pd.notna(subj_year) and pd.notna(comp_year):
            adj += (subj_year - comp_year) * cfg.year_adjustment
        subj_odo = subject.get("odometer_numeric")
        comp_odo = comp.get("odometer_numeric")
        if pd.notna(subj_odo) and pd.notna(comp_odo):
            adj += (comp_odo - subj_odo) / 10000.0 * cfg.odo_adjustment_per_10k
        subj_sev = subject.get("repair_severity", 0.0)
        comp_sev = comp.get("repair_severity", 0.0)
        if pd.notna(subj_sev) and pd.notna(comp_sev):
            adj += (comp_sev - subj_sev) * cfg.severity_adjustment
        subj_state = str(subject.get("location_state") or "").strip().upper()
        comp_state = str(comp.get("location_state") or "").strip().upper()
        if subj_state and comp_state and subj_state != comp_state:
            adj -= cfg.state_penalty
        return price + adj

    @staticmethod
    def _percentile(values: Iterable[float], percentile: float) -> float | None:
        arr = np.array([v for v in values if pd.notna(v)], dtype=float)
        if arr.size == 0:
            return None
        return float(np.percentile(arr, percentile))

    @staticmethod
    def _weighted_percentile(
        values: np.ndarray, weights: np.ndarray, percentile: float
    ) -> float | None:
        mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
        if not mask.any():
            return None
        v = values[mask]
        w = weights[mask]
        order = np.argsort(v)
        v, w = v[order], w[order]
        cumw = np.cumsum(w)
        threshold = (percentile / 100.0) * cumw[-1]
        idx = int(np.searchsorted(cumw, threshold, side="left"))
        return float(v[min(idx, len(v) - 1)])

    def _decay_weights(self, pool: pd.DataFrame, subject_date: pd.Timestamp) -> np.ndarray:
        halflife = self.config.decay_halflife_days
        if halflife <= 0 or not pd.notna(subject_date):
            return np.ones(len(pool), dtype=float)
        days_old = (subject_date - pool["date_sold"]).dt.days.fillna(halflife).clip(lower=0)
        return np.exp(-np.log(2) / halflife * days_old.to_numpy(dtype=float))

    def predict_row(self, row: pd.Series) -> Tuple[float | None, float | None, int, float]:
        pool = self._filtered_pool(row)
        if pool.empty:
            return (None, None, 0, 0.0)
        adjusted = pool.apply(lambda comp: self._adjust_price(comp, row), axis=1)
        pool = pool.assign(adjusted_price=adjusted)
        pool = pool.dropna(subset=["adjusted_price"])
        if pool.empty:
            return (None, None, 0, 0.0)

        comps_count = len(pool)
        subject_date = row["date_sold"]
        weights = self._decay_weights(pool, subject_date)
        vals = pool["adjusted_price"].to_numpy(dtype=float)
        p50 = self._weighted_percentile(vals, weights, 50)
        p90 = self._weighted_percentile(vals, weights, 90)

        cfg = self.config
        recent_ratio = 0.0
        if pd.notna(subject_date):
            recent_cutoff = subject_date - pd.Timedelta(days=cfg.recent_days)
            recent_ratio = pool[pool["date_sold"] >= recent_cutoff].shape[0] / max(comps_count, 1)
        confidence = min(1.0, (comps_count / cfg.preferred_comps) * 0.7 + recent_ratio * 0.3)
        return (p50, p90, comps_count, float(confidence))

    def run(self) -> pd.DataFrame:
        predictions = []
        for _, row in self.data.iterrows():
            p50, p90, count, confidence = self.predict_row(row)
            predictions.append(
                {
                    "comps_p50": p50,
                    "comps_p90": p90,
                    "comps_count": count,
                    "comps_confidence": confidence,
                }
            )
        return pd.DataFrame(predictions)


def fit_adjustment_constants(
    data: pd.DataFrame,
    config: CompsEngineConfig | None = None,
) -> CompsEngineConfig:
    """Derive adjustment constants from OLS regression on sold data.

    Fits sale_price ~ year + odometer_per_10k + repair_severity + cross_state
    and returns a new CompsEngineConfig whose adjustment fields are replaced with
    the regression coefficients (clamped to reasonable ranges so a thin dataset
    doesn't produce nonsense).  Any non-numeric rows are silently dropped.
    """
    base = config or CompsEngineConfig()
    engine = CompsEngine(data, base)
    df = engine.data.copy()
    df = df.dropna(subset=["sale_price_value", "year_numeric", "odometer_numeric", "repair_severity"])
    if len(df) < 30:
        return base  # not enough data to trust the fit

    mode_state = df["location_state"].mode()
    ref_state = mode_state.iloc[0] if not mode_state.empty else ""
    df["cross_state"] = (
        df["location_state"].fillna("").ne(ref_state) & df["location_state"].notna()
    ).astype(float)

    X = df[["year_numeric", "odometer_numeric", "repair_severity", "cross_state"]].copy()
    X["odometer_per_10k"] = X["odometer_numeric"] / 10_000.0
    X = X.drop(columns=["odometer_numeric"])
    X.insert(0, "intercept", 1.0)
    y = df["sale_price_value"].to_numpy(dtype=float)
    Xm = X.to_numpy(dtype=float)

    try:
        coeffs, *_ = np.linalg.lstsq(Xm, y, rcond=None)
    except np.linalg.LinAlgError:
        return base

    _, year_coeff, odo_per_10k_coeff, severity_coeff, state_coeff = coeffs

    return CompsEngineConfig(
        min_comps=base.min_comps,
        preferred_comps=base.preferred_comps,
        year_window=base.year_window,
        severity_window=base.severity_window,
        odometer_ratio=base.odometer_ratio,
        recent_days=base.recent_days,
        decay_halflife_days=base.decay_halflife_days,
        year_adjustment=float(np.clip(year_coeff, 200.0, 3000.0)),
        odo_adjustment_per_10k=float(np.clip(odo_per_10k_coeff, 50.0, 1000.0)),
        severity_adjustment=float(np.clip(severity_coeff, 10.0, 500.0)),
        state_penalty=float(np.clip(-state_coeff, 0.0, 2000.0)),
    )
