# Grays repair review handoff - 2026-07-14

- Grays active listings can include numbered condition assessment rows after the booking-staff opinion sentence.
- The scraper now preserves those numbered rows in `general_condition` alongside the older summary notes.
- AI Analysis now queues Grays comparison `unmatched_lines` into Repair Review through `append_unclassified_condition_lines()`.
- Repair Review key matching normalizes smart apostrophes so saved decisions match live queue rows.
- Numbering-only fragments such as `1.` and `#39.` are filtered before repair review/audit handling.
- Focused regression coverage: `tests/test_extract_vehicle_details_regressions.py`, `tests/test_repair_pricing.py`, and `tests/test_repair_review.py`.
