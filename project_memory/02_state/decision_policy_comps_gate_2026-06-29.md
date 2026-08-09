---
date: 2026-06-29
topic: Minimum comps gate added to BUY decision
status: complete
---

BUY action is now blocked → WATCH when `comps_count < 3` (MIN_COMPS_FOR_BUY).
`comps_count=None` bypasses the gate (backward compatible).
`derive_action_label_from_row()` reads `expected_auction_comps_count` from the row dict.
Applies to all callers: live AI page, missed opportunities replay, Telegram alerting.
