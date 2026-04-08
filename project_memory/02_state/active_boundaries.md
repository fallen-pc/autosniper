# Active Boundaries

These files and areas remain high sensitivity and are not casual cleanup targets:

- `scripts/process_curve_candidates.py`
- `scripts/atomic_csv.py`
- scraper and extractor core files
- adjacent operator pages that directly steer scraper and curve workflows
- broad coordinator files such as `governance/run_checks.py` when the requested change does not truly require them

Important rule:

- small runtime fixes that were previously allowed in these areas do not reopen them for general refactor work
- any deliberate work in these areas should be logged in `project_memory/02_state/` first
