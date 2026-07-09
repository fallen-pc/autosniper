"""Shared styling utilities for the AutoSniper Streamlit apps."""

from __future__ import annotations

import base64
import html as _html_module
from pathlib import Path
import textwrap
from typing import Optional

import streamlit as st

from shared.logging_utils import suppress_tornado_websocket_errors

suppress_tornado_websocket_errors()


_BASE_STYLES = textwrap.dedent(
    """
    <style>
    :root {
        --autosniper-bg: #10141c;
        --autosniper-surface: #151a23;
        --autosniper-panel: #1b2230;
        --autosniper-highlight: #202938;
        --autosniper-primary: #e6edf6;
        --autosniper-primary-dark: #b9c8dc;
        --autosniper-accent: #1fa6ff;
        --autosniper-accent-strong: #0c8beb;
        --autosniper-text: #e6edf6;
        --autosniper-muted: #9aa7b8;
        --autosniper-success: #5ee6a7;
        --autosniper-warning: #ffa726;
        --autosniper-danger: #ff5a5f;
        --autosniper-border: #2d3748;
        --autosniper-shadow: rgba(0, 0, 0, 0.22);
        --autosniper-banner-navy: #0f1724;
        --autosniper-signal-cyan: #27b6ff;
        --autosniper-radius-sm: 6px;
        --autosniper-radius-md: 8px;
        --autosniper-radius-lg: 8px;
        --autosniper-radius-xl: 10px;
        --autosniper-space-1: 0.35rem;
        --autosniper-space-2: 0.6rem;
        --autosniper-space-3: 0.9rem;
        --autosniper-space-4: 1rem;
        --autosniper-space-5: 1.25rem;
        --autosniper-space-6: 1.5rem;
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
        background: #111722;
        color: #f5f7fb;
        border-right: 1px solid rgba(31, 166, 255, 0.35);
        box-shadow: 8px 0 18px rgba(0, 0, 0, 0.18);
    }
    [data-testid="stSidebar"] * {
        color: inherit;
    }
    .block-container {
        padding-top: 0.75rem;
        padding-bottom: 2rem;
    }
    h1, h2, h3 {
        color: var(--autosniper-primary);
        margin-bottom: 0.6rem;
        letter-spacing: 0;
    }
    h1 {
        font-size: 1.75rem;
        font-weight: 800;
    }
    h2 {
        font-size: 1.35rem;
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
        background: rgba(22, 28, 38, 0.96);
        border-radius: var(--autosniper-radius-lg);
        border: 1px solid var(--autosniper-border);
        box-shadow: 0 8px 18px rgba(0, 0, 0, 0.16);
        padding: var(--autosniper-space-4);
        margin-bottom: var(--autosniper-space-4);
    }
    .autosniper-section .section-title {
        font-size: 1.2rem;
        font-weight: 700;
    }
    .autosniper-section .section-subtitle {
        color: var(--autosniper-muted);
        margin-top: 0.35rem;
    }
    .autosniper-body {
        color: var(--autosniper-text);
        line-height: 1.55;
        margin: 0.2rem 0;
    }
    .autosniper-table {
        overflow-x: auto;
        border-radius: var(--autosniper-radius-lg);
        border: 1px solid var(--autosniper-border);
        background: rgba(18, 23, 36, 0.9);
    }
    .autosniper-table table {
        width: 100%;
        border-collapse: collapse;
        color: var(--autosniper-text);
    }
    .autosniper-table th,
    .autosniper-table td {
        padding: 0.55rem 0.75rem;
        border-bottom: 1px solid var(--autosniper-border);
        text-align: left;
    }
    .autosniper-table th {
        background: rgba(31, 166, 255, 0.08);
        color: var(--autosniper-muted);
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.08em;
    }
    .autosniper-table tr:last-child td {
        border-bottom: none;
    }
    /* Shared "open listing" pill link, used by the AI Analysis and Missed
       Opportunities card components (previously two drifted local copies). */
    .card-actions a {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.2rem 0.55rem;
        border-radius: 999px;
        border: 1px solid rgba(39, 182, 255, 0.6);
        color: var(--autosniper-primary);
        text-decoration: none;
        font-size: 0.62rem;
        font-weight: 800;
        text-transform: uppercase;
        letter-spacing: 0.12em;
    }
    .card-actions a:hover {
        background: rgba(39, 182, 255, 0.12);
    }
    /* Shared 4-up stat grid used by the Repair Review and Repair Pricing
       pages (previously two identical local copies). */
    .autosniper-repair-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.65rem;
        margin: 0.75rem 0 1rem;
    }
    @media (max-width: 900px) {
        .autosniper-repair-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    .autosniper-chip {
        display: inline-flex;
        align-items: center;
        padding: 0.35rem 0.75rem;
        background: rgba(31, 166, 255, 0.12);
        border: 1px solid rgba(31, 166, 255, 0.35);
        border-radius: 999px;
        color: var(--autosniper-primary);
        font-weight: 600;
        margin-right: 0.35rem;
        margin-bottom: 0.35rem;
    }
    .stButton>button {
        background: linear-gradient(135deg, var(--autosniper-accent) 0%, var(--autosniper-accent-strong) 100%);
        color: #f6f9ff;
        border-radius: var(--autosniper-radius-md);
        border: none;
        padding: 0.7rem 1.35rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        box-shadow: none;
        transition: all 0.2s ease;
        opacity: 1 !important;
    }
    .stButton>button:hover {
        background: linear-gradient(135deg, var(--autosniper-accent-strong) 0%, var(--autosniper-accent) 100%);
        transform: translateY(-1px);
        box-shadow: 0 8px 18px rgba(12, 139, 235, 0.24);
        color: #f6f9ff;
    }
    .stButton>button:disabled {
        background: linear-gradient(135deg, rgba(31, 166, 255, 0.25) 0%, rgba(12, 139, 235, 0.25) 100%);
        color: rgba(230, 237, 246, 0.65);
        box-shadow: none;
    }
    /* Ensure sidebar buttons match primary styling */
    [data-testid="stSidebar"] .stButton>button {
        background: linear-gradient(135deg, var(--autosniper-accent) 0%, var(--autosniper-accent-strong) 100%);
        color: #f6f9ff;
        border-radius: var(--autosniper-radius-md);
        border: none;
        padding: 0.65rem 1.1rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        box-shadow: none;
        opacity: 1 !important;
    }
    [data-testid="stSidebar"] .stButton>button:hover {
        background: linear-gradient(135deg, var(--autosniper-accent-strong) 0%, var(--autosniper-accent) 100%);
        box-shadow: 0 8px 18px rgba(12, 139, 235, 0.22);
        color: #f6f9ff;
    }
    .autosniper-banner {
        display: flex;
        justify-content: flex-start;
        margin: 0 0 0.65rem;
    }
    .autosniper-banner img {
        width: min(100%, 220px);
        max-height: 96px;
        height: auto;
        object-fit: contain;
        object-position: left center;
        border-radius: var(--autosniper-radius-md);
        box-shadow: none;
        clip-path: none;
    }
    .rail-logo {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 56px;
        height: 56px;
        border-radius: 18px;
        background: transparent;
        border: none;
        box-shadow: none;
    }
    .crosshair {
        position: relative;
        width: 40px;
        height: 40px;
        border: 2px solid rgba(31, 166, 255, 0.8);
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }
    .crosshair::before,
    .crosshair::after {
        content: "";
        position: absolute;
        background: rgba(31, 166, 255, 0.7);
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
        background: rgba(12, 139, 235, 0.95);
        box-shadow: 0 0 12px rgba(0, 0, 0, 0.4);
    }
    .stDataFrame {
        border-radius: var(--autosniper-radius-lg);
        box-shadow: 0 22px 40px rgba(0, 0, 0, 0.32);
        border: 1px solid var(--autosniper-border);
        background: rgba(18, 23, 36, 0.9);
        overflow: hidden;
    }
    .stAlert {
        border-radius: var(--autosniper-radius-md);
        border: 1px solid var(--autosniper-border);
        box-shadow: none;
        background: rgba(31, 166, 255, 0.08);
        color: var(--autosniper-text);
    }
    [data-testid="stMetric"] {
        border-radius: var(--autosniper-radius-md);
        border: 1px solid var(--autosniper-border);
        background: rgba(26, 33, 48, 0.9);
        box-shadow: none;
        padding: 0.75rem;
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
        background: linear-gradient(135deg, rgba(26, 33, 48, 0.92), rgba(18, 23, 36, 0.94));
        border-radius: var(--autosniper-radius-lg);
        border: 1px solid var(--autosniper-border);
        box-shadow: 0 16px 32px rgba(0, 0, 0, 0.28);
        padding: var(--autosniper-space-5);
        margin-bottom: var(--autosniper-space-5);
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
        border-radius: var(--autosniper-radius-lg);
        border: 1px solid var(--autosniper-border);
        background: rgba(26, 33, 48, 0.92);
        box-shadow: 0 18px 32px rgba(0, 0, 0, 0.24);
    }
    hr {
        border: none;
        border-top: 1px solid var(--autosniper-border);
        margin: 1.8rem 0;
    }
    .ai-card {
        background: var(--autosniper-surface);
        border: 1px solid var(--autosniper-border);
        border-radius: 26px;
        box-shadow: none;
        padding: 1.9rem 2.2rem;
        margin-bottom: 1.7rem;
    }
    div[data-testid="stVerticalBlock"].ai-card-wrapper {
        background: var(--autosniper-surface);
        border: 1px solid var(--autosniper-border);
        border-radius: 26px;
        box-shadow: none;
        padding: 1.9rem 2.2rem;
        margin: 1.75rem 0 1.7rem;
    }
    .ai-card-header {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-start;
        justify-content: space-between;
        gap: 1.5rem;
        border-bottom: 1px solid var(--autosniper-border);
        padding-bottom: 1.2rem;
    }
    .ai-card-title-group {
        display: flex;
        flex-direction: column;
        gap: 0.45rem;
        min-width: 260px;
    }
    .ai-card-meta {
        font-size: 0.9rem;
        color: var(--autosniper-muted);
        letter-spacing: 0.05em;
        text-transform: uppercase;
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
        border-radius: 999px;
        padding: 0.35rem 0.8rem;
        font-size: 0.92rem;
        font-weight: 600;
        color: var(--autosniper-primary);
        letter-spacing: 0.02em;
    }
    .ai-card-actions {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 0.75rem;
        min-width: 180px;
    }
    .ai-card-odometer {
        text-align: right;
    }
    .ai-card-odometer-label {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--autosniper-muted);
    }
    .ai-card-odometer-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: var(--autosniper-primary);
    }
    .ai-card-link-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.35rem;
        padding: 0.45rem 1.1rem;
        border-radius: 999px;
        background: var(--autosniper-primary);
        color: #fff;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        font-size: 0.78rem;
        box-shadow: 0 14px 28px rgba(0, 0, 0, 0.25);
    }
    .ai-card-link-button:hover {
        background: var(--autosniper-primary-dark);
        color: #fff;
    }
    .ai-card-body {
        margin-top: 1.2rem;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    .ai-card-conditions {
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
    }
    .ai-card-condition-summary {
        font-size: 0.95rem;
        color: var(--autosniper-text);
        line-height: 1.35;
    }
    .ai-card-condition-badges {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem;
    }
    .ai-card-condition-badge {
        background: rgba(31, 166, 255, 0.08);
        border: 1px solid rgba(38, 50, 67, 0.8);
        border-radius: 999px;
        padding: 0.15rem 0.7rem;
        font-size: 0.8rem;
        color: var(--autosniper-muted);
        font-weight: 500;
    }
    .ai-edge-warning {
        margin-top: 0.6rem;
        padding: 0.55rem 0.85rem;
        border-radius: 14px;
        border: 1px solid rgba(255, 167, 38, 0.35);
        background: rgba(255, 167, 38, 0.12);
        color: rgba(255, 220, 170, 0.95);
        font-weight: 600;
        letter-spacing: 0.01em;
    }
    .ai-card-stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 0.85rem;
    }
    .ai-spec-list {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 0.75rem;
        margin-bottom: 1rem;
    }
    .ai-spec-item {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }
    .ai-spec-wrapper {
        position: relative;
    }
    .ai-spec-actions {
        display: flex;
        justify-content: flex-end;
        margin-bottom: 0.35rem;
    }
    .ai-spec-label,
    .ai-spec-value {
        color: inherit;
    }
    .ai-condition-column {
        background: rgba(26, 33, 48, 0.92);
        border: 1px solid var(--autosniper-border);
        border-radius: 16px;
        padding: 0.9rem 1rem;
        min-height: 100%;
    }
    .ai-condition-summary {
        margin-bottom: 0.6rem;
    }
    .ai-card-stat {
        background: rgba(26, 33, 48, 0.85);
        border: 1px solid var(--autosniper-border);
        border-radius: 18px;
        padding: 0.85rem 1rem;
        box-shadow: 0 18px 32px rgba(0, 0, 0, 0.16);
    }
    .ai-comparison-card {
        border: 1px solid var(--autosniper-border);
        border-radius: 20px;
        padding: 1.1rem 1.2rem;
        background: rgba(15, 23, 36, 0.95);
        min-height: 100%;
    }
    .ai-comparison-table {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        margin-bottom: 1.2rem;
    }
    .ai-comparison-table-row {
        display: grid;
        grid-template-columns: 0.8fr 1fr 1fr;
        gap: 0.9rem;
        background: rgba(13, 19, 31, 0.9);
        border: 1px solid var(--autosniper-border);
        border-radius: 18px;
        padding: 0.85rem 1rem;
    }
    .ai-comparison-table-header {
        display: grid;
        grid-template-columns: 0.8fr 1fr 1fr;
        gap: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 0.78rem;
        color: var(--autosniper-muted);
        background: transparent;
        border: none;
        padding: 0;
    }
    .ai-comparison-label {
        font-weight: 600;
        color: var(--autosniper-muted);
    }
    .ai-comparison-title {
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: var(--autosniper-muted);
        margin-bottom: 0.75rem;
    }
    .ai-comparison-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.6rem;
        font-size: 0.95rem;
        padding: 0.25rem 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
    }
    .ai-comparison-row:last-child {
        border-bottom: none;
    }
    .ai-comparison-row span {
        color: var(--autosniper-muted);
        font-size: 0.85rem;
    }
    .ai-comparison-row strong {
        color: var(--autosniper-primary);
        font-weight: 600;
    }
    .ai-card-stat-label {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: var(--autosniper-muted);
        margin-bottom: 0.15rem;
    }
    .ai-card-stat-value {
        font-size: 1.15rem;
        font-weight: 600;
        color: var(--autosniper-primary);
    }
    input[type="text"],
    input[type="number"],
    textarea,
    select,
    .stTextInput input,
    .stNumberInput input,
    .stSelectbox select,
    .stSelectbox > div > div,
    .stMultiSelect > div > div,
    .stSelectbox [data-baseweb="select"],
    .stMultiSelect [data-baseweb="select"],
    [data-baseweb="select"] [aria-label="Select"] {
        background: var(--autosniper-surface);
        color: var(--autosniper-text);
        border: 1px solid var(--autosniper-border);
        border-radius: 10px;
        padding: 0.55rem 0.7rem;
        box-shadow: inset 0 0 0 1px rgba(31, 166, 255, 0.1);
    }
    [data-baseweb="select"] * {
        color: var(--autosniper-text);
    }
    [data-baseweb="popover"] {
        background: var(--autosniper-panel);
        color: var(--autosniper-text);
        border: 1px solid var(--autosniper-border);
        box-shadow: 0 18px 32px rgba(0, 0, 0, 0.35);
    }
    input[type="text"]::placeholder,
    input[type="number"]::placeholder,
    textarea::placeholder,
    .stSelectbox [data-baseweb="select"] input::placeholder,
    .stMultiSelect [data-baseweb="select"] input::placeholder {
        color: var(--autosniper-muted);
    }
    input[type="text"]:focus,
    input[type="number"]:focus,
    textarea:focus,
    select:focus,
    .stTextInput input:focus,
    .stNumberInput input:focus,
    .stSelectbox select:focus,
    .stSelectbox [data-baseweb="select"]:focus-within,
    .stMultiSelect [data-baseweb="select"]:focus-within {
        border-color: var(--autosniper-accent);
        outline: none;
        box-shadow: 0 0 0 3px rgba(31, 166, 255, 0.25);
    }
    .stNumberInput button {
        color: var(--autosniper-text);
        background: var(--autosniper-panel);
        border: 1px solid var(--autosniper-border);
    }
    .page-intro {
        background: rgba(18, 23, 32, 0.94);
        border: 1px solid var(--autosniper-border);
        border-radius: var(--autosniper-radius-lg);
        padding: 0.85rem 1rem;
        box-shadow: none;
        margin: 0 0 0.85rem;
        text-align: left;
        max-width: none;
    }
    .page-intro h1 {
        margin: 0 0 0.25rem 0;
        font-size: 1.55rem;
        text-align: left;
        letter-spacing: 0;
        text-transform: none;
    }
    .page-intro p {
        margin: 0;
        color: var(--autosniper-muted);
        font-size: 0.95rem;
        line-height: 1.4;
    }
    .hero-card {
        background: rgba(22, 28, 38, 0.96);
        border: 1px solid rgba(44, 58, 79, 0.9);
        border-radius: var(--autosniper-radius-lg);
        box-shadow: none;
        padding: 1rem;
        text-align: left;
        margin: 0 0 1rem;
        max-width: none;
        position: relative;
        overflow: hidden;
    }
    .hero-card::after {
        content: none;
    }
    .hero-card > * {
        position: relative;
        z-index: 1;
    }
    .hero-card h1 {
        margin-bottom: 0.45rem;
        text-transform: none;
        font-weight: 800;
        letter-spacing: 0;
    }
    .hero-card .hero-card-description {
        color: var(--autosniper-muted);
        margin: 0;
        font-size: 0.95rem;
        line-height: 1.45;
    }
    .hero-card .hero-card-actions {
        display: flex;
        justify-content: flex-start;
        margin-bottom: 0.75rem;
    }
    .hero-card .hero-card-actions .stButton>button {
        min-width: 180px;
        border-radius: var(--autosniper-radius-md);
        border: 1px solid rgba(255, 255, 255, 0.35);
        background: linear-gradient(135deg, #00aaff 0%, #0066cc 100%);
        box-shadow: none;
    }
    /* New dark/blue theme overrides.
       NOTE: this block intentionally repeats several selectors already
       defined above (h1/h2/h3, .stButton>button, stMetric*, stSidebar text,
       .page-intro, .autosniper-banner, div[data-testid="stVerticalBlock"].ai-card-wrapper).
       Because it appears later in this stylesheet, it wins the cascade for
       any property it sets, so THIS block is the one that actually renders
       app-wide (its hex values, e.g. #00AFFF/#E5E5E5, match .streamlit/config.toml's
       [theme] section). The earlier declarations for those same selectors are
       mostly dead weight, kept only because a couple of properties they set
       (e.g. margin-bottom, letter-spacing, opacity) aren't touched here and
       still apply. Treat this block, not the original token block above, as
       the source of truth when styling new pages -- 99_STYLE_GUIDE.py still
       shows the older palette and should be refreshed to match this one. */
    .stApp {
        background-color: var(--autosniper-bg) !important;
    }
    .main .block-container {
        padding-top: 1rem;
        padding-bottom: 1.5rem;
        max-width: 1280px;
    }
    section[data-testid="stSidebar"] {
        background: #111722;
        border-right: 1px solid rgba(70, 95, 130, 0.35);
    }
    section[data-testid="stSidebar"] * {
        color: #E5E5E5 !important;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        font-weight: 700;
        color: #E5E5E5 !important;
    }
    section[data-testid="stSidebar"] .stSelectbox,
    section[data-testid="stSidebar"] .stCheckbox,
    section[data-testid="stSidebar"] .stSlider,
    section[data-testid="stSidebar"] .stMultiSelect {
        background-color: rgba(22, 28, 38, 0.72) !important;
        border-radius: var(--autosniper-radius-sm);
        padding: 6px 8px;
    }
    .stSelectbox [data-baseweb="select"],
    .stMultiSelect [data-baseweb="select"],
    .stTextInput input,
    .stNumberInput input,
    .stTextArea textarea,
    .stDateInput input,
    .stTimeInput input {
        min-height: 42px;
        border-radius: var(--autosniper-radius-sm) !important;
        border: 1px solid rgba(80, 120, 170, 0.24) !important;
        background: rgba(17, 22, 31, 0.92) !important;
        color: #E5E5E5 !important;
        box-shadow: none !important;
    }
    @media (max-width: 640px) {
        .autosniper-banner {
            display: none;
        }
        .page-intro {
            margin-top: 0.25rem;
        }
    }
    .stTextArea textarea {
        min-height: 120px;
    }
    .stSelectbox [data-baseweb="select"]:focus-within,
    .stMultiSelect [data-baseweb="select"]:focus-within,
    .stTextInput input:focus,
    .stNumberInput input:focus,
    .stTextArea textarea:focus,
    .stDateInput input:focus,
    .stTimeInput input:focus {
        border-color: rgba(0, 175, 255, 0.65) !important;
        box-shadow: 0 0 0 1px rgba(0, 175, 255, 0.18), 0 0 12px rgba(0, 175, 255, 0.18) !important;
    }
    div[data-testid="stDataFrame"] {
        background: linear-gradient(145deg, rgba(26, 33, 48, 0.96), rgba(10, 16, 28, 0.96));
        border-radius: var(--autosniper-radius-lg);
        padding: 0;
        border: 1px solid rgba(31, 166, 255, 0.18);
        box-shadow: 0 16px 30px rgba(4, 9, 17, 0.3);
        overflow: hidden;
    }
    div[data-testid="stDataFrame"] table {
        color: #E5E5E5;
        border-collapse: separate;
        border-spacing: 0;
    }
    div[data-testid="stDataFrame"] thead tr {
        background-color: #111319 !important;
    }
    div[data-testid="stDataFrame"] thead tr th,
    div[data-testid="stDataFrame"] [role="columnheader"] {
        position: sticky !important;
        top: 0;
        z-index: 3;
        background: #111319 !important;
        backdrop-filter: blur(6px);
    }
    div[data-testid="stDataFrame"] tbody tr:nth-child(even) {
        background-color: #15171C !important;
    }
    div[data-testid="stDataFrame"] tbody tr:nth-child(odd) {
        background-color: #101218 !important;
    }
    div[data-testid="stDataFrame"] tbody tr:hover td,
    div[data-testid="stDataFrame"] [role="row"]:hover > div {
        background-color: rgba(31, 166, 255, 0.09) !important;
    }
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, rgba(26, 33, 48, 0.98), rgba(10, 16, 28, 0.98));
        border-radius: var(--autosniper-radius-md);
        padding: 16px;
        border: 1px solid rgba(31, 166, 255, 0.18);
        box-shadow: 0 16px 30px rgba(4, 9, 17, 0.28);
    }
    [data-testid="stMetricLabel"] {
        color: #B6B6B6 !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 11px;
    }
    [data-testid="stMetricValue"] {
        font-size: 26px;
        font-weight: 800;
        background: linear-gradient(180deg, #E5E5E5, #7A7A7A);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    h1, h2, h3 {
        color: #E5E5E5 !important;
    }
    h1 {
        font-size: 32px !important;
        font-weight: 900 !important;
    }
    .stButton > button {
        border-radius: 999px;
        border: 1px solid #00AFFF;
        background: radial-gradient(circle at top, #00AFFF 0%, #0066CC 70%);
        color: #E5E5E5 !important;
        font-weight: 600;
        font-size: 14px;
        padding: 8px 26px;
        box-shadow: 0 0 12px rgba(0, 175, 255, 0.35);
        transition: all 0.15s ease-out;
    }
    .stButton > button:hover {
        border-color: #00F6FF;
        box-shadow: 0 0 20px rgba(0, 246, 255, 0.55);
        transform: translateY(-1px);
    }
    [data-testid="stTextInput"] input {
        background-color: #1A1A1C !important;
        color: #E5E5E5 !important;
        border-radius: 10px !important;
        border: 1px solid #2A2D30 !important;
    }
    [data-testid="stTextInput"] input:focus {
        border-color: #00AFFF !important;
        box-shadow: 0 0 12px rgba(0, 175, 255, 0.5);
    }
    button[aria-expanded="true"],
    button[aria-expanded="false"] {
        background-color: #14161C !important;
        color: #E5E5E5 !important;
        border-radius: var(--autosniper-radius-md) !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.45rem;
        padding-bottom: 0.3rem;
        border-bottom: 1px solid rgba(31, 166, 255, 0.14);
    }
    [data-testid="stTabs"] [data-baseweb="tab"] {
        height: auto !important;
        padding: 0.65rem 0.95rem !important;
        border-radius: var(--autosniper-radius-md) var(--autosniper-radius-md) 0 0;
        background: rgba(16, 22, 31, 0.82);
        border: 1px solid transparent;
        color: rgba(230, 237, 246, 0.72) !important;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background: linear-gradient(180deg, rgba(31, 166, 255, 0.18), rgba(17, 22, 31, 0.96)) !important;
        border-color: rgba(31, 166, 255, 0.24) !important;
        color: #E5E5E5 !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-highlight"] {
        background: rgba(0, 175, 255, 0.85) !important;
        height: 2px !important;
    }
    [data-testid="stTabs"] [data-baseweb="tab-panel"] {
        padding-top: 1rem;
    }
    .streamlit-expanderHeader {
        padding: 0.9rem 1rem !important;
        font-weight: 700;
    }
    .streamlit-expanderContent {
        padding: 0 1rem 1rem !important;
    }
    /* Chrome gradient title */
    .autosniper-title {
        font-size: 48px;
        font-weight: 900;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        text-align: center;
        margin-top: 10px;
        margin-bottom: 30px;
        background: linear-gradient(180deg, #E5E5E5 0%, #B6B6B6 40%, #7A7A7A 80%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 0 0 12px rgba(0,175,255,0.35);
    }
    /* Highlight active sidebar item */
    section[data-testid="stSidebar"] a[aria-current="page"] {
        background: radial-gradient(circle at left, rgba(0,175,255,0.35) 0%, rgba(0,175,255,0.05) 65%);
        border-radius: 8px;
        font-weight: 700 !important;
        color: #00F6FF !important;
    }
    /* Listing container separation + verdict styling */
    div[data-testid="stVerticalBlock"].ai-card-wrapper {
        margin: 24px 0 18px;
        padding: 22px 22px 12px 22px;
        border: 1px solid rgba(140, 180, 255, 0.2);
        border-radius: 24px;
        background: rgba(10, 16, 26, 0.42);
        box-shadow: 0 14px 32px rgba(0, 0, 0, 0.38);
    }
    .verdict-row {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 0.75rem;
        padding: 0.7rem 0.85rem;
        border-radius: 16px;
        border: 1px solid rgba(38, 50, 67, 0.8);
        background: rgba(26, 33, 48, 0.55);
        margin-top: 0.75rem;
    }
    .verdict-pill {
        font-size: 0.95rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: var(--autosniper-primary);
    }
    .verdict-meta {
        font-size: 0.85rem;
        color: rgba(154, 167, 184, 0.9);
    }
    .verdict-strong {
        border-color: rgba(94, 230, 167, 0.55);
        background: rgba(94, 230, 167, 0.08);
    }
    .verdict-conditional {
        border-color: rgba(31, 166, 255, 0.55);
        background: rgba(31, 166, 255, 0.08);
    }
    .verdict-trap {
        border-color: rgba(255, 167, 38, 0.55);
        background: rgba(255, 167, 38, 0.08);
    }
    .verdict-avoid {
        border-color: rgba(255, 90, 95, 0.60);
        background: rgba(255, 90, 95, 0.08);
    }
    .risk-chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.6rem;
        margin-bottom: 0.25rem;
    }
    .risk-chip {
        display: inline-flex;
        align-items: center;
        padding: 0.18rem 0.65rem;
        border-radius: 999px;
        font-size: 0.78rem;
        border: 1px solid rgba(38, 50, 67, 0.8);
        background: rgba(31, 166, 255, 0.08);
        color: rgba(230, 237, 246, 0.78);
    }
    .risk-chip.more-chip {
        background: transparent;
        border-style: dashed;
        color: rgba(230, 237, 246, 0.6);
    }
    .ai-action-links {
        margin-top: 0.35rem;
        font-size: 0.85rem;
    }
    .ai-action-links a {
        color: var(--autosniper-accent);
        opacity: 0.8;
        text-decoration: none;
    }
    .ai-action-links a:hover {
        opacity: 1;
        text-decoration: underline;
    }
    @media (max-width: 768px) {
        .page-intro {
            padding: 0.9rem 1rem;
            margin-bottom: 0.8rem;
        }
        .page-intro h1 {
            font-size: clamp(1.8rem, 5vw, 2.2rem);
        }
    }
    </style>
    """
)


def clean_html(html: str) -> str:
    """Dedent HTML snippets so Streamlit renders them as markup."""
    return textwrap.dedent(html).strip()


def escape_html(value: object) -> str:
    """HTML-escape a value for safe interpolation into markup.

    Converts the value to a string then escapes ``&``, ``<``, ``>``, ``"``
    and ``'`` so it cannot break out of an HTML attribute or text node.
    """
    return _html_module.escape(str(value) if value is not None else "", quote=True)


def safe_url(value: object) -> str:
    """Return a URL safe for use in an ``href`` attribute.

    Applies HTML-escaping and rejects ``javascript:`` scheme URIs, returning
    an empty string in their place so no script can execute on click.
    """
    url = str(value).strip() if value is not None else ""
    if url.lower().lstrip().startswith("javascript:"):
        return ""
    return _html_module.escape(url, quote=True)


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


def render_logo_centered(width: int = 340) -> None:
    """Render the autosniper logo centered if available."""
    encoded = _load_logo_base64(width)
    if not encoded:
        return
    inject_global_styles()
    st.markdown(
        f"""
        <div style='text-align:center; margin-top:10px; margin-bottom:20px;'>
            <img src="data:image/png;base64,{encoded}" style='width:{width}px; max-width:85%;' />
        </div>
        """,
        unsafe_allow_html=True,
    )


_TITLE_ACRONYMS = {
    "AI",
    "CSV",
    "URL",
    "VIN",
    "QA",
    "V2",
}


def _display_title(title: str) -> str:
    words = str(title).strip().split()
    if not words:
        return ""
    if not all(word.upper() == word for word in words):
        return title
    formatted = []
    for word in words:
        cleaned = word.strip()
        if cleaned in _TITLE_ACRONYMS:
            formatted.append(cleaned)
        elif "-" in cleaned:
            formatted.append("-".join(part.capitalize() if part not in _TITLE_ACRONYMS else part for part in cleaned.split("-")))
        else:
            formatted.append(cleaned.capitalize())
    return " ".join(formatted)


def page_intro(title: str, subtitle: str | None = None, *, show_logo: bool = False) -> None:
    """Render a standard page intro panel."""
    inject_global_styles()
    if show_logo:
        render_logo_centered()
    display_title = _display_title(title)
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        clean_html(
            f"""
            <div class="page-intro">
                <h1>{display_title}</h1>
                {subtitle_html}
            </div>
            """
        ),
        unsafe_allow_html=True,
    )


def chrome_title(text: str = "AUTOSNIPER") -> None:
    """Render the chrome gradient Autosniper title."""
    inject_global_styles()
    st.markdown(f"<div class='autosniper-title'>{text}</div>", unsafe_allow_html=True)


def hero_action_card(title: str, subtitle: str, button_label: str, *, button_key: str) -> bool:
    """Render a hero card with heading, CTA button, and subtitle. Returns button click state."""
    inject_global_styles()
    container = st.container()
    with container:
        st.markdown("<div class='hero-card'>", unsafe_allow_html=True)
        st.markdown(f"<h1>{title}</h1>", unsafe_allow_html=True)
        st.markdown("<div class='hero-card-actions'>", unsafe_allow_html=True)
        clicked = st.button(button_label, key=button_key)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='hero-card-description'>{subtitle}</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    return clicked


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


def display_logo(width: int = 150) -> None:
    """Show the AutoSniper logo centered on the page if available, with a trimmed height."""
    encoded = _load_logo_base64(width)
    if not encoded:
        return
    inject_global_styles()
    st.markdown(
        f"""
        <div style="display:flex;justify-content:center;margin:0.1rem 0 0.35rem;">
            <img src="data:image/png;base64,{encoded}" alt="AutoSniper Logo"
                 style="max-height:110px;width:{width}px;max-width:100%;height:auto;margin:0;" />
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


def display_banner(width: int = 220, image_path: Optional[str | Path] = None) -> None:
    """Render a compact brand mark if available."""
    banner_path = Path(image_path) if image_path is not None else Path("shared/banner.png")
    encoded = _load_banner_base64(width, banner_path)
    if not encoded:
        return
    inject_global_styles()
    st.markdown(
        f"""
        <div class="autosniper-banner">
            <img src="data:image/png;base64,{encoded}" alt="AutoSniper Banner"
                 style="width:min(100%, {width}px); height:auto;" />
        </div>
        """,
        unsafe_allow_html=True,
    )
