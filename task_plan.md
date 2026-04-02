# Task Plan: AutoSniper AI-safe project memory and change discipline

## Goal
Establish durable, repo-local working memory and explicit guardrails so AI-assisted work on AutoSniper does not forget decisions, reopen locked scope, or drift into irrelevant or dangerous changes.

## Current Phase
Phase 5

## Phases

### Phase 1: Memory bootstrap & guardrails
- [x] Confirm available memory/skill mechanisms in workspace
- [x] Verify whether AutoSniper already has planning files
- [x] Record current locked scope, deferred files, and recent decisions
- [x] Create repo-local planning files for persistent working memory
- **Status:** complete

### Phase 2: Working agreement for AI changes
- [x] Define no-touch zones and change constraints for current refactor wave
- [x] Define how to start any future task safely
- [x] Define where durable project decisions must be written
- **Status:** complete

### Phase 3: Active task tracking
- [x] Track current shortlist of candidate files
- [x] Record decisions as each candidate is assessed
- [x] Mark completed safe cleanups and deferred areas
- [x] Recover evidence-backed prior processed-file context where possible
- **Status:** complete

### Phase 4: Verification & upkeep
- [x] Re-read planning files before major decisions or edits
- [x] Update progress after each meaningful work slice
- [x] Keep findings current after discovery/research
- [x] Create a single processed-files ledger for future session recovery
- **Status:** complete

### Phase 5: Delivery discipline
- [x] Use planning files as source of truth for future AutoSniper work
- [x] Refuse to widen changes beyond recorded scope without explicit decision
- [x] Summarize state clearly when handing off or pausing
- **Status:** active / in use

### Phase 6: Structural-refactor lane audit
- [x] Identify that the remaining sandbox divergence is a separate lane, not random leftovers
- [x] Capture the existence of structural docs and package directories as evidence-backed context
- [x] Audit the pre-existing structural-refactor files for alignment, risk, and commit boundaries
- [x] Decide whether that lane should be normalized into repo memory/docs further before new code edits there
- [x] Record structural-split, governance-lane, jobs-lane, and ops-lane audit results in repo memory
- **Status:** complete

## Key Questions
1. What files/areas are explicitly deferred or locked for the current refactor wave?
2. What is the smallest safe next step before touching any new AutoSniper file?
3. Where should durable repo-specific decisions live so they survive context loss?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use repo-local planning files (`task_plan.md`, `findings.md`, `progress.md`) as primary working memory for AutoSniper | Conversation-only context is not reliable enough for a large project |
| Treat explicit deferred files as no-touch until re-approved | Prevents AI from reopening locked scope or undoing prior decisions |
| Stop after small safe cleanup of `scripts/train_auction_price_correction.py` | The meaningful bug was fixed; further work there would likely be low-value tidying |
| Prefer file-backed project memory over relying on model recall | Scales better for long, complex, multi-session work |

## Locked / Deferred Scope
- Do not touch `scripts/process_curve_candidates.py` in the current wave
- Do not touch `scripts/atomic_csv.py` in the current wave
- Do not touch scraper / extractor chain files in the current wave:
  - `scripts/extract_links.py`
  - `scripts/extract_vehicle_details.py`
  - `scripts/scrape_autotrader_rego.py`
  - `scripts/scrape_bid_history.py`
  - `scripts/run_autotrader_scrape.ps1`
  - `shared/scraper_health.py`
  - `autotrader_isolated/scrape_first_page.py`
  - `pages/1_LINK_EXTRACTOR.py`
  - `pages/2_VEHICLE_DETAIL_EXTRACTOR.py`
  - `pages/3_ACTIVE_LISTINGS.py`
  - `pages/7_AUTOTRADER_SCRAPER.py`
  - `pages/12_GRAYS_PIPELINE.py`
  - `pages/05_HEALTH.py`
- Do not widen scope from a targeted script cleanup into architectural churn without explicit approval

## Current Candidate Status
### Committed sold-data / memory lane
- `scripts/train_auction_price_correction.py` → small safe cleanup complete
- `scripts/prepare_sold_training_data.py` → small safe cleanup complete
- `scripts/clean_sold_csv.py` → small safe cleanup complete
- `scripts/enrich_sold_repairs.py` → small safe cleanup complete
- `scripts/build_restricted_datasets.py` → small safe cleanup complete

### Deferred current-wave boundaries
- `scripts/process_curve_candidates.py` → explicitly skipped/deferred
- scraper / extractor chain files → explicitly deferred via named file list in deferred scope
- `scripts/atomic_csv.py` → explicitly deferred

### Separate structural-refactor lane present in sandbox
- architecture docs: `docs/refactor-plan.md`, `docs/repo-structure.md`, `docs/storage-policy.md`
- new package directories: `governance/`, `jobs/`, `ops/`
- compatibility-wrapper style scripts observed: `scripts/normalize_conditions.py`, `scripts/readiness_smoke.py`, `scripts/check_commit_hygiene.py`, `scripts/governance_checks.py`
- this lane should be audited and handled as its own change stream rather than merged mentally into the sold-data cleanup wave

### Current curve mini-wave
- `governance/curve_validator.py` → tiny schema-safety cleanup checkpointed
- `scripts/curve_validator.py` → tiny wrapper-identity cleanup checkpointed
- `governance/curve_coverage_report.py` → tiny helper extraction cleanup checkpointed
- `scripts/curve_coverage_report.py` → tiny wrapper-identity cleanup checkpointed
- `scripts/check_commit_hygiene.py` → tiny wrapper-identity cleanup checkpointed
- `governance/check_commit_hygiene.py` → tiny helper extraction cleanup checkpointed
- `governance/run_checks.py` → reviewed as a possible next target, but held out to keep follow-up work small and low-risk
- `tests/test_generate_curve_candidates.py` → tiny regression-test follow-up complete in working tree
- `tests/test_governance.py` → tiny regression-test follow-up complete in working tree

## Known Processed vs Unknown Historical State
Known from current evidence in this wave:
- `scripts/train_auction_price_correction.py` was processed and received a small safe cleanup
- `scripts/process_curve_candidates.py` was explicitly reviewed for prioritization and then deferred, not changed in this wave
- scraper-chain files were explicitly deferred, not changed in this wave
- `scripts/atomic_csv.py` was explicitly deferred, not changed in this wave

Recovered from repo evidence (recent activity / prior project churn, not necessarily current-wave edits):
- curve pipeline and governance work has been active around:
  - `scripts/process_curve_candidates.py`
  - `scripts/generate_curve_candidates.py`
  - `pages/14_CURVE_PIPELINE.py`
  - `pages/15_CURVE_BUILDER_V2.py`
  - `shared/curves.py`
  - `shared/curve_builder_v2.py`
  - `shared/curve_groups_v2.py`
  - `shared/governance.py`
  - `scripts/governance_checks.py`
  - `scripts/curve_validator.py`
  - `scripts/curve_coverage_report.py`
  - `tests/test_process_curve_candidates.py`
  - `tests/test_generate_curve_candidates.py`
  - `tests/test_governance.py`
- auction/sold-data model and preparation work has touched:
  - `scripts/train_auction_price_correction.py`
  - `scripts/prepare_sold_training_data.py`
  - `scripts/rebuild_sold_dataset.py`
  - `scripts/enrich_sold_repairs.py`
  - `scripts/build_restricted_datasets.py`
  - `scripts/clean_sold_csv.py`
- atomic CSV write infrastructure is broadly depended on by many scripts and should be treated as high-blast-radius even when deferred:
  - `scripts/atomic_csv.py`

Unknown / not yet proven:
- an exact complete ledger of every file previously processed across older AI sessions
- which of the recently active files were AI-edited versus manually edited

Rule:
- do not invent or backfill historical processed-file lists without written/project evidence
- treat recovered git/doc evidence as directional context, not proof of current-wave edits
- if older work is recovered from commits, notes, or prior documents, update this section

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| AutoSniper planning files absent, so planning-with-files had nothing to anchor to | 1 | Initialize planning files in repo root and treat them as canonical working memory |
| Global memory search returned no useful AutoSniper task-state recall | 1 | Store active project state in repo files instead of relying on global memory alone |

## Notes
- Before any substantial AutoSniper work: read `docs/ai_working_agreement.md`, `task_plan.md`, `findings.md`, and `progress.md`
- Record locked decisions immediately when they are made
- If scope changes, update these files before editing code
- Do not treat remembered chat context as authoritative when repo-local memory disagrees
