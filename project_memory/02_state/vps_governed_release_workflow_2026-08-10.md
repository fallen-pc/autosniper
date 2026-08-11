# VPS governed release workflow - 2026-08-10

- The DigitalOcean VPS is AutoSniper's only production runtime and owns scraper output, the live repair queue, valuations, logs, browser sessions, scheduler state, and generated runtime CSVs.
- The laptop is development/review only. Approved code, curve/config data, repair decisions, and repair prices move one way from synchronized Git `main` to the VPS through `scripts/deploy_vps.ps1 -Release`.
- A governed release requires clean release paths and exact `origin/main` alignment; pauses VPS timers; backs up code and governed data separately; validates curve snapshots, repair pricing, and repair-decision schemas; runs VPS governance/readiness checks; verifies Streamlit health; records commit/hash/row-count status; and rolls back on failure.
- VPS navigation is runtime/read-only. Curve Builder, Curve Pipeline, Repair Review, Repair Pricing, and the interactive Autotrader Scraper remain local development surfaces.
- The live repair queue and all scraper/valuation/runtime outputs remain VPS-owned and are never overwritten by the governed release.
- The in-progress third curve batch remains separate and is not authorized for production release until committed, reviewed, merged, and included in a coherent `main` release.
- Curve-manifest validation treats LF and CRLF encodings as equivalent for the recorded SHA-256 provenance check, while still requiring `curves.csv` to exactly match its checked-out version snapshot and its governed row/tag counts. This keeps Windows-authored snapshots releasable from Linux CI/VPS without weakening content-drift detection.
