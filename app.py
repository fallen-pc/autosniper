from __future__ import annotations

import streamlit as st

from shared.auth import require_dashboard_auth
from shared.navigation import build_navigation


require_dashboard_auth()
pages = build_navigation()
navigation = st.navigation(pages, position="hidden")
navigation.run()
