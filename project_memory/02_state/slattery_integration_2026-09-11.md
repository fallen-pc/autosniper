# Slattery integration repair — 11 September 2026

The owner authorised implementing the 9 September Grays/Slattery reassessment. Work is isolated from unrelated repair changes in a worktree based on current origin/main.

Deliberate scope: Slattery referral discovery, numeric/alphanumeric URL aliases resolved from explicit site data, persisted provenance across scheduled seed refreshes, structured identity/condition/location/registration/bid/lifecycle extraction, auction-operator fee selection and evidence-based completeness. Native Grays URLs and governed schemas/curves remain authoritative. Closed auctions must not become verified sales without independent settled-sale and final-price evidence.

Scraper/extractor and valuation changes are intentional within this scope. Captured public evidence is available in the nested development checkout at output/playwright/grays-reassessment-20260909. Tests and bounded live probes will write only isolated output artifacts. Source validation, local commit and production state will be reported separately.

Implemented: explicit native/referral pagination reconciliation; full URL/auction alias identity; structured detail and lifecycle gates; dealer-only registration cost handling; lot-bound fees with missing-evidence Review; fee-boundary-safe proxy caps and live/replay parity. See `docs/slattery_integration.md` for the final behavior and evidence.

Live verification: 325 unique Slattery vehicle URLs reconciled across 19 native API pages and seven Grays search pages. Five Slattery referrals merged into native identities. A final 11-lot detail probe returned 11 successful responses and verified fee schedules, ten complete details and one incomplete missing-odometer record. Statuses: two Active, eight Upcoming, one Closed. This is discovery plus bounded detail evidence, not a claim that all 325 details are complete.

Validation: full suite 1,334 passed with two pre-existing pandas FutureWarnings; readiness and governance passed. Governance reports all 446 observed tags covered, zero schema/dataset authority changes and 13 existing monotonicity warnings with no errors. Ruff, diff, project-memory and staged commit-hygiene checks passed; the staged slice contains source/test/docs/memory files only, with no runtime artifacts.

Status: implementation and local verification complete. No push, deployment or production data refresh has occurred in this work slice. The read-only VPS check observed deployed commit `ac1b2b5` and a successful latest daily run.
