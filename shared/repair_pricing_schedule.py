from __future__ import annotations

from datetime import date
import logging
import re
from pathlib import Path

import pandas as pd
import yaml

from shared.csv_utils import CSV_READ_ERRORS
from shared.repair_review import (
    DECISIONS_PATH,
    latest_repair_decisions,
    load_repair_review_decisions,
    safe_text,
)

logger = logging.getLogger(__name__)


REPORT_DIR = Path("CSV_data/reports")
DICTIONARY_PATH = Path("config/condition_dictionary_v2.yaml")
PRICING_SCHEDULE_PATH = REPORT_DIR / "repair_pricing_schedule.csv"
QUOTE_REQUESTS_PATH = REPORT_DIR / "repair_quote_requests.csv"

PRICING_COLUMNS = [
    "canonical_defect",
    "category",
    "vehicle_class",
    "pricing_method",
    "default_estimate",
    "low_estimate",
    "high_estimate",
    "confidence",
    "evidence_source",
    "evidence_date",
    "supplier",
    "vehicle_specific",
    "labour_required",
    "notes",
]

QUOTE_COLUMNS = [
    "request_id",
    "canonical_defect",
    "category",
    "vehicle_class",
    "representative_vehicle",
    "supplier",
    "supplier_type",
    "contact_method",
    "status",
    "request_date",
    "response_date",
    "quoted_low",
    "quoted_high",
    "quoted_default",
    "evidence_url",
    "draft_subject",
    "draft_body",
    "notes",
    "recipient_email",
    "last_attempted_date",
    "sent_message_id",
    "sent_thread_id",
    "sent_from",
    "response_source",
    "response_text",
    "response_parse_status",
]

VEHICLE_CLASSES = [
    "small_hatch",
    "small_sedan",
    "medium_suv",
    "large_suv",
    "ute",
    "van",
    "generic",
]

PRICING_METHODS = [
    "repair_quote",
    "wrecker_part_price",
    "parts_supplier_price",
    "parts_plus_labour",
    "internal_default",
]

SUPPLIER_TYPES = [
    "repairer",
    "glass",
    "wrecker",
    "parts_supplier",
    "mechanic",
    "trim_upholstery",
    "tyre_battery",
]

DEFAULT_REPAIR_LOCATION = "Melbourne metro"
DEFAULT_FOLLOWUP_WAIT_DAYS = 3

PART_ONLY_CANONICALS = {
    "battery_issue",
    "mirror_light_damage",
    "lighting_damage",
    "bumper_damage",
    "door_handle_damage",
    "fuel_flap_damage",
    "sunroof_damage",
    "key_missing",
    "tyre_replacement",
    "wheel_missing",
}

SPECIALIST_CANONICALS = {
    "windscreen_damage",
    "window_damage",
    "window_tint_damage",
    "paint_damage",
    "paint_surface_issue",
    "cosmetic_surface_damage",
    "corrosion_damage",
    "hail_damage",
    "seat_damage",
    "seat_issue",
    "interior_trim_damage",
    "control_damage",
}

EXCLUDED_PRICING_CATEGORIES = {"boilerplate"}
EXCLUDED_PRICING_CANONICALS = {
    "body_location_list",
    "replacement_required",
}
EXCLUDED_PRICING_CANONICAL_PREFIXES = ("boilerplate_",)
HARD_AVOID_PRICING_CANONICALS = {
    "abs_warning_light",
    "airbag_light_on",
    "airbag_warning_light",
    "battery_warning_light",
    "brakes_require_attention",
    "car_cranks_but_won_t_start",
    "clutch_requires_attention",
    "does_not_start",
    "driveline_requires_attention",
    "engine_cooling_issue",
    "engine_exhaust_smoke_visible",
    "engine_fault",
    "engine_has_knocking_sound_and_rattling_sound",
    "engine_idling_rough",
    "engine_lacks_power",
    "engine_light_on",
    "engine_mechanical_electrical_issues_does_not_start_on_key",
    "engine_mechanical_not_running",
    "engine_noise_observed",
    "engine_oil_leak",
    "engine_overheating",
    "engine_rattle_noise_observed",
    "engine_rattle_noise_observed_at_idle",
    "engine_rattle_on_cold_start_up",
    "engine_rattles_when_start_up",
    "engine_requires_attention",
    "engine_running_fault",
    "engine_smoke_visible",
    "engine_timing_chain_rattle_noise_observed",
    "engine_water_leak_oserved",
    "epc_warning_light",
    "exterior_vehicle_stalling_at_times",
    "fuel_leak",
    "head_gasket_issue",
    "interior_engine_stalling_in_drive_and_reverse",
    "oil_mixed_with_engine_coolant",
    "other_warning_light",
    "push_button_does_not_start_vehicle",
    "rear_diff_bush_needs_replacing",
    "service_warning_light",
    "slight_engine_rattle",
    "steering_requires_attention",
    "structural_damage",
    "suspension_requires_attention",
    "tow_or_no_drive_required",
    "traction_control_warning_light",
    "transmission_fault",
    "transmission_requires_attention",
    "tyre_pressure_warning_light",
    "vehicle_cannot_be_driven_off_site",
    "vehicle_does_not_start",
    "vehicle_stalls_randomly",
    "warning_light",
    "worn_diff_bushes",
}
HARD_AVOID_PRICING_KEYWORDS = (
    "cannot_be_driven",
    "coolant",
    "cooling",
    "diff_",
    "does_not_start",
    "driveline",
    "engine_",
    "frame",
    "fuel_leak",
    "gearbox",
    "head_gasket",
    "not_running",
    "oil_leak",
    "oil_mixed",
    "rear_diff",
    "stall",
    "structural",
    "tilt_tray",
    "tow",
    "transmission",
    "water_leak",
    "won_t_start",
    "worn_diff",
)
CATEGORY_OVERRIDES = {
    "battery_issue": "replacement",
}


def is_hard_avoid_pricing_candidate(canonical_defect: object) -> bool:
    canonical = safe_text(canonical_defect)
    if not canonical:
        return False
    if canonical in HARD_AVOID_PRICING_CANONICALS:
        return True
    return any(keyword in canonical for keyword in HARD_AVOID_PRICING_KEYWORDS)


def _blank_pricing_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=PRICING_COLUMNS)


def _blank_quote_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=QUOTE_COLUMNS)


def load_pricing_schedule(path: Path = PRICING_SCHEDULE_PATH) -> pd.DataFrame:
    if not path.exists():
        return _blank_pricing_frame()
    try:
        df = pd.read_csv(path).fillna("")
    except CSV_READ_ERRORS as exc:
        logger.warning(
            "Unreadable pricing schedule %s (%s: %s); starting from a blank schedule.",
            path,
            type(exc).__name__,
            exc,
        )
        return _blank_pricing_frame()
    for column in PRICING_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[PRICING_COLUMNS]


def validate_pricing_schedule(df: pd.DataFrame) -> list[str]:
    """Validate quote-backed schedule rows before replacing the live file."""
    out = df.copy()
    for column in PRICING_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    errors: list[str] = []
    keys = out[["canonical_defect", "vehicle_class"]].fillna("").astype(str).apply(lambda col: col.str.strip())
    duplicate_mask = keys.duplicated(keep=False)
    if duplicate_mask.any():
        duplicate_keys = sorted(
            f"{row.canonical_defect}|{row.vehicle_class}"
            for row in keys.loc[duplicate_mask].drop_duplicates().itertuples(index=False)
        )
        errors.append(f"Duplicate canonical defect/vehicle class rows: {', '.join(duplicate_keys)}")
    invalid_classes = sorted(set(keys.loc[~keys["vehicle_class"].isin(VEHICLE_CLASSES), "vehicle_class"]) - {""})
    if invalid_classes:
        errors.append(f"Unsupported vehicle classes: {', '.join(invalid_classes)}")
    for index, row in out.iterrows():
        canonical = safe_text(row.get("canonical_defect"))
        vehicle_class = safe_text(row.get("vehicle_class"))
        row_label = f"row {index + 2} ({canonical or 'blank'}|{vehicle_class or 'blank'})"
        if not canonical:
            errors.append(f"{row_label}: canonical_defect is required")
        if vehicle_class not in VEHICLE_CLASSES:
            errors.append(f"{row_label}: vehicle_class must use the governed class list")
        try:
            low = float(row.get("low_estimate"))
            default = float(row.get("default_estimate"))
            high = float(row.get("high_estimate"))
        except (TypeError, ValueError):
            errors.append(f"{row_label}: low/default/high estimates must be numeric")
            continue
        if not (0 < low <= default <= high):
            errors.append(f"{row_label}: estimates must satisfy 0 < low <= default <= high")
        if not safe_text(row.get("evidence_source")):
            errors.append(f"{row_label}: evidence_source is required; do not invent class multipliers")
    return errors


def save_pricing_schedule(df: pd.DataFrame, path: Path = PRICING_SCHEDULE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for column in PRICING_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    errors = validate_pricing_schedule(out)
    if errors:
        raise ValueError("Invalid repair pricing schedule: " + "; ".join(errors))
    out[PRICING_COLUMNS].to_csv(path, index=False)


def load_quote_requests(path: Path = QUOTE_REQUESTS_PATH) -> pd.DataFrame:
    if not path.exists():
        return _blank_quote_frame()
    try:
        df = pd.read_csv(path).fillna("")
    except CSV_READ_ERRORS as exc:
        logger.warning(
            "Unreadable quote requests %s (%s: %s); starting from a blank quote list.",
            path,
            type(exc).__name__,
            exc,
        )
        return _blank_quote_frame()
    for column in QUOTE_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[QUOTE_COLUMNS]


def save_quote_requests(df: pd.DataFrame, path: Path = QUOTE_REQUESTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for column in QUOTE_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    out[QUOTE_COLUMNS].to_csv(path, index=False)


def humanize_canonical_defect(canonical_defect: object) -> str:
    text = safe_text(canonical_defect).replace("_", " ").strip()
    return re.sub(r"\s+", " ", text)


def build_quote_request_subject(canonical_defect: object) -> str:
    item = humanize_canonical_defect(canonical_defect) or "repair job"
    return f"Price request - {item}"


def build_quote_request_body(
    canonical_defect: object,
    representative_vehicle: object,
    request_notes: object = "",
    *,
    location: object = DEFAULT_REPAIR_LOCATION,
) -> str:
    item = humanize_canonical_defect(canonical_defect) or "repair"
    vehicle = safe_text(representative_vehicle) or "my vehicle"
    job = safe_text(request_notes) or item
    place = safe_text(location)
    location_line = f"\nLocation: {place}" if place else ""
    return (
        "Hi,\n\n"
        "Could you please give me a price for this repair?\n\n"
        f"Vehicle: {vehicle}\n"
        f"Job: {job}"
        f"{location_line}\n\n"
        "If the final price depends on photos or inspection, a typical price and likely low/high range is fine.\n\n"
        "Thanks,\n"
        "Ewan"
    )


def build_quote_followup_body(
    row: pd.Series | dict[str, object],
    *,
    sender_name: object = "Ewan",
) -> str:
    canonical = safe_text(row.get("canonical_defect")) if hasattr(row, "get") else ""
    item = humanize_canonical_defect(canonical) or "repair"
    vehicle = safe_text(row.get("representative_vehicle")) if hasattr(row, "get") else ""
    job = safe_text(row.get("draft_body")) if hasattr(row, "get") else ""
    job_line = _extract_email_field(job, "Job")
    if not job_line:
        job_line = _job_from_request_notes(row)
    location_line = _extract_email_field(job, "Location")
    vehicle_line = vehicle or _extract_email_field(job, "Vehicle")
    greeting_name = safe_text(sender_name) or "Ewan"

    details = []
    if vehicle_line:
        details.append(f"Vehicle: {vehicle_line}")
    if job_line:
        details.append(f"Job: {job_line}")
    else:
        details.append(f"Job: {item}")
    if location_line:
        details.append(f"Location: {location_line}")

    detail_block = "\n".join(details)
    return (
        "Hi,\n\n"
        "Just following up on this price request.\n\n"
        f"{detail_block}\n\n"
        "A rough typical price and likely low/high range is fine if the final quote depends on photos or inspection.\n\n"
        "Thanks,\n"
        f"{greeting_name}"
    )


def overdue_quote_followup_candidates(
    quotes: pd.DataFrame,
    *,
    today: date | str | None = None,
    min_days_waiting: int = DEFAULT_FOLLOWUP_WAIT_DAYS,
) -> pd.DataFrame:
    if quotes.empty:
        return quotes.copy()
    current = _coerce_date(today) or date.today()
    out = quotes.copy().fillna("")
    for column in QUOTE_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    sent = out["status"].map(safe_text).isin({"sent", "waiting"})
    gmail = out["contact_method"].map(safe_text).eq("gmail")
    has_recipient = out["recipient_email"].map(safe_text) != ""
    has_thread = out["sent_thread_id"].map(safe_text) != ""
    request_dates = out["request_date"].map(_coerce_date)
    old_enough = request_dates.map(lambda value: value is not None and (current - value).days >= min_days_waiting)
    return out[sent & gmail & has_recipient & has_thread & old_enough & ~out.apply(should_skip_quote_followup, axis=1)][
        QUOTE_COLUMNS
    ]


def should_skip_quote_followup(row: pd.Series | dict[str, object]) -> bool:
    status = safe_text(row.get("status")) if hasattr(row, "get") else ""
    if status in {"priced", "no_quote", "superseded"}:
        return True

    combined = " ".join(
        safe_text(row.get(column))
        for column in ["notes", "response_text", "response_parse_status", "response_source"]
        if hasattr(row, "get")
    ).lower()
    if any(term in combined for term in ["photo", "inspection", "tyre size", "tire size", "no_price_found"]):
        return True
    return has_followup_marker(row)


def has_followup_marker(row: pd.Series | dict[str, object]) -> bool:
    if not hasattr(row, "get"):
        return False
    last_attempted = safe_text(row.get("last_attempted_date"))
    request_date = safe_text(row.get("request_date"))
    if last_attempted and last_attempted != request_date:
        return True
    notes = safe_text(row.get("notes")).lower()
    return "follow-up sent" in notes or "follow-up draft" in notes or "follow up sent" in notes


def parse_quote_response(text: object) -> dict[str, object]:
    body = safe_text(text)
    amounts = _extract_money_amounts(body)
    if not amounts:
        return {
            "quoted_low": "",
            "quoted_high": "",
            "quoted_default": "",
            "response_parse_status": "no_price_found",
        }

    low = min(amounts)
    high = max(amounts)
    default = _extract_default_amount(body, amounts)
    if default is None:
        default = round((low + high) / 2)

    return {
        "quoted_low": int(low),
        "quoted_high": int(high),
        "quoted_default": int(default),
        "response_parse_status": "parsed_price",
    }


def apply_quote_response(
    quotes: pd.DataFrame,
    request_id: object,
    response_text: object,
    *,
    response_date: object = "",
    response_source: object = "gmail",
) -> pd.DataFrame:
    out = quotes.copy().fillna("")
    for column in QUOTE_COLUMNS:
        if column not in out.columns:
            out[column] = ""
    for column in ("quoted_low", "quoted_high", "quoted_default"):
        out[column] = out[column].astype(object)
    request = safe_text(request_id)
    mask = out["request_id"].map(safe_text) == request
    if not mask.any():
        return out[QUOTE_COLUMNS]

    parsed = parse_quote_response(response_text)
    out.loc[mask, "response_text"] = safe_text(response_text)
    out.loc[mask, "response_source"] = safe_text(response_source)
    out.loc[mask, "response_parse_status"] = safe_text(parsed.get("response_parse_status"))
    out.loc[mask, "status"] = "replied"
    if safe_text(response_date):
        out.loc[mask, "response_date"] = safe_text(response_date)
    for column in ["quoted_low", "quoted_high", "quoted_default"]:
        if safe_text(parsed.get(column)):
            out.loc[mask, column] = parsed[column]
    return out[QUOTE_COLUMNS]


def pricing_row_from_quote(quotes: pd.DataFrame, request_id: object) -> dict[str, object] | None:
    request = safe_text(request_id)
    if quotes.empty or not request:
        return None
    source = quotes.copy()
    source = source.where(pd.notna(source), "")
    row_df = source[source["request_id"].map(safe_text) == request]
    if row_df.empty:
        return None
    row = row_df.iloc[0]
    if not safe_text(row.get("quoted_default")):
        return None
    supplier = safe_text(row.get("supplier")) or safe_text(row.get("recipient_email")) or "quote response"
    return {
        "canonical_defect": safe_text(row.get("canonical_defect")),
        "category": safe_text(row.get("category")),
        "vehicle_class": safe_text(row.get("vehicle_class")) or "generic",
        "pricing_method": "repair_quote",
        "default_estimate": row.get("quoted_default"),
        "low_estimate": row.get("quoted_low"),
        "high_estimate": row.get("quoted_high"),
        "confidence": "medium",
        "evidence_source": safe_text(row.get("evidence_url")) or supplier,
        "evidence_date": safe_text(row.get("response_date")) or safe_text(row.get("request_date")),
        "supplier": supplier,
        "vehicle_specific": "yes" if is_vehicle_specific(row.get("canonical_defect")) else "no",
        "labour_required": "yes",
        "notes": f"Imported from quote request {request}. {safe_text(row.get('notes'))}".strip(),
    }


def dictionary_pricing_candidates(path: Path = DICTIONARY_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["canonical_defect", "category", "examples", "decision_count"])
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning(
            "Unreadable condition dictionary %s (%s: %s); no pricing candidates derived.",
            path,
            type(exc).__name__,
            exc,
        )
        return pd.DataFrame(columns=["canonical_defect", "category", "examples", "decision_count"])

    rows: list[dict[str, object]] = []
    for entry in payload.get("entries", []) or []:
        canonical = safe_text(entry.get("canonical_defect"))
        category = safe_text(entry.get("category")) or "unknown"
        if not canonical or category in EXCLUDED_PRICING_CATEGORIES:
            continue
        if canonical in EXCLUDED_PRICING_CANONICALS:
            continue
        if is_hard_avoid_pricing_candidate(canonical):
            continue
        if canonical.startswith(EXCLUDED_PRICING_CANONICAL_PREFIXES):
            continue
        rows.append(
            {
                "canonical_defect": canonical,
                "category": category,
                "examples": safe_text(entry.get("pattern")),
                "decision_count": 0,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["canonical_defect", "category", "examples", "decision_count"])
    df = pd.DataFrame(rows)
    return (
        df.groupby("canonical_defect", as_index=False)
        .agg(
            category=("category", lambda values: _most_common(values, "unknown")),
            examples=("examples", lambda values: " | ".join(_unique_limited(values, 3))),
            decision_count=("decision_count", "sum"),
        )
        .sort_values("canonical_defect")
    )


def reviewed_pricing_candidates(decisions: pd.DataFrame | None = None) -> pd.DataFrame:
    source = load_repair_review_decisions(DECISIONS_PATH) if decisions is None else decisions
    source = latest_repair_decisions(source)
    if source.empty:
        return pd.DataFrame(columns=["canonical_defect", "category", "examples", "decision_count"])
    rows = source[source["decision"] == "Add dictionary rule"].copy()
    rows["canonical_defect"] = rows["canonical_defect"].map(safe_text)
    rows = rows[rows["canonical_defect"] != ""]
    rows = rows[~rows["canonical_defect"].isin(EXCLUDED_PRICING_CANONICALS)]
    rows = rows[~rows["canonical_defect"].map(is_hard_avoid_pricing_candidate)]
    if rows.empty:
        return pd.DataFrame(columns=["canonical_defect", "category", "examples", "decision_count"])
    grouped = (
        rows.groupby("canonical_defect", as_index=False)
        .agg(
            category=("target_category", lambda values: _most_common(values, "unknown")),
            examples=("repair_item", lambda values: " | ".join(_unique_limited(values, 4))),
            decision_count=("repair_key", "count"),
        )
        .sort_values(["decision_count", "canonical_defect"], ascending=[False, True])
    )
    return grouped


def canonical_pricing_candidates(decisions: pd.DataFrame | None = None) -> pd.DataFrame:
    reviewed = reviewed_pricing_candidates(decisions)
    dictionary = dictionary_pricing_candidates()
    frames = [df for df in [reviewed, dictionary] if not df.empty]
    if not frames:
        return pd.DataFrame(columns=["canonical_defect", "category", "examples", "decision_count"])
    combined = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    grouped = (
        combined.groupby("canonical_defect", as_index=False)
        .agg(
            category=("category", lambda values: _most_common(values, "unknown")),
            examples=("examples", lambda values: " | ".join(_unique_limited(values, 4))),
            decision_count=("decision_count", "sum"),
        )
        .sort_values(["decision_count", "canonical_defect"], ascending=[False, True])
    )
    grouped["category"] = grouped.apply(
        lambda row: CATEGORY_OVERRIDES.get(safe_text(row.get("canonical_defect")), safe_text(row.get("category"))),
        axis=1,
    )
    return grouped


# Real vehicle classes infer_vehicle_class() can actually produce. "large_suv" and
# "generic" are valid VEHICLE_CLASSES values but are not body-class buckets a listing
# resolves to, so they are handled separately, not fanned out over.
REAL_VEHICLE_CLASSES = ["small_hatch", "small_sedan", "medium_suv", "ute", "van"]

# cost_model values whose true cost meaningfully differs by vehicle body class - a ute
# panel or an SUV seat is not priced the same as a small hatch's. Confirmed against the
# full 20,406-listing pricing matrix: glass canonicals (windscreen/window/tint) were
# already correctly covered end-to-end by a single generic row (real quote evidence,
# not a guess), so glass is deliberately excluded here rather than fanned out too.
CLASS_VARYING_COST_MODELS = {"cosmetic_panel", "fixed_replacement"}

# battery_issue's decision-file cost_model is "fixed_replacement" (in
# CLASS_VARYING_COST_MODELS), but this predates that data: an earlier version of this
# module already special-cased it, alongside the glass items, as a single generic
# price - a commodity part where the coarse 5-class body bucket is not how suppliers
# actually quote it, and it already has one successful "generic" quote on record.
# Keeping that call rather than silently overturning it; revisit if evidence says
# otherwise.
SINGLE_PRICE_CANONICALS = {"battery_issue", "windscreen_damage", "window_damage", "window_tint_damage"}

REPAIR_PRICING_MATRIX_PATH = Path("CSV_data") / "model_audit" / "repair_pricing_matrix.csv"


def _cost_model_lookup(decisions: pd.DataFrame | None = None) -> dict[str, str]:
    """canonical_defect -> most common cost_model from repair review decisions."""
    source = load_repair_review_decisions(DECISIONS_PATH) if decisions is None else decisions
    source = latest_repair_decisions(source)
    if source.empty or "cost_model" not in source.columns:
        return {}
    rows = source[source["decision"] == "Add dictionary rule"].copy()
    rows["canonical_defect"] = rows["canonical_defect"].map(safe_text)
    rows["cost_model"] = rows["cost_model"].map(safe_text)
    rows = rows[(rows["canonical_defect"] != "") & (rows["cost_model"] != "")]
    if rows.empty:
        return {}
    grouped = rows.groupby("canonical_defect")["cost_model"].agg(lambda values: _most_common(values, ""))
    return grouped.to_dict()


def _class_priority_order(matrix_path: Path = REPAIR_PRICING_MATRIX_PATH) -> list[str]:
    """Real vehicle classes ranked by how many unpriced listing-hits they carry.

    So the first suggested class to quote is the one that actually moves the needle,
    not an arbitrary fixed order. Falls back to REAL_VEHICLE_CLASSES order if the
    coverage matrix has not been generated yet (build_repair_pricing_matrix.py).
    """
    if matrix_path.exists():
        try:
            matrix = pd.read_csv(matrix_path, usecols=["vehicle_class", "occurrences", "status"])
            missing = matrix[matrix["status"] == "MISSING"]
            ranked = missing.groupby("vehicle_class")["occurrences"].sum().sort_values(ascending=False)
            order = [cls for cls in ranked.index if cls in REAL_VEHICLE_CLASSES]
            order += [cls for cls in REAL_VEHICLE_CLASSES if cls not in order]
            return order
        except Exception:
            pass
    return list(REAL_VEHICLE_CLASSES)


def missing_vehicle_classes_for(
    canonical_defect: object,
    schedule_df: pd.DataFrame,
    *,
    cost_models: dict[str, str] | None = None,
    priority_order: list[str] | None = None,
) -> list[str]:
    """Which real vehicle classes still lack a price for this canonical.

    A canonical whose cost_model does not vary by class (glass, wrecker parts,
    batteries, ...) needs exactly one row, under vehicle_class == "generic" - once
    that exists it is priced for every class, same as the live pricing lookup's
    exact -> generic -> fallback order. A class-varying canonical (cosmetic_panel /
    fixed_replacement) needs a row PER class: a generic or single-class row does
    NOT count as covering the others, because the whole reason it varies is that a
    ute panel and a small hatch panel are not the same repair. Ordered by real-world
    impact via priority_order (see _class_priority_order) so index [0] is the class
    worth quoting next, not just the first alphabetically.
    """
    canonical = safe_text(canonical_defect)
    if not canonical:
        return []

    if "canonical_defect" in schedule_df.columns and not schedule_df.empty:
        rows = schedule_df[schedule_df["canonical_defect"].map(safe_text) == canonical]
    else:
        rows = schedule_df.iloc[0:0]
    priced_classes = set(rows["vehicle_class"].map(safe_text)) if "vehicle_class" in rows.columns else set()
    priced_classes.discard("")

    if canonical in SINGLE_PRICE_CANONICALS:
        varies_by_class = False
    else:
        models = cost_models if cost_models is not None else _cost_model_lookup()
        varies_by_class = models.get(canonical) in CLASS_VARYING_COST_MODELS

    if not varies_by_class:
        # Any existing row counts as priced, not specifically a "generic"-labelled
        # one - matches the original canonical-only check for these items, and keeps
        # a bare canonical_defect-only schedule fixture (no vehicle_class column) a
        # valid "already priced" state rather than a false gap.
        return [] if not rows.empty else ["generic"]

    order = priority_order if priority_order is not None else _class_priority_order()
    return [cls for cls in order if cls not in priced_classes]


def needs_pricing(
    candidates: pd.DataFrame | None = None,
    schedule: pd.DataFrame | None = None,
) -> pd.DataFrame:
    candidate_df = canonical_pricing_candidates() if candidates is None else candidates.copy()
    schedule_df = load_pricing_schedule() if schedule is None else schedule.copy()
    if candidate_df.empty:
        return candidate_df
    candidate_df["category"] = candidate_df.apply(
        lambda row: CATEGORY_OVERRIDES.get(safe_text(row.get("canonical_defect")), safe_text(row.get("category"))),
        axis=1,
    )

    cost_models = _cost_model_lookup()
    priority_order = _class_priority_order()
    candidate_df["missing_vehicle_classes"] = candidate_df["canonical_defect"].map(
        lambda c: missing_vehicle_classes_for(
            c, schedule_df, cost_models=cost_models, priority_order=priority_order
        )
    )

    out = candidate_df[candidate_df["missing_vehicle_classes"].map(len) > 0].copy()
    # First entry is the highest-impact still-missing class (see _class_priority_order),
    # NOT a fixed default - the old suggest_vehicle_class() always suggested small_hatch,
    # which was usually the one class already priced, so it kept steering new quote
    # requests at coverage the schedule already had instead of the gap that mattered.
    out["suggested_vehicle_class"] = out["missing_vehicle_classes"].map(
        lambda classes: classes[0] if classes else "small_hatch"
    )
    out["missing_vehicle_classes_display"] = out["missing_vehicle_classes"].map(", ".join)
    out["suggested_pricing_method"] = out["canonical_defect"].map(suggest_pricing_method)
    out["suggested_supplier_type"] = out["canonical_defect"].map(suggest_supplier_type)
    out["vehicle_specific"] = out["canonical_defect"].map(lambda value: "yes" if is_vehicle_specific(value) else "no")
    return out


def suggest_vehicle_class(canonical_defect: object) -> str:
    key = safe_text(canonical_defect)
    if key in {"battery_issue", "windscreen_damage", "window_damage", "window_tint_damage"}:
        return "generic"
    return "small_hatch"


def is_vehicle_specific(canonical_defect: object) -> bool:
    key = safe_text(canonical_defect)
    return key in PART_ONLY_CANONICALS or key in {"windscreen_damage", "window_damage"}


def suggest_pricing_method(canonical_defect: object) -> str:
    key = safe_text(canonical_defect)
    if key in {"battery_issue", "tyre_replacement", "wheel_missing"}:
        return "parts_supplier_price"
    if key in PART_ONLY_CANONICALS:
        return "wrecker_part_price"
    if key in SPECIALIST_CANONICALS:
        return "repair_quote"
    return "repair_quote"


def suggest_supplier_type(canonical_defect: object) -> str:
    key = safe_text(canonical_defect)
    if key in {"windscreen_damage", "window_damage", "window_tint_damage"}:
        return "glass"
    if key in {"battery_issue", "tyre_replacement", "wheel_missing"}:
        return "tyre_battery"
    if key in PART_ONLY_CANONICALS:
        return "wrecker"
    if key in {"seat_damage", "seat_issue", "interior_trim_damage"}:
        return "trim_upholstery"
    if key in {"paint_damage", "paint_surface_issue", "cosmetic_surface_damage", "corrosion_damage", "hail_damage"}:
        return "repairer"
    return "mechanic"


def next_request_id(existing: pd.DataFrame) -> str:
    if existing.empty or "request_id" not in existing.columns:
        return "RQ-0001"
    max_seen = 0
    for value in existing["request_id"]:
        text = safe_text(value)
        if text.upper().startswith("RQ-"):
            try:
                max_seen = max(max_seen, int(text.split("-", 1)[1]))
            except ValueError:
                continue
    return f"RQ-{max_seen + 1:04d}"


def _most_common(values: object, fallback: str) -> str:
    cleaned = [safe_text(value) for value in values if safe_text(value)]
    if not cleaned:
        return fallback
    return pd.Series(cleaned).mode().iloc[0]


def _unique_limited(values: object, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = safe_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _extract_money_amounts(text: str) -> list[int]:
    values: list[int] = []
    for match in re.finditer(
        r"(?:\$[ \t]*|aud[ \t]+)([0-9][0-9,]*(?:\.\d{1,2})?)"
        r"(?:[ \t]*[-\u2013][ \t]*(?:\$[ \t]*)?([0-9][0-9,]*(?:\.\d{1,2})?))?",
        text,
        flags=re.IGNORECASE,
    ):
        values.append(round(float(match.group(1).replace(",", ""))))
        if match.group(2):
            values.append(round(float(match.group(2).replace(",", ""))))
    for match in re.finditer(
        r"\b([1-9][0-9]{2,4})(?:\.\d{1,2})?\s*(?:dollars|aud)\b",
        text,
        flags=re.IGNORECASE,
    ):
        values.append(round(float(match.group(1).replace(",", ""))))
    return [value for value in values if 20 <= value <= 20000]


def _extract_email_field(body: object, field: str) -> str:
    pattern = rf"^{re.escape(field)}:\s*(.+)$"
    for line in safe_text(body).splitlines():
        match = re.match(pattern, line.strip(), flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _job_from_request_notes(row: pd.Series | dict[str, object]) -> str:
    if not hasattr(row, "get"):
        return ""
    notes = safe_text(row.get("notes"))
    match = re.search(r"(?:asked|ask)\s+[^.]*?\s+for\s+(?:a\s+)?(.+?)(?:\.|$)", notes, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _coerce_date(value: object) -> date | None:
    text = safe_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _extract_default_amount(text: str, amounts: list[int]) -> int | None:
    patterns = [
        r"(?:typical|usually|default|normally|most jobs|ballpark)[^$0-9]{0,40}(?:\$|aud\s*)\s*([0-9][0-9,]*(?:\.\d{1,2})?)",
        r"(?:\$|aud\s*)\s*([0-9][0-9,]*(?:\.\d{1,2})?)[^.\n]{0,40}(?:typical|usually|default|normal|ballpark)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = round(float(match.group(1).replace(",", "")))
            if value in amounts or 20 <= value <= 20000:
                return value
    return None
