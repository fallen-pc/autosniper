# AI Working Agreement for AutoSniper

This file is the durable operating contract for AI-assisted work in this repository.

## Purpose
Use explicit written rules to reduce forgetting, scope drift, repeated debate over settled decisions, and accidental damage to important project boundaries.

## Source of Truth Order
When working in this repo, use this priority order:
1. Explicit user instruction in the current conversation
2. This file: `docs/ai_working_agreement.md`
3. Active repo memory files: `task_plan.md`, `findings.md`, `progress.md`
4. Current code and tests
5. Global workspace memory (`MEMORY.md`, daily notes)
6. Model recollection from conversation alone

If memory from chat conflicts with written repo files, prefer the written repo files unless the user explicitly overrides them.

## Mandatory Start Procedure for Any Non-Trivial Task
Before editing code, the agent must:
1. Read `docs/ai_working_agreement.md`
2. Read `task_plan.md`
3. Read `findings.md`
4. Read `progress.md`
5. Inspect relevant code and current git state
6. Restate the intended scope before widening changes

If this procedure is skipped, the agent is operating unsafely.

## Current No-Touch / Deferred Scope
These remain deferred / high-sensitivity unless Ewan explicitly re-opens them for a specific task:
- `scripts/process_curve_candidates.py`
- `scripts/atomic_csv.py`
- scraper / extractor chain core files:
  - `scripts/extract_links.py`
  - `scripts/extract_vehicle_details.py`
  - `scripts/scrape_autotrader_rego.py`
  - `scripts/scrape_bid_history.py`
  - `scripts/run_autotrader_scrape.ps1`
  - `shared/scraper_health.py`
  - `autotrader_isolated/scrape_first_page.py`
- adjacent operator / UI surfaces that are still high-sensitivity even though some sandbox runtime fixes were already allowed:
  - `pages/1_LINK_EXTRACTOR.py`
  - `pages/2_VEHICLE_DETAIL_EXTRACTOR.py`
  - `pages/3_ACTIVE_LISTINGS.py`
  - `pages/7_AUTOTRADER_SCRAPER.py`
  - `pages/12_GRAYS_PIPELINE.py`
  - `pages/05_HEALTH.py`
  - `pages/14_CURVE_PIPELINE.py`
  - `pages/15_CURVE_BUILDER_V2.py`
- broader governance coordinator still intentionally held out from cleanup-style passes:
  - `governance/run_checks.py`

Important clarification:
- sandbox-only runtime bring-up work already reopened a narrow subset of page-level fixes where needed to make the app launchable under WSL/Linux-side validation
- that does **not** mean the whole scraper / extractor / curve-core area is now generally open for casual refactors
- treat these files as high-sensitivity surfaces: only touch them for explicit runtime/product tasks, not opportunistic cleanup

## Current Completed / In-Scope Status
Known checkpointed status now includes:
- sold-data/script hardening complete and checkpointed for:
  - `scripts/train_auction_price_correction.py`
  - `scripts/prepare_sold_training_data.py`
  - `scripts/clean_sold_csv.py`
  - `scripts/enrich_sold_repairs.py`
  - `scripts/build_restricted_datasets.py`
- structural split exists in sandbox as a real package lane (`governance/`, `jobs/`, `ops/`) with wrapper compatibility preserved in `scripts/`
- governance / jobs / ops lane audits were completed and checkpointed
- targeted regression validation is green in the Linux-side test env for:
  - `tests/test_generate_curve_candidates.py`
  - `tests/test_governance.py`
- sandbox runtime bring-up is broadly working under the documented WSL/Linux-side path, including checkpointed runtime/page fixes

If additional files were processed previously but are not recorded here, do not guess. Recover evidence first, then update this document.

## Change Discipline Rules
- Prefer the smallest safe change that materially reduces risk or confusion
- Do not widen a local cleanup into an architectural rewrite without explicit approval
- Do not reopen settled decisions casually
- Do not touch deferred files because they look adjacent or tempting
- If a file is now correct, understandable, and not obviously hazardous, stop
- If a task summary says "do not touch X", treat that as a hard boundary

## Decision Logging Rules
Record these immediately in repo files when they occur:
- files explicitly deferred
- files marked done for now
- architectural constraints
- dangerous areas / no-go zones
- candidate shortlist changes
- reasons for stopping work on a file

Use:
- `task_plan.md` for current status and guardrails
- `findings.md` for discoveries and rationale
- `progress.md` for chronological actions and test notes

## Reliability Rules
- Never claim historical project state unless it is supported by code, git evidence, tests, or written memory files
- If uncertain whether a file was previously processed, say so and record the uncertainty
- Prefer "unknown, needs recovery" over fabricated continuity
- When you say you are starting a task, actually start it in the same turn

## Architecture Guidance
Current high-level judgement for AutoSniper:
- worth continuing; not in crisis
- biggest architectural risk: blurred boundaries between domain logic, jobs/pipelines, UI, and storage/runtime artifacts
- biggest hygiene risk: tracking too much generated/high-churn operational data alongside source code
- the sandbox structural split is directionally good and usable, but still not fully decoupled from legacy/shared high-blast-radius surfaces

Therefore:
- value boundary clarification over cosmetic tidying
- prefer changes that reduce code/data/runtime mixing
- avoid project-wide churn unless there is a clear rollback/test path
- treat generated CSV/runtime churn as validation noise unless deliberately capturing a data snapshot
- current product priorities are now:
  1. verify profit determination accuracy
  2. identify how to safely add more curves in Curve Builder V2

## When to Stop and Ask
Stop and summarize before proceeding if:
- the next step would cross a deferred boundary
- the change would affect multiple subsystems unexpectedly
- the safest path seems to require architectural rather than local edits
- there is conflicting evidence about prior decisions

## Updating This File
This file should stay short, explicit, and durable.
Only add rules that should continue to matter across future sessions.
