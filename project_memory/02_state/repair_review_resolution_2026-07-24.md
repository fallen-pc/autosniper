# Repair review resolution — 2026-07-24

- Unresolved repair fragments now downgrade potential buys to Review across AI Analysis, Telegram alerts, and Missed Opportunities.
- Operator decisions marked `runtime-effective` participate in live repair matching.
- Decision matching tolerates punctuation and formatting differences.
- Active Monitor queues only genuinely unclassified fragments; hard-avoid and post-hard-avoid fragments do not reopen Repair Review.
- Historical replay: 2,660 sold rows, zero unresolved repair fragments.
- Live queue audit: 265 stored rows, zero needing review and zero unresolved.
- Focused verification: 132 tests passed.
- Repair classification is complete. Supplier-backed pricing remains a separate backlog.
