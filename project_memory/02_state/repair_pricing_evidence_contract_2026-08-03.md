# Repair pricing evidence contract - 2026-08-03

- Repair schedule rows are keyed by `(canonical_defect, vehicle_class)`. A class-specific quote may coexist with another class or a genuinely generic quote; saving one class must not delete the others.
- Schedule saves reject duplicate defect/class keys, unsupported vehicle classes, invalid low/default/high ordering, and rows with no `evidence_source`.
- Do not create sedan, SUV, ute, or van prices by multiplying small-hatch quotes. Where only an incompatible class-specific quote exists, live AI Analysis and Missed Opportunities must use the conservative fallback for display but force `Review (repair pricing evidence)` rather than expose a clean `Buy`.
- The 2026-08-03 audit found 21 evidenced `small_hatch` rows and 6 evidenced `generic` rows. No additional class-specific database rows were added because no direct supplier evidence existed for the missing classes.
- The Highway Tyres puncture quote is `$40` low/default/high for `small_hatch`; the regression contract must exercise that class and must not retain the older `$80` heuristic expectation.
- Repair pricing cache keys are content-based. Long-running valuation services include the schedule content in their valuation hash, and Missed Opportunities includes the same signature in its Streamlit cache key, so an edit invalidates same-process results even if file size and modification time are unchanged.
