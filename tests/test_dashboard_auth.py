import hashlib

from shared.auth import (
    AUTH_DISABLED_ENV,
    BLOCKED,
    GATE,
    OPEN,
    PASSWORD_ENV,
    PASSWORD_HASH_ENV,
    auth_disabled,
    auth_requirement,
    configured_password_hash,
    password_matches,
)
from shared.validators import is_allowed_scrape_url


def test_hosted_runtime_without_password_is_blocked():
    assert auth_requirement(vps_mode=True, password_hash=None, disabled=False) == BLOCKED


def test_configured_password_gates_every_runtime():
    digest = hashlib.sha256(b"hunter2").hexdigest()
    assert auth_requirement(vps_mode=True, password_hash=digest, disabled=False) == GATE
    assert auth_requirement(vps_mode=False, password_hash=digest, disabled=False) == GATE


def test_local_runtime_and_explicit_opt_out_stay_open():
    assert auth_requirement(vps_mode=False, password_hash=None, disabled=False) == OPEN
    assert auth_requirement(vps_mode=True, password_hash="abc", disabled=True) == OPEN


def test_password_hash_env_takes_precedence(monkeypatch):
    digest = hashlib.sha256(b"from-hash").hexdigest()
    monkeypatch.setenv(PASSWORD_HASH_ENV, digest.upper())
    monkeypatch.setenv(PASSWORD_ENV, "from-plaintext")
    assert configured_password_hash() == digest


def test_plaintext_password_is_hashed(monkeypatch):
    monkeypatch.delenv(PASSWORD_HASH_ENV, raising=False)
    monkeypatch.setenv(PASSWORD_ENV, "hunter2")
    expected = hashlib.sha256(b"hunter2").hexdigest()
    assert configured_password_hash() == expected
    assert password_matches("hunter2", expected)
    assert not password_matches("hunter3", expected)


def test_missing_password_configuration_returns_none(monkeypatch):
    monkeypatch.delenv(PASSWORD_HASH_ENV, raising=False)
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    assert configured_password_hash() is None


def test_auth_disabled_requires_truthy_flag(monkeypatch):
    monkeypatch.setenv(AUTH_DISABLED_ENV, "0")
    assert not auth_disabled()
    monkeypatch.setenv(AUTH_DISABLED_ENV, "yes")
    assert auth_disabled()


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
