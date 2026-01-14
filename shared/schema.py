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

# Active listings schema keeps the static fields plus dynamic auction data.
ACTIVE_LISTING_SCHEMA: list[str] = list(dict.fromkeys(STATIC_VEHICLE_SCHEMA + ["bids", "price", "date_sold"]))

# Values in the make column that should be discarded entirely (e.g., compliance markers).
DISALLOWED_MAKE_VALUES = {"(comp)", "comp"}
# Regex patterns (case-insensitive) identifying make values to drop (e.g., "(2012" or "(2012)").
DISALLOWED_MAKE_PATTERNS = (
    r"\(\d{4}",
    r"\(wovr-?\s*inspected",
    r"\(wovr-?\s*repairable",
)
