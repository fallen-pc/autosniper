from __future__ import annotations

from collections import OrderedDict

import streamlit as st


NavigationSpec = "OrderedDict[str, list[tuple[str, str, bool]]]"

HIDDEN_ROUTABLE_GROUP = "_HIDDEN"
HIDDEN_ROUTABLE_PAGES: list[tuple[str, str, bool]] = []


def navigation_spec() -> NavigationSpec:
    return OrderedDict(
        [
            (
                "SYSTEM",
                [
                    ("DASHBOARD.py", "Dashboard", True),
                    ("pages/3_ACTIVE_LISTINGS.py", "Active Inventory", False),
                    ("pages/01_EXCEPTIONS.py", "Exceptions", False),
                    # Existing drill-down flow relies on this page being routable.
                    ("pages/02_DETAIL.py", "Listing Detail", False),
                ],
            ),
            (
                "PIPELINE",
                [
                    ("pages/12_GRAYS_PIPELINE.py", "Grays Pipeline", False),
                    ("pages/05_HEALTH.py", "Health", False),
                ],
            ),
            (
                "VALUATION",
                [
                    ("pages/03_CURVES.py", "Curves", False),
                    ("pages/15_CURVE_BUILDER_V2.py", "Curve Builder V2", False),
                    ("pages/14_CURVE_PIPELINE.py", "Curve Pipeline", False),
                ],
            ),
            (
                "AI",
                [
                    ("pages/6_AI_ANALYSIS.py", "AI Analysis", False),
                    ("pages/17_MODEL_PROOF.py", "Model Proof", False),
                ],
            ),
            (
                "INTELLIGENCE",
                [
                    ("pages/8_MISSED_OPPORTUNITIES.py", "Missed Opportunities", False),
                    ("pages/18_REPAIR_REVIEW.py", "Repair Review", False),
                    ("pages/19_REPAIR_PRICING.py", "Repair Pricing", False),
                ],
            ),
            (
                "OPERATIONS",
                [
                    ("pages/7_AUTOTRADER_SCRAPER.py", "Autotrader Scraper", False),
                ],
            ),
        ]
    )


def build_navigation() -> "OrderedDict[str, list[st.Page]]":
    # Keep the current page scripts intact and define the sidebar explicitly here.
    pages: "OrderedDict[str, list[st.Page]]" = OrderedDict()
    for group, entries in navigation_spec().items():
        pages[group] = [
            st.Page(path, title=title, default=default)
            for path, title, default in entries
        ]
    pages[HIDDEN_ROUTABLE_GROUP] = [
        st.Page(path, title=title, default=default)
        for path, title, default in HIDDEN_ROUTABLE_PAGES
    ]
    return pages


def render_sidebar_navigation(pages: "OrderedDict[str, list[st.Page]]") -> None:
    st.sidebar.markdown(
        """
        <style>
        .autosniper-nav-group {
            margin: 0.78rem 0 0.18rem;
            font-size: 0.66rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            text-transform: uppercase;
            color: rgba(229, 229, 229, 0.52);
        }
        section[data-testid="stSidebar"] [data-testid="stPageLink"] a {
            padding: 0.32rem 0.52rem;
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for group, entries in pages.items():
        if group == HIDDEN_ROUTABLE_GROUP:
            continue
        st.sidebar.markdown(f"<div class='autosniper-nav-group'>{group}</div>", unsafe_allow_html=True)
        for page in entries:
            st.sidebar.page_link(page, label=page.title)
