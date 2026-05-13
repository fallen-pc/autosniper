# Current Status

- AutoSniper is a private owner-operated buying tool. Audit and prioritization should follow safe private-use fitness, not commercial SaaS standards; see [DEC-009](../03_decisions/DEC-009-audit-for-private-owner-use.md).

- The repo is broadly stable for active product work. Latest local validation after the most recent code changes: `.venv_local\Scripts\python.exe -m pytest -q` passed with `217` tests, and `python scripts/project_memory.py check` passed.

- The valuation path is now curve-first only. The old non-curve LLM pricing path has been removed, and current AI pricing behavior depends on saved curve coverage plus the active buying rules.

- Repair costing is materially stronger than the earlier baseline. Live valuation now uses the richer V2 repair engine, duplicate charging is blocked, hard-stop reasons are split into `MECHANICAL` and `STRUCTURAL`, and hard-avoid rows show an explicit repair/risk figure instead of fake `$0`.

- Unregistered-car costing now matches the owner's workflow better. AutoSniper no longer charges full buyer-side rego in valuation. Unregistered rows keep the `UNREGISTERED` risk signal, show `rego_estimate = $0`, and add a separate `roadworthy_estimate` instead.

- The current non-hard-avoid repair gate is intentionally looser than before. Moderate repair totals can still surface as `Marginal (repairs)` if the flip math works; mechanical and structural hard-stops still force `Avoid`.

- Lifecycle handling is more robust. Listings previously marked terminal can reopen to `active` on fresh live evidence, which reduced stale state drift between `vehicle_state.csv` and the materialized active views.

- AI shortlist hygiene is stricter in the active-monitor path. Completed rows, rows without a live price, and WOVR/repairable rows are excluded before curve-coverage valuation so the hourly/AI loop stays focused on real shortlist candidates.

- AI valuation history now has a compact decision-change ledger at `CSV_data/ai/listing_decision_events.csv`. It is designed to record meaningful per-listing transitions such as verdict/action changes, material max-bid or repair-estimate moves, bid-status flips, and coverage/risk changes instead of relying on broad hourly snapshot churn.

- Current live shortlist state is allowed to be empty. After the shortlist cleanup, the remaining restricted active rows are high-kilometre rows outside current curve bounds, so `0` AI-eligible active rows is currently a valid state rather than a pipeline failure.

- Curve coverage is complete on the current audited mainstream universe. The saved V2/base-curve setup covers all currently observed canonical tags on the last verified governance baseline (`45` observed, `45` covered, `0` missing).

- Scheduler logic is in better shape, but unattended operation still has a real Windows-session dependency. The daily/hourly paths have been hardened and overlap handling is better, but reliable Autotrader work still depends on an awake, logged-in session because headless/browser-session stability is not fully solved.

- AI Analysis wording is clearer than before. Cards now lead with the action, verdict text is supporting context, and profit wording is framed as margin strength instead of mixing several equally loud judgment labels. Stored action labels now use a shared `Buy` / `Watch` / `Avoid` / `Review` policy instead of mixing `Watch closely` and `Bid carefully` variants.

- The highest-value remaining product work is now the next decision-model layer: make visual semantics for risk/confidence/margin coherent, and then confirm the decision ledger against real shortlist movement when live candidates return.
