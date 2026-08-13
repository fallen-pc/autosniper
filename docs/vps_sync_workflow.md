# VPS Release And Sync Workflow

The DigitalOcean VPS is the only live AutoSniper runtime. It owns scraper output, the live repair queue, valuations, logs, browser sessions, scheduler state, and other generated data. Laptop production tasks must remain disabled.

The laptop checkout is the development and review workspace. Approved code, curves, curve configuration, repair decisions, and repair prices reach production only through a governed release from synchronized `main`.

| Data | Authority | Direction |
|---|---|---|
| Application code and `config/` | Git `main` | Git to VPS |
| Curves and curve version history | Git `main` | Git to VPS through `-Release` |
| Approved repair decisions and repair pricing | Git `main` | Git to VPS through `-Release` |
| Scraper data, live repair queue, valuations, logs and status | VPS | Never overwritten by a release |

The VPS navigation intentionally omits Curve Builder, Curve Pipeline, Repair Review, Repair Pricing, and the interactive Autotrader Scraper. Those are development/authoring surfaces, not production controls.

## Governed production release

After the intended work is tested, committed, merged to `main`, and pushed:

```powershell
git switch main
git pull --ff-only
.\scripts\deploy_vps.ps1 -Release
```

The release command refuses to run unless:

- the current branch is `main`;
- local `HEAD` exactly matches `origin/main`;
- deployable code and governed data paths are clean;
- no scheduled AutoSniper job is active; and
- local governed curve, pricing, decision, and version-manifest validation passes.

On the VPS it pauses the daily/hourly timers, backs up code and governed data separately, validates the staged release, runs governance and readiness checks, restarts Streamlit, verifies health, and restores the previous release if activation fails. A successful release writes:

```text
/opt/autosniper/status/deployed_commit.txt
/opt/autosniper/status/governed_data_release.json
```

The JSON marker records the commit, file hashes, byte sizes, and CSV row counts so production code and governed inputs can be reconciled without guesswork.

## Publish application changes

1. Make and test the intended changes locally.
2. Commit only the intended source slice.
3. From the repository root, run:

   ```powershell
   .\scripts\deploy_vps.ps1 -Push
   ```

This remains available for code-only maintenance. It deploys the exact current Git commit, verifies the Streamlit health endpoint, records the deployed commit in `/opt/autosniper/status/deployed_commit.txt`, and then pushes that commit to the configured Git upstream. It does not publish curves or repair data.

Deployment stops when deployable files have uncommitted changes. This prevents unrelated worktree edits from leaking onto the live VPS.

## Explicit committed-version deployment

To redeploy the current committed version while intentionally leaving local edits unpublished:

```powershell
.\scripts\deploy_vps.ps1 -DeployCommittedHead
```

Use `-DryRun` with either command to validate the deployment configuration without changing the VPS.

Runtime data under `CSV_data`, `curves`, `artifacts`, `logs`, `output`, `outputs`, `status`, virtual environments, and the authenticated Autotrader output directory is preserved.

For a governed production release, use `-Release`; do not manually copy individual curve or repair CSV files to the VPS.
