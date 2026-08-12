from pathlib import Path


def test_embedded_remote_script_is_normalized_to_lf_before_encoding():
    script = Path("scripts/deploy_vps.ps1").read_text(encoding="utf-8")

    normalization = '$normalizedRemoteScript = $remoteScript -replace "`r`n?", "`n"'
    encoding = "GetBytes($normalizedRemoteScript)"

    assert normalization in script
    assert encoding in script
    assert script.index(normalization) < script.index(encoding)
