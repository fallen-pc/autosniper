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
| Treat the sandbox as the active working base, not the main repo | Sandbox now contains the meaningful checkpointed stabilisation, runtime, validation, and structural work |
| Treat runtime-generated CSV churn as validation noise by default | Generated outputs should not drive source-of-truth project state unless intentionally captured |
| Shift from cleanup mode into product discovery mode | The sandbox is now stable enough that the highest-value next work is profit/curve product understanding, not more opportunistic cleanup |

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

### Governance-lane audit result
- The governance slice of the structural split also looks coherent overall
- Wrappers for `scripts/governance_checks.py`, `scripts/check_commit_hygiene.py`, `scripts/curve_coverage_report.py`, `scripts/curve_validator.py`, and `scripts/readiness_smoke.py` are consistent compatibility wrappers into `governance.*`
- `python3 -m py_compile` passed across those wrappers and the paired `governance/` modules, so syntax-level integrity looks good
- `governance/run_checks.py` appears structurally sensible and does not obviously reach back into deferred curve-core or scraper-core modules
- Important caveats from this lane audit:
  - `governance/curve_coverage_report.py` still depends on `scripts.atomic_csv`
  - `governance/readiness_smoke.py` intentionally probes legacy/deferred entrypoints such as `scripts.extract_links` and `scripts.extract_vehicle_details` as part of readiness validation
  - live `--help` execution for governance entrypoints was environment-sensitive here because project dependencies like `pandas` were not installed in the current shell
- Best interpretation: governance is a real, usable package lane with preserved wrapper compatibility, but it is not fully isolated from shared/runtime or deferred-boundary surfaces

### Jobs-lane audit result
- The jobs slice of the structural split also looks coherent overall
- Wrappers for `scripts/normalize_conditions.py` and `scripts/normalize_listing_csvs.py` are clean compatibility wrappers into `jobs.*`
- Sampled package modules (`jobs/build_restricted_datasets.py`, `jobs/normalize_conditions.py`, `jobs/normalize_listing_csvs.py`, `jobs/extract_links.py`) are real implementations rather than stubs
- `python3 -m py_compile` passed across sampled wrappers and jobs modules, so syntax-level integrity looks good
- `jobs/build_restricted_datasets.py`, `jobs/normalize_conditions.py`, and `jobs/normalize_listing_csvs.py` did not show obvious direct reach-back into deferred curve-core or scraper-core entrypoints during the import-text scan
- Important caveats from this lane audit:
  - sampled jobs modules still depend on `scripts.atomic_csv`, so the lane is not fully decoupled from shared high-blast-radius write infrastructure
  - `jobs/extract_links.py` is a real module under the new package layout, but it remains functionally inside the deferred scraper/extractor boundary and should still be treated as sensitive
- Best interpretation: jobs is a real, usable package lane with preserved wrapper compatibility, but it is not yet fully isolated from shared/deferred infrastructure and scraper-boundary sensitivity

### Ops-lane audit result
- The ops slice of the structural split also looks coherent overall
- Wrappers for `scripts/active_monitor.py`, `scripts/analyze_bid_history.py`, `scripts/generate_curve_candidates.py`, `scripts/outcome_tracking.py`, and `scripts/render_curve_images.py` are consistent compatibility wrappers into `ops.*`
- Sampled package modules (`ops/active_monitor.py`, `ops/analyze_bid_history.py`, `ops/generate_curve_candidates.py`, `ops/outcome_tracking.py`, `ops/render_curve_images.py`) are real implementations rather than stubs
- `python3 -m py_compile` passed across sampled wrappers and ops modules, so syntax-level integrity looks good
- The sampled ops modules did not show obvious direct reach-back into deferred `scripts/process_curve_candidates.py` or the locked scraper entrypoints during the import-text scan
- Important caveats from this lane audit:
  - some ops modules still depend on `scripts.atomic_csv`, so the lane is not fully decoupled from shared high-blast-radius infrastructure
  - parts of the lane remain curve-adjacent or autotrader-adjacent, so it should still be treated with care even though the package split itself looks coherent
- Best interpretation: ops is a real, usable package lane with preserved wrapper compatibility, but it is not yet fully isolated from shared infrastructure or all nearby high-sensitivity surfaces

### Curve mini-wave status
- A small curve-adjacent cleanup wave was checkpointed in the sandbox after the broader lane audits
- That checkpoint stayed on the low-risk governance/wrapper side rather than reopening deferred curve-core or scraper scope
- Checkpointed low-risk changes:
  - `governance/curve_validator.py`: made warning-frame column shape explicit even when empty, reducing return-shape drift risk
  - `scripts/curve_validator.py`: added a compatibility-wrapper docstring to make the wrapper role explicit
  - `governance/curve_coverage_report.py`: extracted canonical-tag report-frame creation into a small helper without widening behavior
  - `scripts/curve_coverage_report.py`: added a compatibility-wrapper docstring to make the wrapper role explicit
  - `scripts/check_commit_hygiene.py`: added a compatibility-wrapper docstring to make the wrapper role explicit
  - `governance/check_commit_hygiene.py`: extracted repeated git-output line normalization into a tiny helper without widening behavior
- `python3 -m py_compile` passed for the updated curve-governance files, including `governance/check_commit_hygiene.py`
- `governance/run_checks.py` remains intentionally held out because it is broader and more coupled than the utility/wrapper cleanups done so far
- Best interpretation: the curve mini-wave is checkpointed, and the subsequent governance utility follow-up was also safely checkpointed without reopening deferred curve-core work

### Test follow-up status
- The next safest move after the governance-side micro-cleanups was test-first regression coverage rather than more production-code tidying
- `tests/test_generate_curve_candidates.py` now includes narrow regression coverage around alias/base-tag grouping, existing-curve refresh detection, and duplicate-free `review_reason` output without overfitting to stale historical tag strings or overly brittle full-order expectations
- `tests/test_governance.py` now includes narrow regression coverage that checks dataset-delta allowlist matching still works after path normalization (`\\` to `/`) and that equivalent path spellings deduplicate cleanly after normalization
- A WSL venv on `/mnt/c` proved unreliable for compiled packages, so targeted validation was moved to a clean Linux-side venv at `/home/ewanf/.cache/autosniper-test-venv`
- In that clean env, targeted pytest ran successfully: `tests/test_generate_curve_candidates.py` and `tests/test_governance.py` passed together (`15 passed`)
- Best interpretation: this is now a clean, low-blast-radius, test-validated follow-up that strengthens expected behavior around curve-candidate triage and governance path handling without reopening deferred production-code scope
- A real structural-split inconsistency remained in `ops/prepare_sold_training_data.py`: it had not inherited the safer missing-odometer guard or the copy-before-transform behavior previously applied to `scripts/prepare_sold_training_data.py`
- That follow-up was worth doing because it reduces split-brain risk between the wrapper-facing script path and the package implementation that the structural split is trying to make authoritative
- After that sync, the next genuinely safe package-side cleanup found was in `jobs/normalize_conditions.py`: an unused `csv` import remained and could be removed cleanly without touching behavior, boundaries, or output shape
- Another real structural-split consistency gap remained in `jobs/build_restricted_datasets.py`: it had not inherited the safer missing-column fallback handling and single-instant backlog timestamp/date derivation already proven in `scripts/build_restricted_datasets.py`
- That follow-up is worth doing because it keeps the package implementation aligned with the safer script-side backlog behavior without reopening deferred scope or changing output contracts
- The sandbox app is now broadly launchable in the WSL/Linux-side validation setup after mechanical runtime fixes and dependency bring-up, so the repo is no longer just theoretically coherent — it has been exercised through live Streamlit startup and page-import/runtime paths
- The working bring-up path is WSL + sandbox repo + Linux-side venv at `/home/ewanf/.cache/autosniper-test-venv`, not Windows PowerShell + main repo + unrelated venvs
- The most valuable runtime fixes were mechanical, not business-logic changes:
  - replacing bare `python` shell-outs in page entrypoints with `sys.executable`
  - fixing the `pages/04_MAPPINGS.py` empty-state `st.data_editor(... disabled=None ...)` crash by using an empty list instead of `None`
  - satisfying missing runtime deps in the Linux-side venv incrementally (`streamlit`, `beautifulsoup4`, `playwright`, `python-dotenv`, `openai` as needed during bring-up)
- Live warnings seen during bring-up do not currently block app startup but are worth bounded cleanup:
  - `pages/04_MAPPINGS.py` badge matching used regex-enabled `str.contains`, which emitted warnings for raw badge text containing regex groups; using `regex=False` is the safer/default intent here
  - some Streamlit `use_container_width` warnings are mechanical deprecations; a bounded pass should only touch warning sites actually seen during bring-up, not the whole app at once
- Real click-through validation found two more page-render bugs after the app became broadly launchable:
  - `pages/15_CURVE_BUILDER_V2.py` unconditionally unpacked three columns from a `st.columns(...)` call that sometimes only returned two; the safe fix is to branch column creation by mode and set the middle slot to `None` when absent
  - `pages/99_STYLE_GUIDE.py` called `st.code()` with no body at all; the safe fix is to provide a harmless placeholder string so the page can render instead of crashing
- These are good examples of the current repo state: no longer broken at the platform/startup level, but still likely to contain small page-local runtime defects that only appear under real click-through validation
- The project now benefits from two short operational docs to prevent regression into environment confusion and ad hoc validation:
  - `docs/wsl_runbook.md` captures the known-good WSL + sandbox + Linux-side venv launch path and the dependency/browser install pattern that actually worked
  - `docs/workflow_validation_checklist.md` captures how to classify and record sandbox workflow issues so future validation distinguishes code bugs from dependency/data/browser/service blockers
- The repo-memory docs had drifted behind actual sandbox history in a few places:
  - scraper/operator pages such as `pages/1_LINK_EXTRACTOR.py`, `pages/2_VEHICLE_DETAIL_EXTRACTOR.py`, and `pages/7_AUTOTRADER_SCRAPER.py` were still described as untouched/deferred even after sandbox-only runtime bring-up fixes had already been checkpointed there
  - `jobs/build_restricted_datasets.py` still appeared as “in progress” in some task text after its consistency sync had already been checkpointed
- That drift is itself a useful lesson: once a branch leaves cleanup mode and becomes the active working base, repo-memory files must be updated to describe the real baseline, not just preserve older guardrails verbatim
- Current highest-value product questions are now different from the earlier cleanup wave:
  1. whether profit determination is semantically consistent across producer, ranking, display, and retrospective calibration surfaces
  2. what actually blocks more curves from appearing in Curve Builder V2 (candidate gating, tag resolution, supported-universe limits, evidence thresholds, governance, or editor workflow)

### Limits of recovery
- Recent commit/file churn is not the same as a verified AI-processed ledger
- Do not assume every recently active file was touched by the same refactor wave
- If a precise historical list is needed, recover it from explicit notes/commits rather than inference

## Visual/Browser Findings
- None for this setup pass

---
*Update this file after every 2 view/browser/search operations*
*This prevents visual information from being lost*
