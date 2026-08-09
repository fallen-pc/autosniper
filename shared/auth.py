"""Password gate for the Streamlit dashboard.

The dashboard exposes pipeline controls that launch scrapers, rebuild models,
and write datasets, so the hosted deployment must not be reachable anonymously.

Environment variables:
----------------------
AUTOSNIPER_DASHBOARD_PASSWORD
    Shared password required before any page renders.
AUTOSNIPER_DASHBOARD_PASSWORD_PBKDF2
    PBKDF2-HMAC-SHA256 verifier for the password in
    ``<iterations>$<salt_hex>$<derived_hex>`` form, preferred over the
    plaintext variable. Build one with :func:`build_pbkdf2_verifier`.
AUTOSNIPER_DASHBOARD_AUTH_DISABLED
    Set to ``1`` to run without a gate. Only safe for a local, loopback-only
    session; on the hosted deployment the app refuses to render without a
    password unless this is set deliberately.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

import streamlit as st

from shared.runtime import is_vps_runtime

PASSWORD_ENV = "AUTOSNIPER_DASHBOARD_PASSWORD"
PASSWORD_PBKDF2_ENV = "AUTOSNIPER_DASHBOARD_PASSWORD_PBKDF2"
AUTH_DISABLED_ENV = "AUTOSNIPER_DASHBOARD_AUTH_DISABLED"

SESSION_KEY = "_autosniper_dashboard_authenticated"

OPEN = "open"
GATE = "gate"
BLOCKED = "blocked"

PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16

_TRUTHY = {"1", "true", "yes", "on"}


def build_pbkdf2_verifier(
    password: str,
    *,
    iterations: int = PBKDF2_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    """Return a ``<iterations>$<salt_hex>$<derived_hex>`` verifier string."""
    salt_bytes = salt if salt is not None else secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, iterations)
    return f"{iterations}${salt_bytes.hex()}${derived.hex()}"


def _parse_pbkdf2_verifier(verifier: str) -> tuple[int, bytes, str] | None:
    parts = verifier.split("$")
    if len(parts) != 3:
        return None
    iterations_text, salt_hex, derived_hex = parts
    try:
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return None
    if iterations <= 0 or not salt or not derived_hex:
        return None
    return iterations, salt, derived_hex.strip().lower()


def configured_credential() -> str | None:
    """Return the configured password verifier or plaintext, or None when unset."""
    verifier = os.getenv(PASSWORD_PBKDF2_ENV, "").strip()
    if verifier:
        return verifier
    password = os.getenv(PASSWORD_ENV, "")
    return password or None


def auth_disabled() -> bool:
    return os.getenv(AUTH_DISABLED_ENV, "").strip().lower() in _TRUTHY


def password_matches(candidate: str, credential: str) -> bool:
    """Constant-time check of a candidate against a verifier or plaintext secret."""
    parsed = _parse_pbkdf2_verifier(credential)
    if parsed is not None:
        iterations, salt, derived_hex = parsed
        derived = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(derived.hex(), derived_hex)
    return hmac.compare_digest(candidate, credential)


def auth_requirement(
    *,
    vps_mode: bool,
    credential: str | None,
    disabled: bool,
) -> str:
    """Resolve how the gate should behave for the current configuration.

    ``OPEN`` renders the app, ``GATE`` demands the password, and ``BLOCKED``
    refuses to render because a hosted deployment has no password configured.
    """
    if disabled:
        return OPEN
    if credential:
        return GATE
    if vps_mode:
        return BLOCKED
    return OPEN


def _render_gate(credential: str) -> None:
    st.title("AutoSniper")
    st.caption("Enter the dashboard password to continue.")
    with st.form("autosniper_dashboard_login"):
        candidate = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if candidate and password_matches(candidate, credential):
            st.session_state[SESSION_KEY] = True
            st.rerun()
        st.error("Incorrect password.")


def require_dashboard_auth() -> None:
    """Stop page execution unless the visitor is authenticated."""
    credential = configured_credential()
    requirement = auth_requirement(
        vps_mode=is_vps_runtime(),
        credential=credential,
        disabled=auth_disabled(),
    )
    if requirement == OPEN:
        return
    if requirement == BLOCKED or credential is None:
        st.error(
            "Dashboard authentication is not configured. Set "
            f"{PASSWORD_ENV} (or {PASSWORD_PBKDF2_ENV}) in the service environment "
            "before serving this deployment."
        )
        st.stop()
    if st.session_state.get(SESSION_KEY):
        return
    _render_gate(credential)
    st.stop()
