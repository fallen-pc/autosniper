# New Vehicle Expansion Workflow

Use this checklist when adding a new vehicle family, trim, series, fuel, body, or transmission lane to AutoSniper.

## Source-of-truth roles

- `config/allowed_variants.csv` gates which raw listings can receive a narrow canonical tag.
- `config/curve_groups_v2.csv` maps detailed match tags onto V2 base curve tags. This is the V2 mapping layer used by valuation.
- `CSV_data/restricted/curves.csv` stores the saved retail resale curve values. This is the valuation data source.
- `config/supported_curve_universe_v1.csv` is the approved/selectable V2 base-curve registry used by Curve Builder V2 and curve-contract tests. Despite the `v1` filename, it is not the old valuation path.
- `CSV_data/restricted/versions/curves_manifest.csv` and `CSV_data/restricted/versions/curves_<version>.csv` version governed curve changes.
- Curve Builder V2 is the only supported curve-pricing pipeline. Autotrader evidence is comparison/follow-up only and must not fit or overwrite retail resale curve prices.

## Preflight

1. Confirm the task is a deliberate expansion, not a tagging repair, evidence-alignment check, or repricing review.
2. Identify the narrow lane: make, model, trim, series/platform, body, fuel, and transmission.
3. Check that materially different trims, engines, drivetrains, generations, WOVR/repairable rows, and body styles are excluded.
4. Confirm the retail evidence source. Private Carsales/Apify evidence should set retail curve prices; Grays sold history is buy-side spread and priority evidence, not retail repricing evidence.
5. Confirm Autotrader evidence, if present, is being used only to check the lane and queue follow-up scrapes, not to price the curve.

## Implementation Checklist

1. Add or tighten canonical recognition in `shared/canonical_tagging.py` only when the existing parser cannot identify the lane.
2. Add the lane to `config/allowed_variants.csv` with explicit include and exclude terms.
3. Add the match-tag to V2 base-curve mapping in `config/curve_groups_v2.csv`.
4. Add or update the V2 base-curve registry row in `config/supported_curve_universe_v1.csv` if the lane should be selectable/live in Curve Builder V2.
5. Add curve rows to `CSV_data/restricted/curves.csv` using the standard grid unless the lane has an explicit governed reason for additional high-km buckets.
6. Snapshot the curve version and update `CSV_data/restricted/versions/curves_manifest.csv`.
7. Update `CHANGELOG.md` and `project_memory/02_state/recent_changes.md`.
8. Add focused canonical-tagging and curve-contract tests for the lane and its most important exclusions.
9. Rebuild restricted datasets when active/sold coverage should change.
10. Re-run or refresh AI valuations when active AI Analysis coverage should change.
11. Check AI Analysis and Missed Opportunities for the new lane when active or historical rows exist.

## Verification

Run the focused tests for the changed lane, then the normal repo checks:

```powershell
venv\Scripts\python.exe -m pytest -q tests/test_canonical_tagging_recent_scrape_curves.py tests/test_curves.py
venv\Scripts\python.exe -m pytest -q
venv\Scripts\python.exe scripts\readiness_smoke.py
venv\Scripts\python.exe scripts\governance_checks.py check
venv\Scripts\python.exe scripts\project_memory.py check
```

Before committing, stage intentionally and run:

```powershell
venv\Scripts\python.exe scripts\project_memory.py check --staged
venv\Scripts\python.exe scripts\check_commit_hygiene.py --staged
```

If a governed curve slice must include source/config plus `CSV_data/restricted/curves.csv`, its version snapshot, and manifest together, the normal hygiene check will report a mixed source/artifact commit. Use `AUTOSNIPER_ALLOW_MIXED_COMMIT=1` only for that intentional governed curve slice after the non-overridden failure is understood.

## Done Criteria

A new lane is not complete until:

- the raw listings receive the intended narrow canonical tag,
- materially different rows are excluded,
- the match tag resolves to the intended V2 base curve,
- the saved curve exists and passes governance,
- the V2 base-curve registry reflects the intended selectable/live status,
- governed curve versioning is present,
- active/sold restricted outputs are rebuilt where relevant,
- AI Analysis and Missed Opportunities have been checked when data exists,
- focused tests, full pytest, readiness, governance, and project-memory checks pass.
