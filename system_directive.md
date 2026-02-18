AutoSniper2 System Directive

Version 2.0 — Layer Enforced, Profit Locked

AutoSniper2 is a profit-safe vehicle acquisition intelligence system designed to identify profitable used vehicles at auction.

Primary Objective:
Ensure profit-safe decision making with zero valuation contamination.

Accuracy and structural integrity override speed or aggressiveness.

🔷 SYSTEM LAYERING (NON-NEGOTIABLE)

The system operates strictly in this order:

Pipeline & Data Integrity

Curve & Valuation Engine

Risk & Repairs Model

AI Profit Logic

UI & Display

Lower layers must never depend on upper layers.

Specifically:

Curve engine must not reference auction price, bids, reserve, or max_bid.

Risk modelling must not inflate resale_estimate.

AI Profit Logic must not modify curve outputs.

UI must not influence valuation or bidding logic.

No cross-layer contamination is permitted.

🔷 CORE PRINCIPLES
1️⃣ Curve-First Valuation (Mandatory)

resale_estimate must be derived from approved resale curves when available.

Auction prices, current bids, and reserve prices must never influence resale_estimate.

Historical sales data may only be used to:

Build curves

Validate curve reasonableness

Provide fallback estimates if curve coverage is missing

If curve coverage exists → historical prices must be ignored entirely.

2️⃣ Curve Coverage Rules

If a matching curve exists:

Use interpolation based on odometer band.

If no curve exists:

Flag listing as [NO_CURVE]

Generate conservative fallback resale_estimate

Reduce max_bid via a risk penalty

Never mix curve and fallback pricing silently.

3️⃣ URL as Sole Unique Identifier

The full listing URL is the only accepted unique identifier.

It must be used to:

Prevent duplicates

Reconcile status changes

Link active, sold, and AI verdict records

No alternative ID systems are permitted.

4️⃣ Withdrawn / Unsold Detection (Early Exit)

Exclude and log any listing with:

Missing final sale price

Expired auction without sale

Broken or dead URL

These must never enter active_vehicle_details.csv.

All exclusions must be logged with reason codes.

5️⃣ Risk & Assumption Handling

Assume:

No repairs unless explicitly stated.

Odometer materially affects risk.

Rego expiry materially affects risk.

Missing documentation increases risk.

Risk must:

Lower max_bid

Influence verdict

Influence confidence

Risk must never inflate resale_estimate.

6️⃣ AI Profit Logic (Profit-Locked)

AI analysis may only run after full normalization and validation.

Outputs must include:

max_bid (must always produce positive projected profit)

resale_estimate (curve-based or conservative fallback)

profit_margin percentage

verdict (Avoid / Not Viable / Marginal / Good)

Rules:

Never return a max_bid that results in negative profit.

If risk is high, reduce max_bid — not resale_estimate.

resale_estimate must remain structurally independent of auction price.

Profit safety overrides bid aggressiveness.

🔷 DATA GOVERNANCE

Normalization (Mandatory):

Strip non-alphanumeric leading characters from titles.

Convert odometer to numeric.

Convert dates to ISO format.

Exclusions:

Invalid or missing VIN

Non-vehicle entries

Obvious junk or listings with no auction data

CSV Consistency:

Column order, names, and types must match columns_list() exactly.

No silent schema changes permitted.

Logging:
All skipped or malformed rows must use reason codes:

[WITHDRAWN]

[NO_PRICE]

[BAD_PARSE]

[NON_VEHICLE]

[NO_URL]

[NO_CURVE]

No silent failures.

🔷 CONFIDENCE POLICY

Valuation confidence must be derived from:

Curve coverage percentage

Data completeness

Tag classification reliability

Risk profile strength

Confidence must never inflate resale_estimate.

🔷 MISSED OPPORTUNITIES POLICY

The system must support transparent analysis of:

Vehicles sold below theoretical max_bid

Vehicles skipped due to missing curve

Vehicles excluded due to risk

Misclassification or tag failures

This enables continuous calibration and investor transparency.

🔷 CHANGE CONTROL

Any modification to:

Curve interpolation logic

Risk multipliers

Fallback valuation method

max_bid calculation framework

Must be explicitly stated and documented.

Silent logic drift is not permitted.

🔷 SYSTEM PHILOSOPHY

Conservative over aggressive

Transparent over clever

Structured over reactive

Modular over tangled

Data-driven over assumption

The system prioritizes structural integrity over short-term opportunity.