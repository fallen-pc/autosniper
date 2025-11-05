"""Shared styling utilities for the AutoSniper Streamlit apps."""

from __future__ import annotations

import base64
from pathlib import Path
import textwrap
from typing import Optional

import streamlit as st


_BASE_STYLES = textwrap.dedent(
    """
    <style>
    :root {
        --autosniper-bg: #ffffff;
        --autosniper-surface: #ffffff;
        --autosniper-panel: #f2ecdb;
        --autosniper-highlight: #d8caa3;
        --autosniper-primary: #0d022d;
        --autosniper-primary-dark: #07031a;
        --autosniper-accent: #284735;
        --autosniper-text: #1f1c17;
        --autosniper-muted: #403030;
        --autosniper-success: #284735;
        --autosniper-warning: #b6a77c;
        --autosniper-danger: #3c352f;
        --autosniper-border: rgba(13, 2, 45, 0.22);
        --autosniper-shadow: rgba(13, 2, 45, 0.18);
        --autosniper-banner-navy: #07031a;
    }
    [data-testid="stAppViewContainer"] {
        background: var(--autosniper-bg);
        color: var(--autosniper-text);
        font-family: "Segoe UI", Arial, sans-serif;
    }
    [data-testid="stAppViewContainer"] * {
        color: inherit;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(185deg, #0a0424 0%, var(--autosniper-banner-navy) 100%);
        color: #f5f7fb;
        border-right: 1px solid rgba(255, 255, 255, 0.08);
    }
    [data-testid="stSidebar"] * {
        color: inherit;
    }
    .block-container {
        padding-top: 1.25rem;
        padding-bottom: 2.5rem;
    }
    h1, h2, h3 {
        color: var(--autosniper-primary);
        margin-bottom: 1rem;
        letter-spacing: -0.01em;
    }
    h1 {
        font-size: clamp(2.4rem, 2.2vw + 1.6rem, 3rem);
        font-weight: 800;
    }
    h2 {
        font-size: clamp(1.7rem, 1.5vw + 1.2rem, 2.2rem);
        font-weight: 700;
    }
    h3 {
        font-size: 1.25rem;
        font-weight: 600;
        letter-spacing: 0.02em;
    }
    .autosniper-tagline {
        font-size: 1.05rem;
        color: var(--autosniper-accent);
        max-width: 760px;
        margin-top: -0.35rem;
        margin-bottom: 1.6rem;
        line-height: 1.55;
    }
    .autosniper-section {
        background: linear-gradient(135deg, rgba(242, 236, 219, 0.95) 0%, rgba(216, 202, 163, 0.9) 100%);
        border-radius: 16px;
        border: 1px solid rgba(40, 71, 53, 0.32);
        box-shadow: 0 16px 36px rgba(13, 2, 45, 0.18);
        padding: 1.5rem 1.75rem;
        margin-bottom: 1.5rem;
    }
    .autosniper-section .section-title {
        font-size: 1.2rem;
        font-weight: 700;
    }
    .autosniper-section .section-subtitle {
        color: rgba(40, 71, 53, 0.78);
        margin-top: 0.35rem;
    }
    .autosniper-chip {
        display: inline-flex;
        align-items: center;
        padding: 0.35rem 0.75rem;
        background: rgba(182, 167, 124, 0.24);
        border-radius: 999px;
        color: var(--autosniper-primary);
        font-weight: 600;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
    }
    .stButton>button {
        background: var(--autosniper-primary);
        color: #f5f7fb;
        border-radius: 10px;
        border: none;
        padding: 0.65rem 1.3rem;
        font-weight: 600;
        box-shadow: 0 12px 28px rgba(13, 2, 45, 0.28);
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        background: var(--autosniper-primary-dark);
        transform: translateY(-1px);
        box-shadow: 0 16px 34px rgba(13, 2, 45, 0.34);
    }
    .autosniper-banner {
        display: flex;
        justify-content: center;
        margin: 1.5rem 0 2.5rem;
    }
    .autosniper-banner img {
        width: min(100%, 1600px);
        height: auto;
        border-radius: 18px;
        box-shadow: 0 18px 36px rgba(13, 2, 45, 0.24);
        clip-path: inset(8px round 18px);
    }
    .rail-logo {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 64px;
        height: 64px;
        border-radius: 20px;
        background: transparent;
        border: none;
        box-shadow: none;
    }
    .crosshair {
        position: relative;
        width: 40px;
        height: 40px;
        border: 2px solid rgba(40, 71, 53, 0.85);
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }
    .crosshair::before,
    .crosshair::after {
        content: "";
        position: absolute;
        background: rgba(214, 202, 163, 0.94);
    }
    .crosshair::before {
        width: 1px;
        height: 34px;
    }
    .crosshair::after {
        width: 34px;
        height: 1px;
    }
    .crosshair .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: rgba(40, 71, 53, 0.9);
        box-shadow: 0 0 12px rgba(13, 2, 45, 0.45);
    }
    .stDataFrame {
        border-radius: 14px;
        box-shadow: 0 22px 40px rgba(13, 2, 45, 0.2);
        border: 1px solid rgba(40, 71, 53, 0.32);
        background: rgba(242, 236, 219, 0.92);
        overflow: hidden;
    }
    .stAlert {
        border-radius: 14px;
        border: 1px solid rgba(40, 71, 53, 0.38);
        box-shadow: 0 12px 26px rgba(13, 2, 45, 0.16);
        background: rgba(216, 202, 163, 0.18);
        color: var(--autosniper-text);
    }
    [data-testid="stMetric"] {
        border-radius: 14px;
        border: 1px solid var(--autosniper-border);
        background: rgba(242, 236, 219, 0.92);
        box-shadow: 0 12px 26px rgba(13, 2, 45, 0.16);
        padding: 1.1rem 1.25rem;
    }
    [data-testid="stMetric"] > div {
        justify-content: flex-start;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--autosniper-muted);
    }
    [data-testid="stMetricValue"] {
        font-size: 1.7rem;
        font-weight: 700;
        color: var(--autosniper-primary);
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.95rem;
        font-weight: 600;
    }
    .autosniper-metric-row {
        display: grid;
        gap: 1.1rem;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        margin-bottom: 1.4rem;
    }
    .autosniper-panel {
        background: linear-gradient(135deg, rgba(242, 236, 219, 0.94), rgba(216, 202, 163, 0.85));
        border-radius: 18px;
        border: 1px solid var(--autosniper-border);
        box-shadow: 0 16px 32px rgba(13, 2, 45, 0.2);
        padding: 1.5rem 1.75rem;
        margin-bottom: 1.5rem;
    }
    .autosniper-panel h3 {
        margin-top: 0;
        margin-bottom: 0.65rem;
    }
    .autosniper-panel p {
        color: var(--autosniper-muted);
        margin-bottom: 0;
    }
    .stCaption, .stMarkdown p {
        line-height: 1.55;
    }
    .stExpander {
        border-radius: 16px;
        border: 1px solid rgba(40, 71, 53, 0.3);
        background: rgba(242, 236, 219, 0.9);
        box-shadow: 0 18px 32px rgba(13, 2, 45, 0.16);
    }
    hr {
        border: none;
        border-top: 1px solid rgba(182, 167, 124, 0.46);
        margin: 1.8rem 0;
    }
    .ai-card-header {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1.5rem;
        padding: 1.6rem 1.9rem;
        background: linear-gradient(135deg, rgba(242, 236, 219, 0.96), rgba(216, 202, 163, 0.88));
        border: 1px solid rgba(40, 71, 53, 0.38);
        border-radius: 20px;
        box-shadow: 0 24px 48px rgba(13, 2, 45, 0.22);
        margin-bottom: 1.4rem;
    }
    .ai-card-title-group {
        display: flex;
        flex-direction: column;
        gap: 0.55rem;
        min-width: 260px;
    }
    .ai-card-title {
        font-size: clamp(2.1rem, 2vw + 1.3rem, 2.7rem);
        font-weight: 800;
        color: var(--autosniper-primary);
        letter-spacing: -0.01em;
    }
    .ai-card-subtitle {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
    }
    .ai-card-subtitle span {
        background: var(--autosniper-panel);
        border-radius: 40px;
        padding: 0.35rem 0.8rem;
        font-size: 0.92rem;
        font-weight: 600;
        color: var(--autosniper-primary);
        letter-spacing: 0.02em;
    }
    .ai-card-metric {
        min-width: 200px;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 0.45rem;
    }
    .ai-card-metric-label {
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--autosniper-muted);
    }
    .ai-card-metric-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--autosniper-primary);
    }
    .ai-card-link {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        color: var(--autosniper-accent);
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        font-size: 0.8rem;
    }
    .ai-card-link:hover {
        color: var(--autosniper-primary-dark);
    }
    </style>
    """
)


def clean_html(html: str) -> str:
    """Dedent HTML snippets so Streamlit renders them as markup."""
    return textwrap.dedent(html).strip()


def inject_global_styles() -> None:
    """Inject global CSS styles; safe to call multiple times."""
    st.markdown(_BASE_STYLES, unsafe_allow_html=True)


def render_html(html: str) -> None:
    """Helper to inject CSS (if needed) and render cleaned HTML."""
    inject_global_styles()
    st.markdown(clean_html(html), unsafe_allow_html=True)


def section_heading(title: str, subtitle: str | None = None) -> None:
    """Render a decorated section heading card."""
    inject_global_styles()
    subtitle_html = f"<p class='section-subtitle'>{subtitle}</p>" if subtitle else ""
    st.markdown(
        clean_html(
            f"""
            <div class="autosniper-section">
                <div class="section-title">{title}</div>
                {subtitle_html}
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def info_chip(label: str) -> None:
    """Render a small pill-style chip."""
    inject_global_styles()
    st.markdown(f"<span class='autosniper-chip'>{label}</span>", unsafe_allow_html=True)


_LOGO_CACHE: dict[int, str] = {}


def _load_logo_base64(width: int) -> str | None:
    logo_path = Path("shared/autosniper_logo.png")
    if not logo_path.exists():
        return None
    cache_key = width
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key]
    encoded = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
    _LOGO_CACHE[cache_key] = encoded
    return encoded


def display_logo(width: int = 180) -> None:
    """Show the AutoSniper logo centered on the page if available."""
    encoded = _load_logo_base64(width)
    if not encoded:
        return
    inject_global_styles()
    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;margin-bottom:1.5rem;">
            <img src="data:image/png;base64,{encoded}" alt="AutoSniper Logo"
                 style="width:{width}px;max-width:100%;" />
        </div>
        """,
        unsafe_allow_html=True,
    )


_BANNER_CACHE: dict[tuple[str, int], str] = {}


def _load_banner_base64(width: int, image_path: Path) -> str | None:
    if not image_path.exists():
        return None
    cache_key = (str(image_path), width)
    if cache_key in _BANNER_CACHE:
        return _BANNER_CACHE[cache_key]
    encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    _BANNER_CACHE[cache_key] = encoded
    return encoded


def display_banner(width: int = 1600, image_path: Optional[str | Path] = None) -> None:
    """Render the wide banner if available."""
    banner_path = Path(image_path) if image_path is not None else Path("shared/banner.png")
    encoded = _load_banner_base64(width, banner_path)
    if not encoded:
        return
    inject_global_styles()
    st.markdown(
        f"""
        <div class="autosniper-banner" style="margin-top:2.5rem;margin-bottom:2rem;">
            <img src="data:image/png;base64,{encoded}" alt="AutoSniper Banner"
                 style="width:min(100%, {width}px); height:auto;" />
        </div>
        """,
        unsafe_allow_html=True,
    )
