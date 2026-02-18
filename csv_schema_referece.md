# AutoSniper2 — CSV Schema Reference
Version: 1.0
Status: Authoritative

This document defines the official dataset schemas used in AutoSniper2.

All CSV files must:
- Match column order exactly.
- Match column names exactly.
- Not introduce silent column additions.
- Be written and read consistently across pipeline layers.

Schema drift is not permitted.

---

# 1️⃣ all_vehicle_links.csv

## Purpose
Stores unique listing URLs discovered by the scraper.

## Layer
Pipeline & Data Integrity

## Columns (Exact Order)

| Column | Type | Description |
|--------|------|------------|
| url | string | Full listing URL (absolute unique identifier) |
| discovered_at | ISO date | Timestamp first seen |

## Invariants
- URL must be unique.
- No duplicates permitted.
- No partial URLs.

---

# 2️⃣ vehicle_static_details.csv

## Purpose
Immutable snapshot of listing attributes at scrape time.

## Layer
Pipeline & Data Integrity

## Key Columns

| Column | Type | Description |
|--------|------|------------|
| url | string | Absolute unique identifier |
| year | integer | Model year |
| make | string | Manufacturer |
| model | string | Model name |
| variant | string | Trim level |
| canonical_tag | string | Curve matching tag |
| body_type | string | Body style |
| transmission | string | Transmission type |
| fuel_type | string | Fuel |
| odometer_reading | integer | KM reading (numeric) |
| vin | string | Vehicle identification number |
| rego_expiry | ISO date | Registration expiry |
| location | string | State / auction location |
| general_condition | string | Raw condition notes |
| status | string | Active / Sold / Expired |

## Invariants
- URL must exist.
- Odometer must be numeric.
- Dates must be ISO.
- canonical_tag must exist before AI runs.

---

# 3️⃣ vehicle_active_details.csv

## Purpose
Dynamic auction state for active vehicles.

## Layer
AI Profit Logic

## Columns

| Column | Type | Description |
|--------|------|------------|
| url | string | Unique identifier |
| current_price | numeric | Current auction price |
| bid_count | integer | Number of bids |
| time_remaining | string | Auction time remaining |
| status | string | Active |

## Invariants
- Withdrawn listings must not exist here.
- Missing final price must not exist here.
- URL must match static file.

---

# 4️⃣ sold_cars.csv

## Purpose
Finalized sold listings.

## Layer
AI Profit Logic

## Columns

| Column | Type | Description |
|--------|------|------------|
| url | string | Unique identifier |
| final_price | numeric | Hammer price |
| bid_count | integer | Final bids |
| date_sold | ISO date | Finalization date |

## Invariants
- Must not contain active listings.
- Must contain final_price.

---

# 5️⃣ ai_listing_valuations.csv

## Purpose
AI decision output.

## Layer
AI Profit Logic

## Columns

| Column | Type | Description |
|--------|------|------------|
| url | string | Unique identifier |
| resale_estimate | numeric | Curve-derived resale value |
| max_bid | numeric | Profit-locked max bid |
| profit_margin_pct | numeric | Profit margin percentage |
| verdict | string | Avoid / Not Viable / Marginal / Good |
| confidence | numeric | Confidence score (0–1) |

## Invariants
- resale_estimate must be curve-based.
- max_bid must produce positive profit.
- Risk must not inflate resale_estimate.

---

# 6️⃣ repair_prices.csv

## Purpose
Structured repair cost allocation.

## Layer
Risk & Repairs Model

## Columns

| Column | Type | Description |
|--------|------|------------|
| url | string | Unique identifier |
| total_estimated_repairs | numeric | Total repair estimate |
| risk_flags | string | Encoded risk categories |

## Invariants
- Repairs modify max_bid only.
- Repairs must not alter resale_estimate.

---

# 7️⃣ curves.csv

## Purpose
Canonical resale curves.

## Layer
Curve & Valuation Engine

## Columns (Exact Order)

| Column | Type | Description |
|--------|------|------------|
| canonical_tag | string | Unique curve group |
| anchor_year | integer | Year anchor |
| km_bucket | integer | Odometer anchor (km) |
| price_low | numeric | Lower bound |
| price_mid | numeric | Median value |
| price_high | numeric | Upper bound |

## Invariants
- Auction data must never influence these values.
- Only canonical_tag-based curves supported.
- No legacy schema permitted.

---

# Schema Change Policy

Any modification to:
- Column names
- Column order
- Column meaning

Must be documented and versioned.

Silent schema changes are prohibited.
