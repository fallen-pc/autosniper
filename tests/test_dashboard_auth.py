from pathlib import Path

import pytest

import shared.auth as dashboard_auth
from shared.auth import (
    AUTH_DISABLED_ENV,
    BLOCKED,
    GATE,
    OPEN,
    PASSWORD_ENV,
    PASSWORD_PBKDF2_ENV,
    SESSION_KEY,
    auth_disabled,
    auth_requirement,
    build_pbkdf2_verifier,
    configured_credential,
    password_matches,
)
from shared.validators import is_allowed_scrape_url


def _verifier(password: str) -> str:
    return build_pbkdf2_verifier(password, iterations=1000, salt=b"\x01\x02\x03\x04")


def test_hosted_runtime_without_password_is_blocked():
    assert auth_requirement(credential=None, disabled=False) == BLOCKED


def test_configured_password_gates_every_runtime():
    credential = _verifier("hunter2")
    assert auth_requirement(credential=credential, disabled=False) == GATE


def test_every_runtime_fails_closed_without_credentials():
    assert auth_requirement(credential=None, disabled=False) == BLOCKED


def test_explicit_local_opt_out_stays_open():
    assert auth_requirement(credential="hunter2", disabled=True) == OPEN


def test_pbkdf2_verifier_env_takes_precedence(monkeypatch):
    credential = _verifier("from-verifier")
    monkeypatch.setenv(PASSWORD_PBKDF2_ENV, credential)
    monkeypatch.setenv(PASSWORD_ENV, "from-plaintext")
    assert configured_credential() == credential


def test_malformed_pbkdf2_env_fails_closed(monkeypatch):
    monkeypatch.setenv(PASSWORD_PBKDF2_ENV, "600000$not-hex$also-not-hex")
    monkeypatch.setenv(PASSWORD_ENV, "plaintext-fallback")
    assert configured_credential() is None
    assert auth_requirement(credential=configured_credential(), disabled=False) == BLOCKED


def test_pbkdf2_verifier_accepts_only_the_right_password():
    credential = _verifier("hunter2")
    assert password_matches("hunter2", credential)
    assert not password_matches("hunter3", credential)


def test_pbkdf2_verifier_is_salted():
    first = build_pbkdf2_verifier("hunter2", iterations=1000)
    second = build_pbkdf2_verifier("hunter2", iterations=1000)
    assert first != second
    assert password_matches("hunter2", first)
    assert password_matches("hunter2", second)


def test_malformed_verifier_is_compared_as_plaintext():
    assert password_matches("not$a$verifier", "not$a$verifier")
    assert not password_matches("hunter2", "not$a$verifier")


def test_plaintext_password_is_compared_directly(monkeypatch):
    monkeypatch.delenv(PASSWORD_PBKDF2_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "hunter2")
    assert configured_credential() == "hunter2"
    assert password_matches("hunter2", "hunter2")
    assert not password_matches("hunter3", "hunter2")


def test_missing_password_configuration_returns_none(monkeypatch):
    monkeypatch.delenv(PASSWORD_PBKDF2_ENV, raising=False)
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    assert configured_credential() is None


def test_auth_disabled_requires_truthy_flag(monkeypatch):
    monkeypatch.setenv(AUTH_DISABLED_ENV, "0")
    assert not auth_disabled()
    monkeypatch.setenv(AUTH_DISABLED_ENV, "yes")
    assert auth_disabled()


def test_unconfigured_gate_stops_page_execution(monkeypatch):
    class GateStopped(RuntimeError):
        pass

    errors: list[str] = []
    monkeypatch.delenv(PASSWORD_PBKDF2_ENV, raising=False)
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    monkeypatch.delenv(AUTH_DISABLED_ENV, raising=False)
    monkeypatch.setattr(dashboard_auth.st, "error", errors.append)
    monkeypatch.setattr(
        dashboard_auth.st,
        "stop",
        lambda: (_ for _ in ()).throw(GateStopped()),
    )

    with pytest.raises(GateStopped):
        dashboard_auth.require_dashboard_auth()

    assert errors and "authentication is not configured" in errors[0]


def test_authenticated_session_skips_login_form(monkeypatch):
    monkeypatch.setenv(PASSWORD_PBKDF2_ENV, _verifier("saved-password"))
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    monkeypatch.delenv(AUTH_DISABLED_ENV, raising=False)
    monkeypatch.setattr(dashboard_auth.st, "session_state", {SESSION_KEY: True})
    monkeypatch.setattr(
        dashboard_auth,
        "_render_gate",
        lambda credential: pytest.fail(f"unexpected login form for {credential}"),
    )

    dashboard_auth.require_dashboard_auth()


def test_devcontainer_uses_authenticated_entrypoint_and_security_defaults():
    config_text = Path(".devcontainer/devcontainer.json").read_text(encoding="utf-8")
    assert '"server": "streamlit run app.py"' in config_text
    assert "enableCORS false" not in config_text
    assert "enableXsrfProtection false" not in config_text


def test_scrape_url_allowlist_accepts_expected_hosts():
    allowed = ("autotrader.com.au",)
    assert is_allowed_scrape_url("https://www.autotrader.com.au/for-sale/used", allowed)
    assert is_allowed_scrape_url("https://autotrader.com.au/", allowed)


def test_scrape_url_allowlist_rejects_other_targets():
    allowed = ("autotrader.com.au",)
    assert not is_allowed_scrape_url("http://www.autotrader.com.au/", allowed)
    assert not is_allowed_scrape_url("https://autotrader.com.au.evil.test/", allowed)
    assert not is_allowed_scrape_url("https://169.254.169.254/latest/meta-data", allowed)
    assert not is_allowed_scrape_url("file:///etc/passwd", allowed)
    assert not is_allowed_scrape_url("", allowed)
