from __future__ import annotations

import streamlit as st

from shared.navigation import build_navigation


pages = build_navigation()
navigation = st.navigation(pages, position="hidden")
navigation.run()
