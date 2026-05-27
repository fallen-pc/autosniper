from __future__ import annotations

import streamlit as st

from shared.navigation import build_navigation, render_sidebar_navigation


pages = build_navigation()
render_sidebar_navigation(pages)
navigation = st.navigation(pages, position="hidden")
navigation.run()
