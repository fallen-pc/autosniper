# AutoSniper2 — Curve Specification
Version: 1.0
Status: Canonical

This document defines the official resale curve model used in AutoSniper2.

Only canonical_tag-based curves are supported.

---

# 1️⃣ Curve Identity

Each curve is uniquely identified by:

canonical_tag

canonical_tag must match the exact format produced by the system's
canonical tagging logic.

Example (real format):

toyota_corolla_ascent_petrol_auto_sedan_zre152r

Structure:

make_model_variant_fuel_transmission_body_platform

Breakdown example:

toyota
corolla
ascent
petrol
auto
sedan
zre152r

Important Rules:

- canonical_tag represents configuration identity only.
- It must not contain year ranges.
- It must not contain km bands.
- It must not contain pricing information.
- Platform/generation codes (e.g. zre152r) are allowed.
- Year anchoring is handled exclusively via anchor_year.
- Odometer anchoring is handled exclusively via km_bucket.

Legacy identifiers such as:
- group_id
- series
- km_anchor

are not permitted anywhere in runtime logic.


---

# 2️⃣ Curve Structure

Each row in curves.csv represents:

(canonical_tag, anchor_year, km_bucket)

Example anchor points:

| canonical_tag | anchor_year | km_bucket | price_mid |
|---------------|------------|----------|----------|
| corolla_tag | 2018 | 50000 | 21000 |
| corolla_tag | 2018 | 120000 | 17000 |

---

# 3️⃣ Interpolation Logic

Resale estimation uses bilinear interpolation:

Step 1:
Interpolate across km_bucket for nearest km anchors.

Step 2:
Interpolate across anchor_year for nearest year anchors.

Final resale_estimate = interpolated price_mid.

price_low and price_high may be used for confidence bounds only.

---

# 4️⃣ Curve Coverage Policy

A listing has curve coverage if:

- canonical_tag exists in curves.csv
- anchor_year range contains listing year
- km_bucket range contains listing odometer

If coverage exists:
- Use curve interpolation only.

If no coverage:
- Flag [NO_CURVE]
- Use conservative fallback valuation
- Reduce max_bid
- Never blend with auction price.

---

# 5️⃣ Contamination Guards

The following must NEVER influence resale_estimate:

- Current auction price
- Bid count
- Reserve price
- Final sale price

Curves are independent of auction dynamics.

---

# 6️⃣ Risk Interaction

Repairs and risk factors:

- Do NOT modify resale_estimate.
- Modify max_bid only.

---

# 7️⃣ Fallback Policy

If curve coverage is missing:

- resale_estimate must be conservative.
- confidence must be reduced.
- max_bid must reflect increased risk.

---

# 8️⃣ Change Control

Any modification to:

- Anchor structure
- Interpolation method
- Coverage logic
- Fallback method

Must be explicitly documented.

No silent logic drift permitted.

---

# 9️⃣ System Integrity Principle

Curve valuation is the foundation of profit safety.

If curve integrity is compromised:
- The entire AI layer becomes invalid.

Curve purity is non-negotiable.
