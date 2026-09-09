from __future__ import annotations

import streamlit as st

from shared.auth import require_dashboard_auth
from shared.navigation import build_navigation


pages = build_navigation()
navigation = st.navigation(pages, position="hidden")
# Register deep links before the login form can stop the run. Page code remains
# gated, and a successful sign-in can resume the originally requested page.
require_dashboard_auth()
navigation.run()
