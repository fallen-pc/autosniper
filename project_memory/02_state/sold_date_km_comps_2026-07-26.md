# Sold-date validation and km-aware comps

Status: implemented and verified on 2026-07-26.

- Sold validation rejects `date_sold` values more than one local-calendar day in the future.
- AI Analysis and Missed Opportunities use the shared `sold_comparables` selector.
- Comparable selection prefers at least three same-tag/year sales within 50,000 km, expands to 100,000 km, and otherwise uses the available tag/year fallback.
- Missed Opportunities excludes the replayed sold URL from its own comparable pool.
- The 19 pricing-relevant legacy date-swapped rows were re-scraped and restored with confirmed February/March 2026 dates.
- Focused verification: 68 comparable/policy tests and 12 sold-date/rebuild/repair tests passed.
