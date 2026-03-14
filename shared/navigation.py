from __future__ import annotations

from collections import OrderedDict

import streamlit as st


def build_navigation() -> "OrderedDict[str, list[st.Page]]":
    # Keep the current page scripts intact and define the sidebar explicitly here.
    return OrderedDict(
        [
            (
                "SYSTEM",
                [
                    st.Page("DASHBOARD.py", title="Dashboard", default=True),
                    st.Page("pages/00_RADAR.py", title="Radar"),
                    st.Page("pages/3_ACTIVE_LISTINGS.py", title="Active Listings"),
                    st.Page("pages/01_EXCEPTIONS.py", title="Exceptions"),
                    # Existing drill-down flow relies on this page being routable.
                    st.Page("pages/02_DETAIL.py", title="Listing Detail"),
                ],
            ),
            (
                "PIPELINE",
                [
                    st.Page("pages/1_LINK_EXTRACTOR.py", title="Link Extractor"),
                    st.Page("pages/2_VEHICLE_DETAIL_EXTRACTOR.py", title="Detail Extractor"),
                    st.Page("pages/12_GRAYS_PIPELINE.py", title="Grays Pipeline"),
                    st.Page("pages/05_HEALTH.py", title="Health"),
                ],
            ),
            (
                "VALUATION",
                [
                    st.Page("pages/03_CURVES.py", title="Curves"),
                    st.Page("pages/13_CURVE_BUILDER.py", title="Curve Builder"),
                    st.Page("pages/04_MAPPINGS.py", title="Mappings"),
                    st.Page("pages/4_MASTER_DATABASE.py", title="Master Database"),
                ],
            ),
            (
                "AI",
                [
                    st.Page("pages/6_AI_ANALYSIS.py", title="AI Analysis"),
                    st.Page("pages/8_MODEL_ACCURACY.py", title="Model Accuracy"),
                    st.Page("pages/8_REAUCTION_MONITOR.py", title="Reaction Monitor"),
                ],
            ),
            (
                "INTELLIGENCE",
                [
                    st.Page("pages/8_MISSED_OPPORTUNITIES.py", title="Missed Opportunities"),
                    st.Page("pages/10_BIDDER_INSIGHTS.py", title="Bidder Insights"),
                    st.Page("pages/9_VEHICLE_REPAIRS.py", title="Vehicle Repairs"),
                ],
            ),
            (
                "COVERAGE",
                [
                    st.Page("pages/11_TOYOTA_COVERAGE.py", title="Toyota Coverage"),
                    st.Page("pages/7_AUTOTRADER_SCRAPER.py", title="Autotrader Scraper"),
                ],
            ),
        ]
    )
