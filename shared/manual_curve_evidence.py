from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from shared.data_loader import dataset_path


MANUAL_CURVE_EVIDENCE_PATH = dataset_path("quality/manual_curve_evidence.csv")
MANUAL_CURVE_EVIDENCE_COLUMNS: Sequence[str] = (
    "base_curve_tag",
    "source",
    "year",
    "variant",
    "price",
    "km",
    "engine",
    "body_type",
    "transmission",
    "fuel_type",
    "location",
    "notes",
)


def load_manual_curve_evidence(path: Path | None = None) -> pd.DataFrame:
    csv_path = path or MANUAL_CURVE_EVIDENCE_PATH
    if not csv_path.exists():
        return pd.DataFrame(columns=list(MANUAL_CURVE_EVIDENCE_COLUMNS))
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=list(MANUAL_CURVE_EVIDENCE_COLUMNS))
    for column in MANUAL_CURVE_EVIDENCE_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    for column in ["base_curve_tag", "source", "variant", "engine", "body_type", "transmission", "fuel_type", "location", "notes"]:
        df[column] = df[column].fillna("").astype(str).str.strip()
    for column in ["year", "price", "km"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df[list(MANUAL_CURVE_EVIDENCE_COLUMNS)].copy()


def prepare_manual_curve_evidence(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    working = df.copy()
    working["year_numeric"] = pd.to_numeric(working["year"], errors="coerce")
    working["price_numeric"] = pd.to_numeric(working["price"], errors="coerce")
    working["odometer_numeric"] = pd.to_numeric(working["km"], errors="coerce")
    working["canonical_tag"] = working["base_curve_tag"].fillna("").astype(str).str.strip()
    working["source_type"] = "carsales_manual"
    working = working.dropna(subset=["year_numeric", "price_numeric", "odometer_numeric"]).copy()
    return working
