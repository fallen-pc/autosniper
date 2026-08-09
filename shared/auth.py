"""Password gate for the Streamlit dashboard.

The dashboard exposes pipeline controls that launch scrapers, rebuild models,
and write datasets, so the hosted deployment must not be reachable anonymously.

Environment variables:
----------------------
AUTOSNIPER_DASHBOARD_PASSWORD
    Shared password required before any page renders.
AUTOSNIPER_DASHBOARD_PASSWORD_SHA256
    Hex SHA-256 digest of the password, preferred over the plaintext variable.
AUTOSNIPER_DASHBOARD_AUTH_DISABLED
    Set to ``1`` to run without a gate. Only safe for a local, loopback-only
    session; on the hosted deployment the app refuses to render without a
    password unless this is set deliberately.
"""

from __future__ import annotations

import hashlib
import hmac
import os

import streamlit as st

from shared.runtime import is_vps_runtime

PASSWORD_ENV = "AUTOSNIPER_DASHBOARD_PASSWORD"
PASSWORD_HASH_ENV = "AUTOSNIPER_DASHBOARD_PASSWORD_SHA256"
AUTH_DISABLED_ENV = "AUTOSNIPER_DASHBOARD_AUTH_DISABLED"

SESSION_KEY = "_autosniper_dashboard_authenticated"

OPEN = "open"
GATE = "gate"
BLOCKED = "blocked"

_TRUTHY = {"1", "true", "yes", "on"}


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def configured_password_hash() -> str | None:
    """Return the expected password digest, or None when unset."""
    digest = os.getenv(PASSWORD_HASH_ENV, "").strip().lower()
    if digest:
        return digest
    password = os.getenv(PASSWORD_ENV, "")
    if password:
        return _sha256_hex(password)
    return None


def auth_disabled() -> bool:
    return os.getenv(AUTH_DISABLED_ENV, "").strip().lower() in _TRUTHY


def password_matches(candidate: str, expected_hash: str) -> bool:
    """Constant-time comparison of a candidate password against a digest."""
    return hmac.compare_digest(_sha256_hex(candidate), expected_hash.strip().lower())


def auth_requirement(
    *,
    vps_mode: bool,
    password_hash: str | None,
    disabled: bool,
) -> str:
    """Resolve how the gate should behave for the current configuration.

    ``OPEN`` renders the app, ``GATE`` demands the password, and ``BLOCKED``
    refuses to render because a hosted deployment has no password configured.
    """
    if disabled:
        return OPEN
    if password_hash:
        return GATE
    if vps_mode:
        return BLOCKED
    return OPEN


def _render_gate(expected_hash: str) -> None:
    st.title("AutoSniper")
    st.caption("Enter the dashboard password to continue.")
    with st.form("autosniper_dashboard_login"):
        candidate = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if candidate and password_matches(candidate, expected_hash):
            st.session_state[SESSION_KEY] = True
            st.rerun()
        st.error("Incorrect password.")


def require_dashboard_auth() -> None:
    """Stop page execution unless the visitor is authenticated."""
    expected_hash = configured_password_hash()
    requirement = auth_requirement(
        vps_mode=is_vps_runtime(),
        password_hash=expected_hash,
        disabled=auth_disabled(),
    )
    if requirement == OPEN:
        return
    if requirement == BLOCKED or expected_hash is None:
        st.error(
            "Dashboard authentication is not configured. Set "
            f"{PASSWORD_ENV} (or {PASSWORD_HASH_ENV}) in the service environment "
            "before serving this deployment."
        )
        st.stop()
    if st.session_state.get(SESSION_KEY):
        return
    _render_gate(expected_hash)
    st.stop()
