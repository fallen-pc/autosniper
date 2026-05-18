# Current Status

- AutoSniper is a private owner-operated buying tool. Audit and prioritization should follow safe private-use fitness, not commercial SaaS standards; see [DEC-009](../03_decisions/DEC-009-audit-for-private-owner-use.md).

- The repo is broadly stable for active product work. Latest local validation for the active-pipeline contract changes: focused pytest for link extraction, detail extraction, and readiness smoke tests passed; `python scripts/readiness_smoke.py`, `python scripts/governance_checks.py check`, and `python scripts/project_memory.py check` passed. The full pytest suite was attempted but timed out at 5 minutes and was stopped before completion.

- The valuation path is now curve-first only. The old non-curve LLM pricing path has been removed, and current AI pricing behavior depends on saved curve coverage plus the active buying rules.

- Repair costing is materially stronger than the earlier baseline. Live valuation now uses the richer V2 repair engine, duplicate charging is blocked, punctuation-heavy condition notes are split into repair fragments, mixed cosmetic/replacement damage is costed together, and hard-stop reasons are split into `MECHANICAL` and `STRUCTURAL`. Hard-avoid rows show an explicit repair/risk figure instead of fake `$0`.

- Unregistered-car costing now matches the owner's workflow better. AutoSniper no longer charges full buyer-side rego in valuation. Unregistered rows keep the `UNREGISTERED` risk signal, show `rego_estimate = $0`, and add a separate `roadworthy_estimate` instead.

- The current non-hard-avoid repair gate is intentionally looser than before. Moderate repair totals can still surface as `Marginal (repairs)` if the flip math works; mechanical and structural hard-stops still force `Avoid`.

- Lifecycle handling is more robust. Listings previously marked terminal can reopen to `active` on fresh live evidence, which reduced stale state drift between `vehicle_state.csv` and the materialized active views.

- Pipeline materialization is now queue-first for active listings. `active_vehicle_links.csv` is the unresolved active queue, `vehicle_static_details.csv` supplies static identity, and `vehicle_state.csv` enriches latest bid/lifecycle observations but does not need to say `state=active` for a queued static row to appear in `active_vehicle_details.csv`. Readiness now checks active rows against the active queue/static details and rejects only terminal state conflicts.

- AI shortlist hygiene is stricter in the active-monitor path. Completed rows, rows without a live price, and WOVR/repairable rows are excluded before curve-coverage valuation so the hourly/AI loop stays focused on real shortlist candidates.

- AI valuation history now has a compact decision-change ledger at `CSV_data/ai/listing_decision_events.csv`. It is designed to record meaningful per-listing transitions such as verdict/action changes, material max-bid or repair-estimate moves, bid-status flips, and coverage/risk changes instead of relying on broad hourly snapshot churn.

- Current live shortlist state is allowed to be empty. After the shortlist cleanup, the remaining restricted active rows are high-kilometre rows outside current curve bounds, so `0` AI-eligible active rows is currently a valid state rather than a pipeline failure.

- Curve coverage is complete on the current audited mainstream universe. The saved V2/base-curve setup covers all currently observed canonical tags on the last verified governance baseline (`45` observed, `45` covered, `0` missing).

- Scheduler logic is in better shape, but unattended operation still has a real Windows-session dependency. The daily/hourly paths have been hardened and overlap handling is better, but reliable Autotrader work still depends on an awake, logged-in session because headless/browser-session stability is not fully solved.

- Runtime artifact handling is now explicit. Generated reports, audits, backups, and output files should remain untracked where safe, while the minimum governed runtime CSV baseline stays tracked for fresh clones and governance checks. For normal source work, use `scripts/git_runtime_quiet.ps1 -Mode quiet` to hide local scraper/pipeline CSV churn; use `-Mode unquiet` before intentional data commits.

- AI Analysis wording is clearer than before. Cards now expose action, bid status, margin, confidence, and risk as separate signal tiles, verdict text is supporting context, and profit wording is framed as margin strength instead of mixing several equally loud judgment labels. Stored action labels now use a shared `Buy` / `Watch` / `Avoid` / `Review` policy instead of mixing `Watch closely` and `Bid carefully` variants. The card title path also preserves merged listing identity fields, so cards should show the vehicle title instead of the generic `Listing` fallback.

- The highest-value remaining product work is to validate the new AI Analysis signal strip against real shortlist movement when live candidates return, then tune only the labels or thresholds that prove confusing in daily auction review.
