from __future__ import annotations

from collections import OrderedDict
import html
import os
from pathlib import Path
import re

import streamlit as st


NavigationSpec = "OrderedDict[str, list[tuple[str, str, bool]]]"

HIDDEN_ROUTABLE_GROUP = "_HIDDEN"
HIDDEN_ROUTABLE_PAGES: list[tuple[str, str, bool]] = []


def _is_vps_runtime() -> bool:
    explicit = os.getenv("AUTOSNIPER_VPS_MODE", "").strip().lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    return Path(__file__).resolve().parents[1] == Path("/opt/autosniper")


def navigation_spec(*, vps_mode: bool | None = None) -> NavigationSpec:
    if vps_mode is None:
        vps_mode = _is_vps_runtime()
    system_pages = [
        ("DASHBOARD.py", "Dashboard", not vps_mode),
        ("pages/3_ACTIVE_LISTINGS.py", "Active Inventory", False),
        ("pages/01_EXCEPTIONS.py", "Exceptions", False),
        # Existing drill-down flow relies on this page being routable.
        ("pages/02_DETAIL.py", "Listing Detail", False),
    ]
    if vps_mode:
        system_pages.insert(0, ("pages/00_SCRAPER_OPERATIONS.py", "Scraper Operations", True))

    return OrderedDict(
        [
            (
                "SYSTEM",
                system_pages,
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


def render_sidebar_navigation() -> None:
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
        .autosniper-nav-link {
            display: block;
            padding: 0.32rem 0.52rem;
            border-radius: 8px;
            color: inherit !important;
            text-decoration: none !important;
        }
        .autosniper-nav-link:hover {
            background: rgba(31, 166, 255, 0.10);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    for group, entries in navigation_spec().items():
        st.sidebar.markdown(f"<div class='autosniper-nav-group'>{group}</div>", unsafe_allow_html=True)
        for path, title, is_default in entries:
            filename = path.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
            url_path = re.sub(r"^\d+_?", "", filename)
            href = "/" if is_default else f"/{url_path}"
            st.sidebar.markdown(
                f'<a class="autosniper-nav-link" href="{html.escape(href, quote=True)}" '
                f'target="_self">{html.escape(title)}</a>',
                unsafe_allow_html=True,
            )
