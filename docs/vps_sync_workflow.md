# VPS Sync Workflow

The DigitalOcean VPS is the live AutoSniper runtime. It owns scraper output, logs, browser sessions, and other generated data. The laptop is the development workspace for application code.

## Publish application changes

1. Make and test the intended changes locally.
2. Commit only the intended source slice.
3. From the repository root, run:

   ```powershell
   .\scripts\deploy_vps.ps1 -Push
   ```

The command deploys the exact current Git commit, verifies the Streamlit health endpoint, records the deployed commit in `/opt/autosniper/status/deployed_commit.txt`, and then pushes that commit to the configured Git upstream.

Deployment stops when deployable files have uncommitted changes. This prevents unrelated worktree edits from leaking onto the live VPS.

## Explicit committed-version deployment

To redeploy the current committed version while intentionally leaving local edits unpublished:

```powershell
.\scripts\deploy_vps.ps1 -DeployCommittedHead
```

Use `-DryRun` with either command to validate the deployment configuration without changing the VPS.

Runtime data under `CSV_data`, `curves`, `artifacts`, `logs`, `output`, `outputs`, `status`, virtual environments, and the authenticated Autotrader output directory is preserved.
