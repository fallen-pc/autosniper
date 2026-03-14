from __future__ import annotations

import streamlit as st

from shared.navigation import build_navigation


navigation = st.navigation(build_navigation(), position="sidebar")
navigation.run()
