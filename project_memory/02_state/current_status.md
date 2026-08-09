# Current Status

- AutoSniper is a private owner-operated buying tool. Audit and prioritization should follow safe private-use fitness, not commercial SaaS standards; see [DEC-009](../03_decisions/DEC-009-audit-for-private-owner-use.md).

- The DigitalOcean VPS at `/opt/autosniper` is the live production runtime and owns scraper output, scheduler state, logs, browser sessions, health reports, and generated CSV data. The laptop checkout is the development workspace; disabled laptop Task Scheduler jobs and stale local runtime CSVs are not evidence of a production outage. For any freshness, scraper, scheduler, active-listing, or valuation-runtime audit, inspect the VPS first through read-only Scraper Operations or read-only SSH checks. See `docs/vps_sync_workflow.md` and `project_memory/02_state/vps_runtime_authority_2026-08-02.md`.

- The 2026-08-03 audit branch passes its full committed test suite (`590 passed`), readiness smoke, governance, and project-memory validation from a separate clean checkout. A replay against the fresh VPS snapshot checked 2,503 curve-covered sold rows with zero mismatches between AI Analysis and Missed Opportunities for proxy max bid, downside profit, hard-safety state, or action.

- The valuation path is now curve-first only. The old non-curve LLM pricing path has been removed, and current AI pricing behavior depends on saved curve coverage plus the active buying rules.

- Repair costing is materially stronger than the earlier baseline. Live valuation now uses the richer V2 repair engine, duplicate charging is blocked, punctuation-heavy condition notes are split into repair fragments, mixed cosmetic/replacement damage is costed together, and hard-stop reasons are split into `MECHANICAL` and `STRUCTURAL`. Hard-avoid rows show an explicit repair/risk figure instead of fake `$0`.

- Repair Review can optionally receive conservative OpenAI suggestions for unresolved fragments. The classifier is disabled by default, suggestions only prefill operator fields, and no repair rule is promoted until an operator reviews and saves the decision. Older valuation rows with missing repair low/high fields can be repaired separately with the audited backfill script.

- Unregistered-car costing now matches the owner's workflow better. AutoSniper no longer charges full buyer-side rego in valuation. Unregistered rows keep the `UNREGISTERED` risk signal, show `rego_estimate = $0`, and add a separate `roadworthy_estimate` instead.

- The current non-hard-avoid repair gate is intentionally looser than before. Moderate repair totals can still surface as `Marginal (repairs)` if the flip math works; mechanical and structural hard-stops still force `Avoid`.

- Lifecycle handling is more robust. Listings previously marked terminal can reopen to `active` on fresh live evidence, which reduced stale state drift between `vehicle_state.csv` and the materialized active views.

- Pipeline materialization is now queue-first for active listings. `active_vehicle_links.csv` is the unresolved active queue, `vehicle_static_details.csv` supplies static identity, and `vehicle_state.csv` enriches latest bid/lifecycle observations but does not need to say `state=active` for a queued static row to appear in `active_vehicle_details.csv`. Readiness now checks active rows against the active queue/static details and rejects only terminal state conflicts.

- AI shortlist hygiene is stricter in the active-monitor path. Completed rows, rows without a live price, and WOVR/repairable rows are excluded before curve-coverage valuation so the hourly/AI loop stays focused on real shortlist candidates.

- AI valuation history now has a compact decision-change ledger at `CSV_data/ai/listing_decision_events.csv`. It is designed to record meaningful per-listing transitions such as verdict/action changes, material max-bid or repair-estimate moves, bid-status flips, and coverage/risk changes instead of relying on broad hourly snapshot churn.

- Current live shortlist state is allowed to be empty. After the shortlist cleanup, the remaining restricted active rows are high-kilometre rows outside current curve bounds, so `0` AI-eligible active rows is currently a valid state rather than a pipeline failure.

- Curve coverage is complete on the current audited mainstream universe. The latest verified governance baseline covers `233` observed tags with `0` missing.

- Production scheduling is now unattended on the DigitalOcean VPS through enabled systemd daily and hourly timers. Linux Chromium plus `xvfb-run` has a successful production-path Autotrader proof. Laptop Windows tasks should remain disabled unless the VPS is deliberately taken out of service and a single-writer fallback is explicitly chosen.

- Runtime artifact handling is now explicit. Generated reports, audits, backups, and output files should remain untracked where safe, while the minimum governed runtime CSV baseline stays tracked for fresh clones and governance checks. For normal source work, use `scripts/git_runtime_quiet.ps1 -Mode quiet` to hide local scraper/pipeline CSV churn; use `-Mode unquiet` before intentional data commits.

- AI Analysis is the daily buying screen and Dashboard is its condensed projection. Cards expose action, bid status, margin, confidence, risk, current bid, proxy max, and expected finish as separate signals. The shared action policy now emits `Buy`, `Avoid`, or `Review`: `Buy` is governed by current worst-case profit, remaining room to the auction-site proxy max, and hard-max safety. Expected auction finish and sold-comps count are informational only because the proxy max prevents an unprofitable above-cap win. `Avoid` covers bids over the cap, insufficient current worst-case profit, and hard safety/policy blocks; `Review` covers missing context. Legacy stored `Watch` fallbacks normalize to `Review`.

- The highest-value remaining product work is to validate the new AI Analysis signal strip against real shortlist movement when live candidates return, then tune only the labels or thresholds that prove confusing in daily auction review.
