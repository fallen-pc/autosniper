from collections import OrderedDict
from pathlib import Path
import runpy

import pytest

import shared.auth as auth
import shared.navigation as navigation


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
