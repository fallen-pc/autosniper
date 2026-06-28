---
date: 2026-06-29
topic: Removed legacy page 9 (VEHICLE_REPAIRS)
status: complete
---

`pages/9_VEHICLE_REPAIRS.py` deleted — it referenced `repair_estimates.csv`
which no longer exists. Active repair workflow is now pages 18 (REPAIR_REVIEW)
and 19 (REPAIR_PRICING). Removed references from `shared/navigation.py`,
`shared/data_loader.py`, and `project_memory/01_machine_rules/tracked_datasets.yaml`.
