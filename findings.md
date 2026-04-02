# Findings & Decisions

## Requirements
- Prevent AI-assisted work from forgetting prior decisions on AutoSniper
- Prevent reopening explicitly deferred files or widening scope casually
- Preserve project state across long sessions and resets
- Keep the memory system lean enough to be read quickly before action

## Research Findings
- OpenClaw global memory exists (`MEMORY.md` plus daily notes), but current AutoSniper-specific recall is too sparse to reliably recover active project state
- The `planning-with-files` skill is installed in the workspace, but it only becomes useful for a project when planning files actually exist in the project root
- The `refactor-safely` skill helps constrain how changes are made, but does not itself provide sufficient long-horizon project memory
- For a project this large, the reliable pattern is: repo-local working memory + explicit change constraints + re-reading before decisions
- Git history shows recent heavy project churn around the curve pipeline/governance area, plus sold-data preparation/modeling scripts
- Git/docs evidence can recover a useful map of historically active areas, but not a perfect ledger of what an AI previously changed unless that history was explicitly written down
- The earlier fuzzy bucket "scraper-chain files" has now been replaced with an explicit named file list in repo rules/ledger to reduce boundary ambiguity
- The sandbox also contains a separate structural-refactor lane (docs + package directories + compatibility wrappers) that predates the sold-data cleanup checkpoint and should be tracked as its own context rather than dismissed as random leftovers

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Use repo-local markdown files as operational memory | More reliable than hoping the model remembers long threads |
| Keep active task state in the repo, not only in global workspace memory | Project-specific decisions need to travel with the codebase |
| Keep planning files concise and high-signal | They need to be cheap to re-read before action |
| Separate active task state from long-term global memory | Global memory should hold durable summaries, not all live project details |
| Add `docs/ai_working_agreement.md` as durable repo law | Long-lived rules should be separate from active task tracking |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Planning skill installed but inactive for AutoSniper | Created planning files in repo root |
| Memory search did not surface shortlist/decision context for this thread | Wrote the current state into repo-local files |
| AI drift risk on large refactor tasks | Added explicit no-touch/deferred scope and current candidate status |
| Prior processed-file history is incomplete from current evidence | Record only confirmed state; recover older history later from evidence if needed |

## Resources
- AutoSniper sandbox repo root: `/mnt/c/Users/ewanf/Desktop/autosniper-main-sandbox`
- Durable repo rules: `/mnt/c/Users/ewanf/Desktop/autosniper-main-sandbox/docs/ai_working_agreement.md`
- Processed files ledger: `/mnt/c/Users/ewanf/Desktop/autosniper-main-sandbox/docs/processed_files_ledger.md`
- Planning skill: `/home/ewanf/.openclaw/workspace/skills/planning-with-files/SKILL.md`
- Refactor skill: `/home/ewanf/.openclaw/workspace/skills/refactor-safely/SKILL.md`
- Global memory: `/home/ewanf/.openclaw/workspace/MEMORY.md`
- Daily note: `/home/ewanf/.openclaw/workspace/memory/2026-04-01.md`
- Recent commit evidence: `git log --oneline -n 25` in the sandbox repo root
- Recent file churn evidence: `git log --name-only -n 25 -- '*.py' '*.md' 'docs/*'`

## Recovered Historical Context
### Confirmed current-wave status
- `scripts/train_auction_price_correction.py` was edited in the current working tree and is now marked small-safe-cleanup complete
- `scripts/process_curve_candidates.py`, scraper-chain files, and `scripts/atomic_csv.py` are currently deferred / no-touch

### Recovered from recent repo evidence
- The curve pipeline/governance area has been a major recent focus, including commits about:
  - curve datasets and governance snapshots
  - Curve Builder V2 and grouped curve mapping
  - unlocking curve candidates using recent market evidence
  - regression/governance checks
  - stable CSV loading and pipeline tooling
- Files strongly indicated as recent high-activity areas:
  - `scripts/process_curve_candidates.py`
  - `scripts/generate_curve_candidates.py`
  - `pages/14_CURVE_PIPELINE.py`
  - `pages/15_CURVE_BUILDER_V2.py`
  - `shared/governance.py`
  - `shared/curves.py`
  - `shared/curve_builder_v2.py`
  - `shared/curve_groups_v2.py`
  - `tests/test_process_curve_candidates.py`
  - `tests/test_generate_curve_candidates.py`
  - `tests/test_governance.py`
- The sold-data / pricing-modeling area also has evidence of prior work around:
  - `scripts/train_auction_price_correction.py`
  - `scripts/prepare_sold_training_data.py`
  - `scripts/rebuild_sold_dataset.py`
  - `scripts/enrich_sold_repairs.py`
  - `scripts/build_restricted_datasets.py`
  - `scripts/clean_sold_csv.py`
- `scripts/atomic_csv.py` appears as shared infrastructure used broadly across many scripts, so even when deferred it should be treated as high-blast-radius

### Structural-refactor lane observed in sandbox
- The sandbox contains untracked architecture/planning docs: `docs/refactor-plan.md`, `docs/repo-structure.md`, `docs/storage-policy.md`
- The sandbox also contains untracked package directories: `governance/`, `jobs/`, and `ops/`
- Several modified `scripts/` files are now evidenced as compatibility wrappers into those newer package paths rather than unrelated one-off edits
- Direct reads of the docs show a coherent migration story: role-based package split, wrapper compatibility phase, and storage classification work
- Direct package listings show `governance/`, `jobs/`, and `ops/` contain real modules rather than empty scaffolding
- Diff shape strongly suggests migration work more than fresh behavior edits: large deletions from old `scripts/` files and small wrapper replacements
- This lane is directionally aligned with the repo-memory guardrails (clearer boundaries, less mixed responsibility), but it is broader and riskier than the small sold-data cleanup wave and should be tracked separately

### Current structural-lane assessment
- Best current interpretation: this is a coherent pre-existing structural migration lane, not random sandbox leftovers
- It appears to include three kinds of changes:
  1. planning/rules docs (`docs/refactor-plan.md`, `docs/repo-structure.md`, `docs/storage-policy.md`)
  2. moved/new package implementations under `governance/`, `jobs/`, and `ops/`
  3. compatibility wrappers left in `scripts/` to preserve old entrypoints/import expectations
- That coherence was later strong enough to checkpoint as a separate structural migration commit in the sandbox history
- Special-case leftovers from that lane were then resolved separately (`.gitignore` and `task_plan.md` committed in their own tiny follow-up, generated CSV residue reverted, scraper-boundary wrapper reverted)

### Structural split audit result
- Post-checkpoint audit found the structural split to be coherent rather than half-broken
- Wrapper scripts sampled in `scripts/` do behave as compatibility wrappers into the newer package layout (`governance.*`, `jobs.*`, `ops.*`)
- `python3 -m py_compile` passed across the sampled wrappers and corresponding package modules, giving syntax-level confidence that the split is intact
- The package roles look directionally sensible:
  - `governance/` for checks/reporting entrypoints
  - `jobs/` for job-style preparation/normalization tasks
  - `ops/` for operational and curve-adjacent tooling
- Important remaining caveat: the split did not fully remove dependence on older high-blast-radius/shared surfaces
  - confirmed examples: `jobs/extract_links.py` and `jobs/normalize_listing_csvs.py` still reference `scripts.atomic_csv`
- So the correct interpretation is: the structural split is real and usable as a baseline, but not yet proof that all architectural risk around deferred/shared infrastructure has been eliminated

### Limits of recovery
- Recent commit/file churn is not the same as a verified AI-processed ledger
- Do not assume every recently active file was touched by the same refactor wave
- If a precise historical list is needed, recover it from explicit notes/commits rather than inference

## Visual/Browser Findings
- None for this setup pass

---
*Update this file after every 2 view/browser/search operations*
*This prevents visual information from being lost*
