import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd
from difflib import SequenceMatcher


ACTIVE_PRIMARY_PATH = Path("CSV_data") / "vehicle_static_details.csv"
ACTIVE_FALLBACK_PATH = Path("CSV_data") / "active_vehicle_details.csv"
BASE_SOLD_PATH = Path("CSV_data") / "sold_cars.csv"
SOLD_ARCHIVE_DIR = Path("CSV_data") / "ai_analysis_ready"


@dataclass
class PriceStats:
    count: int
    median: Optional[float]
    mean: Optional[float]
    minimum: Optional[float]
    maximum: Optional[float]
    variant_match_quality: Optional[float]
    close_count: int
    close_median: Optional[float]
    close_mean: Optional[float]
    close_minimum: Optional[float]
    close_maximum: Optional[float]
    close_average_odometer_diff: Optional[float]


def _parse_numeric(value) -> Optional[float]:
    """
    Convert values like "$12,340" or "12340.0" into floats.
    Returns None when the value cannot be parsed.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text == "?":
        return None
    # Remove common currency formatting while keeping decimal points.
    cleaned = re.sub(r"[^\d.]", "", text)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_text(value: Optional[str]) -> str:
    """
    Lowercase and remove non-alphanumeric characters for robust matching.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _extract_hours_remaining(value: Optional[str]) -> Optional[float]:
    """
    Convert time strings like '1d 4h 22m', '23h 10m', '45m', or '3h 10m10s'
    into the total number of hours remaining.
    Returns None when the string cannot be interpreted as a remaining time.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).lower().strip()
    if not text:
        return None

    # Ignore absolute dates (e.g., "2025-06-26") or statuses.
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        return None
    if any(keyword in text for keyword in ("ended", "sold", "closed")):
        return None

    days = sum(int(match) for match in re.findall(r"(\d+)\s*d", text))
    hours = sum(int(match) for match in re.findall(r"(\d+)\s*h", text))
    minutes = sum(int(match) for match in re.findall(r"(\d+)\s*m", text))
    seconds = sum(int(match) for match in re.findall(r"(\d+)\s*s", text))

    total_seconds = (
        days * 24 * 3600 +
        hours * 3600 +
        minutes * 60 +
        seconds
    )
    if total_seconds == 0:
        return None
    return total_seconds / 3600


def _to_int_or_none(value) -> Optional[int]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        number = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _snake_case(column_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", column_name.lower()).strip("_")


def _parse_odometer(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.]", "", text.replace(",", ""))
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalise_sold_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise differing column names across sold datasets and align key fields.
    """
    df = df.copy()
    rename_map = {_col: _snake_case(_col) for _col in df.columns}
    df.rename(columns=rename_map, inplace=True)

    df.replace("?", pd.NA, inplace=True)

    if "final_price" not in df.columns:
        for candidate in ("price", "hammer_price", "sold_price"):
            if candidate in df.columns:
                df["final_price"] = df[candidate]
                break

    if "final_bids" not in df.columns and "bids" in df.columns:
        df["final_bids"] = df["bids"]

    if "date_sold" not in df.columns and "date" in df.columns:
        df["date_sold"] = df["date"]

    if "odometer_reading" not in df.columns:
        for candidate in (
            "odometer reading",
            "indicated odometer reading",
            "indicated_odometer_reading",
            "indicated odometer",
        ):
            if candidate in df.columns:
                df["odometer_reading"] = df[candidate]
                break

    return df


def _resolve_active_path(csv_path: Optional[Path]) -> Optional[Path]:
    if csv_path is not None and csv_path.exists():
        return csv_path
    for candidate in (ACTIVE_PRIMARY_PATH, ACTIVE_FALLBACK_PATH):
        if candidate.exists():
            return candidate
    return None


def load_active_listings_within_hours(
    csv_path: Optional[Path] = None,
    min_hours: float = 0.0,
    max_hours: Optional[float] = 24.0,
) -> pd.DataFrame:
    """
    Load active vehicle listings and filter them by a window of hours remaining.
    """
    resolved_path = _resolve_active_path(csv_path)
    if resolved_path is None:
        return pd.DataFrame()

    df = pd.read_csv(resolved_path)

    # Ensure consistent casing and status filtering.
    df["status"] = df.get("status", "").astype(str).str.lower().str.strip()
    df = df[df["status"] == "active"].copy()
    if df.empty:
        return df

    df["hours_remaining"] = df["time_remaining_or_date_sold"].apply(_extract_hours_remaining)
    mask = df["hours_remaining"].notna()
    if min_hours is not None:
        mask &= df["hours_remaining"] >= min_hours
    if max_hours is not None:
        mask &= df["hours_remaining"] < max_hours
    df = df[mask].copy()

    if df.empty:
        return df

    df["price_numeric"] = df["price"].apply(_parse_numeric)
    df["year_int"] = df["year"].apply(_to_int_or_none)
    df["make_norm"] = df["make"].apply(_normalize_text)
    df["model_norm"] = df["model"].apply(_normalize_text)
    df["variant_norm"] = df["variant"].apply(_normalize_text)
    if "odometer_reading" in df.columns:
        df["odometer_numeric"] = df["odometer_reading"].apply(_parse_odometer)
    elif "odometer_numeric" not in df.columns:
        df["odometer_numeric"] = None
    return df


def load_active_listings_under_24h(
    csv_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Backwards compatible wrapper for listings with less than 24 hours remaining.
    """
    return load_active_listings_within_hours(
        csv_path=csv_path,
        min_hours=0.0,
        max_hours=24.0,
    )


def _load_additional_sold_files(directory: Path) -> List[Path]:
    """
    Return a list of CSV file paths inside the provided directory.
    """
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(directory.glob("*.csv"))


def load_historical_sales(
    base_csv: Path = BASE_SOLD_PATH,
    extra_sources: Optional[Iterable[Path]] = None,
) -> pd.DataFrame:
    """
    Load sold vehicle records from the primary CSV and any supplementary CSV files.
    """
    dataframes: List[pd.DataFrame] = []

    if base_csv.exists():
        dataframes.append(_normalise_sold_dataframe(pd.read_csv(base_csv)))

    if extra_sources is None:
        extra_sources = _load_additional_sold_files(SOLD_ARCHIVE_DIR)

    for source in extra_sources:
        try:
            normalised = _normalise_sold_dataframe(pd.read_csv(source))
            dataframes.append(normalised)
        except Exception:
            continue

    if not dataframes:
        return pd.DataFrame()

    sold_df = pd.concat(dataframes, ignore_index=True, sort=False)

    price_columns = [
        column
        for column in ("final_price", "price", "sold_price", "hammer_price")
        if column in sold_df.columns
    ]

    if not price_columns:
        return pd.DataFrame()

    # Prefer dedicated sale price fields but fall back to raw price columns when needed.
    final_price_numeric = sold_df[price_columns[0]].apply(_parse_numeric)
    for column in price_columns[1:]:
        parsed = sold_df[column].apply(_parse_numeric)
        final_price_numeric = final_price_numeric.fillna(parsed)
    sold_df["final_price_numeric"] = final_price_numeric
    sold_df["year_int"] = sold_df["year"].apply(_to_int_or_none)
    sold_df["make_norm"] = sold_df["make"].apply(_normalize_text)
    sold_df["model_norm"] = sold_df["model"].apply(_normalize_text)
    sold_df["variant_norm"] = sold_df["variant"].apply(_normalize_text)
    if "odometer_reading" in sold_df.columns:
        sold_df["odometer_numeric"] = sold_df["odometer_reading"].apply(_parse_odometer)
    else:
        sold_df["odometer_numeric"] = None
    sold_df = sold_df[sold_df["final_price_numeric"].notna()]

    return sold_df


def _variant_similarity(active_variant: str, sold_variant: str) -> float:
    """
    Compute a similarity ratio between two normalised variant strings.
    """
    if not active_variant and not sold_variant:
        return 1.0
    if not active_variant or not sold_variant:
        return 0.0
    return SequenceMatcher(None, active_variant, sold_variant).ratio()


def _score_matches(active_row: pd.Series, candidate_df: pd.DataFrame) -> pd.DataFrame:
    """
    Attach a variant similarity score to candidate matches.
    """
    candidate_df = candidate_df.copy()
    active_variant = active_row.get("variant_norm", "")
    candidate_df["variant_score"] = candidate_df["variant_norm"].apply(
        lambda variant: _variant_similarity(active_variant, variant)
    )
    return candidate_df


def _select_relevant_matches(candidate_df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep the most relevant matches, preferring strong variant similarity.
    """
    if candidate_df.empty:
        return candidate_df

    strong_matches = candidate_df[candidate_df["variant_score"] >= 0.5]
    if not strong_matches.empty:
        return strong_matches

    # Fall back to the top few closest matches when no strong matches exist.
    return candidate_df.nlargest(5, "variant_score")


def _summarise_prices(matches: pd.DataFrame, active_odometer: Optional[float]) -> tuple[PriceStats, pd.DataFrame]:
    """
    Produce summary statistics for the supplied matches and select close odometer comps.
    Returns tuple of PriceStats and DataFrame of close matches (may include odometer_diff column).
    """
    if matches.empty:
        empty_stats = PriceStats(
            count=0,
            median=None,
            mean=None,
            minimum=None,
            maximum=None,
            variant_match_quality=None,
            close_count=0,
            close_median=None,
            close_mean=None,
            close_minimum=None,
            close_maximum=None,
            close_average_odometer_diff=None,
        )
        return empty_stats, matches.copy()

    prices = matches["final_price_numeric"]

    if active_odometer is not None:
        with_odometer = matches.dropna(subset=["odometer_numeric"]).copy()
        if not with_odometer.empty:
            with_odometer["odometer_diff"] = (with_odometer["odometer_numeric"] - active_odometer).abs()
            close_matches = with_odometer.nsmallest(5, "odometer_diff")
        else:
            close_matches = matches.copy()
            close_matches["odometer_diff"] = None
    else:
        close_matches = matches.copy()
        close_matches["odometer_diff"] = None

    close_prices = close_matches["final_price_numeric"]
    close_diffs = close_matches["odometer_diff"].dropna()

    close_count = int(len(close_matches))
    close_median = float(close_prices.median()) if not close_prices.empty else None
    close_mean = float(close_prices.mean()) if not close_prices.empty else None
    close_min = float(close_prices.min()) if not close_prices.empty else None
    close_max = float(close_prices.max()) if not close_prices.empty else None
    close_avg_diff = float(close_diffs.mean()) if not close_diffs.empty else None

    stats = PriceStats(
        count=int(len(matches)),
        median=float(prices.median()),
        mean=float(prices.mean()),
        minimum=float(prices.min()),
        maximum=float(prices.max()),
        variant_match_quality=float(matches["variant_score"].mean()),
        close_count=close_count,
        close_median=close_median,
        close_mean=close_mean,
        close_minimum=close_min,
        close_maximum=close_max,
        close_average_odometer_diff=close_avg_diff,
    )
    return stats, close_matches


def compare_active_to_history(
    active_df: pd.DataFrame,
    sold_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compare active listings to historical sales and calculate pricing gaps.
    Returns a dataframe with summary statistics per active listing.
    """
    if active_df.empty:
        return pd.DataFrame()

    if sold_df.empty:
        result = active_df.copy()
        result = result.assign(
            historical_data_status="No historical data available",
            historical_match_count=0,
            historical_price_median=None,
            historical_price_mean=None,
            historical_price_min=None,
            historical_price_max=None,
            variant_match_quality=None,
            price_vs_median=None,
            median_discount=None,
            priced_below_history=None,
            historical_close_match_count=0,
            historical_close_price_median=None,
            historical_close_price_mean=None,
            historical_close_price_min=None,
            historical_close_price_max=None,
            historical_close_avg_odometer_diff=None,
            price_vs_close_median=None,
            close_median_discount=None,
            priced_below_close_history=None,
            historical_matches_rows=None,
            historical_close_matches_rows=None,
        )
        if "price_numeric" in result.columns:
            result["current_price"] = result["price_numeric"]
        elif "price" in result.columns:
            result["current_price"] = result["price"].apply(_parse_numeric)
        else:
            result["current_price"] = None

        if "hours_remaining" not in result.columns:
            result["hours_remaining"] = None
        if "odometer_numeric" not in result.columns and "odometer_reading" in result.columns:
            result["odometer_numeric"] = result["odometer_reading"].apply(_parse_odometer)
        elif "odometer_numeric" not in result.columns:
            result["odometer_numeric"] = None

        return result

    summaries = []

    for _, active_row in active_df.iterrows():
        make = active_row.get("make_norm", "")
        model = active_row.get("model_norm", "")
        year = active_row.get("year_int")

        initial_candidates = sold_df[
            (sold_df["make_norm"] == make) &
            (sold_df["model_norm"] == model)
        ]

        # Prefer exact year matches when possible.
        if year is not None:
            year_matches = initial_candidates[initial_candidates["year_int"] == year]
            if not year_matches.empty:
                initial_candidates = year_matches

        # Enforce key attribute alignment before scoring to avoid mismatched trims (e.g. hybrids vs non-hybrids).
        active_variant_norm = active_row.get("variant_norm", "") or ""
        active_variant_norm = str(active_variant_norm)
        if active_variant_norm:
            contains_hybrid = "hybrid" in active_variant_norm
            mask = initial_candidates["variant_norm"].astype(str).str.contains("hybrid", na=False)
            if contains_hybrid:
                initial_candidates = initial_candidates[mask]
            else:
                initial_candidates = initial_candidates[~mask]

        def _norm(value: object) -> str:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return ""
            return str(value).lower().strip()

        if "transmission" in initial_candidates.columns:
            active_transmission = _norm(active_row.get("transmission"))
            if active_transmission:
                trans_series = (
                    initial_candidates["transmission"].astype(str).str.lower().str.strip()
                )
                initial_candidates = initial_candidates[trans_series == active_transmission]

        if "fuel_type" in initial_candidates.columns:
            active_fuel = _norm(active_row.get("fuel_type"))
            if active_fuel:
                fuel_series = (
                    initial_candidates["fuel_type"].astype(str).str.lower().str.strip()
                )
                initial_candidates = initial_candidates[fuel_series == active_fuel]

        scored_matches = _score_matches(active_row, initial_candidates)
        selected_matches = _select_relevant_matches(scored_matches)
        active_odometer = active_row.get("odometer_numeric")
        stats, close_matches = _summarise_prices(selected_matches, active_odometer)

        historical_rows = _prepare_match_rows(selected_matches, include_diff=False, limit=15)
        close_rows = _prepare_match_rows(close_matches, include_diff=True, limit=10)

        price_numeric = active_row.get("price_numeric")
        delta_to_median = None
        discount_vs_median = None
        priced_below_history = None
        close_delta = None
        close_discount = None
        priced_below_close = None

        if price_numeric is not None and stats.median is not None:
            delta_to_median = price_numeric - stats.median
            discount_vs_median = stats.median - price_numeric
            priced_below_history = price_numeric < stats.median

        if price_numeric is not None and stats.close_median is not None:
            close_delta = price_numeric - stats.close_median
            close_discount = stats.close_median - price_numeric
            priced_below_close = price_numeric < stats.close_median

        summaries.append({
            "year": active_row.get("year_int"),
            "make": active_row.get("make"),
            "model": active_row.get("model"),
            "variant": active_row.get("variant"),
            "transmission": active_row.get("transmission"),
            "bids": active_row.get("bids"),
            "raw_price": active_row.get("price"),
            "no_of_plates": active_row.get("no_of_plates"),
            "general_condition": active_row.get("general_condition"),
            "features_list": active_row.get("features_list"),
            "url": active_row.get("url"),
            "location": active_row.get("location"),
            "odometer_reading": active_row.get("odometer_reading"),
            "odometer_unit": active_row.get("odometer_unit"),
            "current_price": price_numeric,
            "time_remaining_or_date_sold": active_row.get("time_remaining_or_date_sold"),
            "hours_remaining": active_row.get("hours_remaining"),
            "odometer_numeric": active_odometer,
            "historical_match_count": stats.count,
            "historical_price_median": stats.median,
            "historical_price_mean": stats.mean,
            "historical_price_min": stats.minimum,
            "historical_price_max": stats.maximum,
            "variant_match_quality": stats.variant_match_quality,
            "price_vs_median": delta_to_median,
            "median_discount": discount_vs_median,
            "priced_below_history": priced_below_history,
            "historical_close_match_count": stats.close_count,
            "historical_close_price_median": stats.close_median,
            "historical_close_price_mean": stats.close_mean,
            "historical_close_price_min": stats.close_minimum,
            "historical_close_price_max": stats.close_maximum,
            "historical_close_avg_odometer_diff": stats.close_average_odometer_diff,
            "price_vs_close_median": close_delta,
            "close_median_discount": close_discount,
            "priced_below_close_history": priced_below_close,
            "historical_matches_rows": historical_rows,
            "historical_close_matches_rows": close_rows,
            "historical_data_status": (
                "No historical data available" if stats.count == 0 else "Matched"
            ),
        })

    return pd.DataFrame(summaries)
def _prepare_match_rows(df: pd.DataFrame, include_diff: bool = False, limit: int = 15) -> list[dict]:
    if df is None or df.empty:
        return []
    display_columns = [
        "year",
        "make",
        "model",
        "variant",
        "transmission",
        "odometer_reading",
        "final_price_numeric",
        "date_sold",
        "location",
    ]
    if include_diff and "odometer_diff" in df.columns:
        display_columns.append("odometer_diff")

    subset = df.copy()
    for column in display_columns:
        if column not in subset.columns:
            subset[column] = None

    if "odometer_reading" not in subset.columns and "odometer_numeric" in subset.columns:
        subset["odometer_reading"] = subset["odometer_numeric"]

    subset = subset[display_columns].head(limit).copy()

    def format_price(val):
        if pd.isna(val):
            return "—"
        try:
            return f"${float(val):,.0f}"
        except Exception:
            return str(val)

    def format_odometer(val):
        if pd.isna(val):
            return "—"
        try:
            return f"{int(round(float(val))):,} km"
        except Exception:
            text = str(val).strip()
            if not text:
                return "—"
            return text if text.lower().endswith("km") else f"{text} km"

    if "final_price_numeric" in subset.columns:
        subset["final_price_numeric"] = subset["final_price_numeric"].apply(format_price)

    if "odometer_reading" in subset.columns:
        subset["odometer_reading"] = subset["odometer_reading"].apply(format_odometer)

    if include_diff and "odometer_diff" in subset.columns:
        subset["odometer_diff"] = subset["odometer_diff"].apply(format_odometer)

    rename_map = {
        "year": "Year",
        "make": "Make",
        "model": "Model",
        "variant": "Variant",
        "transmission": "Transmission",
        "odometer_reading": "Odometer",
        "final_price_numeric": "Price",
        "date_sold": "Date Sold",
        "location": "Location",
        "odometer_diff": "Odo Diff",
    }
    subset = subset.rename(columns=rename_map)

    preferred_order = [
        "Year",
        "Make",
        "Model",
        "Variant",
        "Transmission",
        "Odometer",
        "Price",
        "Date Sold",
        "Location",
    ]
    if include_diff and "Odo Diff" in subset.columns:
        preferred_order.append("Odo Diff")

    subset = subset[[col for col in preferred_order if col in subset.columns]]

    return subset.to_dict(orient="records")
