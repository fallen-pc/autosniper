import streamlit as st
import pandas as pd

from shared.styling import clean_html, display_banner, inject_global_styles, section_heading


st.set_page_config(page_title="STYLE GUIDE & TEMPLATE", layout="wide")
inject_global_styles()

display_banner()

st.markdown(
    clean_html(
        """
        <h1 style="text-align:center;">AUTOSNIPER UI TEMPLATE</h1>
        """
    ),
    unsafe_allow_html=True,
)
st.markdown(
    clean_html(
        """
        <p class="autosniper-tagline">
            Copy and paste these patterns when building new Streamlit pages so everything stays on-brand.
        </p>
        """
    ),
    unsafe_allow_html=True,
)

st.markdown(
    clean_html(
        """
        <style>
        .palette-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 0.9rem;
        }
        .palette-tile {
            border-radius: 16px;
            padding: 1.1rem;
            box-shadow: 0 18px 38px rgba(0, 0, 0, 0.28);
            border: 1px solid var(--autosniper-border);
            background: linear-gradient(135deg, rgba(26, 33, 48, 0.95) 0%, rgba(18, 23, 36, 0.92) 100%);
        }
        .palette-swatch {
            height: 52px;
            border-radius: 12px;
            margin-bottom: 0.7rem;
            border: 1px solid rgba(38, 50, 67, 0.7);
        }
        .palette-label {
            font-weight: 700;
            font-size: 0.95rem;
            color: var(--autosniper-text);
            margin-bottom: 0.15rem;
        }
        .palette-token {
            font-size: 0.8rem;
            color: var(--autosniper-muted);
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

section_heading(
    "Brand Palette",
    "Dark navy base with electric blue accents; reuse these tokens for any custom HTML blocks.",
)

palette = [
    ("Background", "var(--autosniper-bg)", "#0f1724"),
    ("Surface", "var(--autosniper-surface)", "#121724"),
    ("Panel", "var(--autosniper-panel)", "#1a2130"),
    ("Highlight", "var(--autosniper-highlight)", "#1a2130"),
    ("Primary", "var(--autosniper-primary)", "#e6edf6"),
    ("Primary Dark", "var(--autosniper-primary-dark)", "#b9c8dc"),
    ("Accent", "var(--autosniper-accent)", "#1fa6ff"),
    ("Accent Strong", "var(--autosniper-accent-strong)", "#0c8beb"),
    ("Muted", "var(--autosniper-muted)", "#9aa7b8"),
    ("Success", "var(--autosniper-success)", "#5ee6a7"),
    ("Warning", "var(--autosniper-warning)", "#ffa726"),
    ("Danger", "var(--autosniper-danger)", "#ff5a5f"),
]

palette_tiles = "".join(
    f"""
    <div class="palette-tile">
        <div class="palette-swatch" style="background:{hex_code};"></div>
        <div class="palette-label">{label}</div>
        <div class="palette-token">{token}</div>
        <div class="palette-token">{hex_code}</div>
    </div>
    """
    for label, token, hex_code in palette
)

st.markdown(
    clean_html(
        f"""
        <div class="autosniper-section">
            <div class="palette-grid">{palette_tiles}</div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

section_heading("Component Cheatsheet", "Copy these references to keep buttons, tables, and headings consistent.")

st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Buttons</div>
            <p class="autosniper-body">
                Primary: gradient blue, 12px radius, bold white text. Disabled: muted blue gradient, still readable.
            </p>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

col1, col2 = st.columns(2)
with col1:
    st.button("Primary Action")
with col2:
    st.button("Disabled State", disabled=True)
st.code(
    """# Primary button
if st.button("Save"):
    ...
# Disabled example
st.button("Save", disabled=True)""",
    language="python",
)

section_heading("Tables", "Use st.dataframe with the shared theme; keep columns tight and sortable.")

sample_df = pd.DataFrame(
    [
        {"Year": 2021, "Make": "Toyota", "Model": "Hilux", "Price": "$42,000"},
        {"Year": 2018, "Make": "Hyundai", "Model": "i30", "Price": "$14,500"},
    ]
)
st.dataframe(sample_df, use_container_width=True)
st.code(
    """st.dataframe(df, use_container_width=True)""",
    language="python",
)

section_heading("Listing Heading", "Large, bold title with a subdued subline; use .ai-card-title and .ai-card-subtitle styles.")

st.markdown(
    clean_html(
        """
        <div class="ai-card" style="padding:1.4rem 1.6rem;">
            <div class="ai-card-title">2024 Ford Everest Platinum</div>
            <div class="ai-card-subtitle" style="margin-top:0.35rem;">
                <span>10 auto</span>
                <span>Diesel</span>
                <span>VIC</span>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

section_heading("Info Banner", "Use a single banner style for page intros and notices.")

st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Manual Carsales</div>
            <div class="section-subtitle">Enter resale and instant-buy ranges, then save each row.</div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)
st.code(
    """section_heading("Manual Carsales", "Enter resale and instant-buy ranges, then save each row.")""",
    language="python",
)
