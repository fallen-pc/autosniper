# Repair vehicle-class propagation - 2026-08-11

- Direct supplier quotes remain scoped by both `canonical_defect` and `vehicle_class`.
- The Windscreen Medics `$339` quote applies to `windscreen` for `small_hatch`; the generic
  windscreen baseline remains `$300/$500/$1,000` for low/default/high.
- AI listing valuation, AI Analysis, Missed Opportunities, active monitoring, repair backfill,
  and aligned-training generation all pass `vehicle_class_for_listing(...)` to `assess_repairs(...)`.
- The Grays condition-repair report now does the same and keys its assessment cache by repair
  text plus vehicle class, preventing a quote for one class from leaking into another.
- The production schedule was installed at `/opt/autosniper/CSV_data/reports/repair_pricing_schedule.csv`
  with SHA-256 `06453726711a4c9b19fd5a6d40d38fca75e55e9f3824c196de67673788af2f94`.
- Verification: 159 cross-program repair tests passed before the report fix; the focused combined
