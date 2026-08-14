from pathlib import Path


def test_embedded_remote_script_is_normalized_to_lf_before_encoding():
    script = Path("scripts/deploy_vps.ps1").read_text(encoding="utf-8")

    normalization = '$normalizedRemoteScript = $remoteScript -replace "`r`n?", "`n"'
    encoding = "GetBytes($normalizedRemoteScript)"

    assert normalization in script
    assert encoding in script
    assert script.index(normalization) < script.index(encoding)


def test_remote_governance_skips_git_delta_for_archive_deploy():
    script = Path("scripts/deploy_vps.ps1").read_text(encoding="utf-8")

    command = 'scripts/governance_checks.py check --skip-dataset-delta'
    assert command in script

def test_deployment_backups_are_private_and_exclude_browser_sessions():
    script = Path("scripts/deploy_vps.ps1").read_text(encoding="utf-8")

    assert "umask 077" in script
    assert 'chmod 700 "$backup_dir"' in script
    assert "--exclude='./autotrader_isolated/output'" in script
    assert 'chmod 600 "$backup"' in script
    assert 'chmod 600 "$governed_backup"' in script
