from collections import OrderedDict
from pathlib import Path
import runpy

import pytest

import shared.auth as auth
import shared.navigation as navigation


def test_cold_dashboard_route_resolves_and_remains_password_gated(monkeypatch):
    from streamlit.commands import navigation as streamlit_navigation
    from streamlit.runtime.pages_manager import PagesManager
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("AUTOSNIPER_VPS_MODE", "1")
    monkeypatch.setenv(auth.AUTH_DISABLED_ENV, "0")
    monkeypatch.setenv(auth.PASSWORD_ENV, "local-route-check")
    monkeypatch.delenv(auth.PASSWORD_PBKDF2_ENV, raising=False)
    # Exercise the actual legacy scan that runs before app.py on a cold server.
    monkeypatch.setattr(PagesManager, "uses_pages_directory", None)
    missing_pages = []
    monkeypatch.setattr(streamlit_navigation, "send_page_not_found", lambda ctx: missing_pages.append(True))
    app = AppTest.from_file("app.py", default_timeout=30)
    app.switch_page("pages/04_DASHBOARD.py").run()
    assert not app.exception
    assert not missing_pages
    assert [title.value for title in app.title] == ["AutoSniper"]
    assert app.text_input[0].label == "Password"
    assert not app.metric
    app.text_input[0].set_value("wrong-password")
    app.button[0].click().run()
    assert any(error.value == "Incorrect password." for error in app.error)
    assert not app.metric


@pytest.mark.parametrize("vps_mode", [False, True])
def test_sidebar_links_use_registered_session_routes(monkeypatch, vps_mode):
    spec = navigation.navigation_spec(vps_mode=vps_mode)
    links = []
    markup = []
    monkeypatch.setattr(navigation, "navigation_spec", lambda: spec)
    monkeypatch.setattr(navigation.st, "navigation", lambda pages, **kw: None)
    monkeypatch.setattr(navigation, "require_dashboard_auth", lambda: None)
    monkeypatch.setattr(navigation.st.sidebar, "markdown", lambda text, **kw: markup.append(text))
    monkeypatch.setattr(navigation.st.sidebar, "page_link", lambda path, **kw: links.append((path, kw["label"])))

    navigation.render_sidebar_navigation()

    assert links == [(path, title) for entries in spec.values() for path, title, _ in entries]
    assert not any("<a " in text for text in markup)


def test_direct_page_registers_routes_before_its_login_gate(monkeypatch):
    class LoginRequired(Exception):
        pass

    events = []
    pages = OrderedDict(SYSTEM=[object()])
    monkeypatch.setattr(navigation, "build_navigation", lambda: pages)
    monkeypatch.setattr(
        navigation.st, "navigation",
        lambda registered, **kwargs: events.append((registered, kwargs)),
    )

    def require_login():
        assert events == [(pages, {"position": "hidden"})]
        raise LoginRequired

    monkeypatch.setattr(navigation, "require_dashboard_auth", require_login)
    with pytest.raises(LoginRequired):
        navigation.render_sidebar_navigation()


@pytest.mark.parametrize("authenticated", [False, True])
def test_routes_are_available_at_login_but_page_execution_stays_gated(monkeypatch, authenticated):
    class LoginRequired(Exception):
        pass

    events = []
    pages = OrderedDict(SYSTEM=[object()])

    class SelectedPage:
        def run(self):
            events.append("page executed")

    def register_routes(registered, **kwargs):
        assert registered is pages
        assert kwargs["position"] == "hidden"
        events.append("routes registered")
        return SelectedPage()

    def require_login():
        assert events == ["routes registered"]
        events.append("authentication checked")
        if not authenticated:
            raise LoginRequired

    monkeypatch.setattr(navigation, "build_navigation", lambda: pages)
    monkeypatch.setattr(navigation.st, "navigation", register_routes)
    monkeypatch.setattr(auth, "require_dashboard_auth", require_login)

    if authenticated:
        runpy.run_path(str(Path("app.py")))
        assert events == ["routes registered", "authentication checked", "page executed"]
    else:
        with pytest.raises(LoginRequired):
            runpy.run_path(str(Path("app.py")))
        assert events == ["routes registered", "authentication checked"]
