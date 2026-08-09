# Governed data snapshot - 2026-07-21

- `CSV_data/scrapers/sold_cars_all.csv` is the complete sold ledger and remains separate from the strict/model-ready `sold_cars.csv` contract.
- `CSV_data/reports/repair_review_live_queue.csv` captures the current deduplicated Repair Review work universe used by the operator and optional suggestion workflow.
- Timestamped pre-backfill and pre-recovery CSVs are local recovery artifacts and are deliberately excluded from this snapshot.
