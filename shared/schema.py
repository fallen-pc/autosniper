"""Central definitions for dataset schemas."""

from __future__ import annotations

# Final column order for the cleaned sold cars dataset.
SOLD_LISTING_SCHEMA: list[str] = [
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "transmission",
    "fuel_type",
    "odometer_reading",
    "no_of_seats",
    "vin",
    "rego_no",
    "rego_expiry",
    "no_of_cylinders",
    "engine_capacity",
    "exterior_colour",
    "interior_colour",
    "key",
    "spare_key",
    "owners_manual",
    "service_history",
    "engine_turns_over",
    "location",
    "url",
    "general_condition",
    "bids",
    "price",
    "date_sold",
]

# Raw scrape output columns (keeps fields required for cleaning).
SOLD_RAW_SCRAPE_COLUMNS: list[str] = list(
    dict.fromkeys(
        SOLD_LISTING_SCHEMA
        + [
            "build_date",
            "compliance_date",
            "status",
            "rego_state",
            "no_of_plates",
            "odometer_unit",
            "time_remaining_or_date_sold",
            "features_list",
        ]
    )
)

# Static scrape schema (base spec without dynamic bidding columns).
STATIC_VEHICLE_SCHEMA: list[str] = [
    column for column in SOLD_LISTING_SCHEMA if column not in {"bids", "price", "date_sold"}
]

# Static detail export enriched with canonical tagging metadata.
STATIC_CANONICAL_SCHEMA: list[str] = list(
    dict.fromkeys(STATIC_VEHICLE_SCHEMA + ["canonical_tag", "canonical_reason"])
)

# Active listings schema keeps the static fields plus dynamic auction data.
ACTIVE_LISTING_SCHEMA: list[str] = list(dict.fromkeys(STATIC_VEHICLE_SCHEMA + ["bids", "price", "date_sold"]))

# Full active dataset persisted by update_master.py.
ACTIVE_DETAIL_SCHEMA: list[str] = list(
    dict.fromkeys(
        ["url"]
        + [column for column in STATIC_CANONICAL_SCHEMA if column != "url"]
        + ["status", "price", "bids", "time_remaining_or_date_sold", "date_sold"]
    )
)

# Full referred dataset persisted by update_master.py.
REFERRED_LISTING_SCHEMA: list[str] = [
    "year",
    "make",
    "model",
    "variant",
    "body_type",
    "no_of_seats",
    "build_date",
    "compliance_date",
    "vin",
    "rego_no",
    "rego_state",
    "rego_expiry",
    "no_of_plates",
    "no_of_cylinders",
    "engine_capacity",
    "fuel_type",
    "transmission",
    "odometer_reading",
    "odometer_unit",
    "exterior_colour",
    "interior_colour",
    "key",
    "spare_key",
    "owners_manual",
    "service_history",
    "engine_turns_over",
    "location",
    "url",
    "general_condition",
    "features_list",
    "bids",
    "price",
    "time_remaining_or_date_sold",
    "referral_reason",
    "status",
    "canonical_tag",
    "canonical_reason",
]

# Values in the make column that should be discarded entirely (e.g., compliance markers).
DISALLOWED_MAKE_VALUES = {"(comp)", "comp"}
# Regex patterns (case-insensitive) identifying make values to drop (e.g., "(2012" or "(2012)").
DISALLOWED_MAKE_PATTERNS = (
    r"\(\d{4}",
    r"\(wovr-?\s*inspected",
    r"\(wovr-?\s*repairable",
)

# Append-only discovery ledger schema (identity discovery, not runtime state).
DISCOVERY_LEDGER_SCHEMA: list[str] = [
    "url",
    "discovered_at",
    "source",
    "discovery_run_id",
]

# URL-keyed listing lifecycle state table schema.
STATE_TABLE_SCHEMA: list[str] = [
    "url",
    "state",
    "current_price",
    "final_sale_price",
    "final_sale_date",
    "sale_price_source",
    "bid_count",
    "time_remaining",
    "last_seen_at",
    "terminal_reason",
    "state_updated_at",
    "fetch_fail_count",
    "last_fetch_error",
    "last_evidence",
    "run_id",
]

# Ordered lifecycle states for Layer 1.
STATE_DISCOVERED = "discovered"
STATE_STATIC_PARSED = "static_parsed"
STATE_ACTIVE = "active"
STATE_SOLD = "sold"
STATE_WITHDRAWN = "withdrawn"
STATE_REFERRED = "referred"
STATE_DEAD_URL = "dead_url"
STATE_FETCH_FAILED = "fetch_failed"

TERMINAL_STATES = {STATE_SOLD, STATE_WITHDRAWN, STATE_REFERRED, STATE_DEAD_URL}

ALLOWED_LISTING_STATES = {
    STATE_DISCOVERED,
    STATE_STATIC_PARSED,
    STATE_ACTIVE,
    STATE_SOLD,
    STATE_WITHDRAWN,
    STATE_REFERRED,
    STATE_DEAD_URL,
    STATE_FETCH_FAILED,
}

# Audit log for stage-level exclusions/rejections.
PIPELINE_EXCLUSION_SCHEMA: list[str] = [
    "url",
    "reason_code",
    "timestamp",
    "stage",
    "run_id",
    "details",
]
