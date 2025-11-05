import streamlit as st

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
        .template-grid {
            display: grid;
            gap: 1.2rem;
        }
        @media (min-width: 992px) {
            .template-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }
        .palette-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 0.9rem;
        }
        .palette-tile {
            border-radius: 16px;
            padding: 1.1rem;
            box-shadow: 0 12px 24px rgba(13, 2, 45, 0.18);
            border: 1px solid rgba(40, 71, 53, 0.24);
            background: rgba(242, 236, 219, 0.96);
        }
        .palette-swatch {
            height: 52px;
            border-radius: 12px;
            margin-bottom: 0.7rem;
            border: 1px solid rgba(40, 71, 53, 0.28);
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
        .template-card {
            background: var(--autosniper-panel);
            border-radius: 18px;
            padding: 1.5rem;
            border: 1px solid var(--autosniper-border);
            box-shadow: 0 18px 38px rgba(13, 2, 45, 0.18);
        }
        .template-card h3 {
            margin: 0;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-size: 0.88rem;
            color: var(--autosniper-muted);
        }
        .template-card .content {
            margin-top: 0.9rem;
        }
        .example-button-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
        }
        .ghost-button {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.55rem 1.1rem;
            border-radius: 10px;
            color: var(--autosniper-text);
            border: 1.5px solid rgba(40, 71, 53, 0.4);
            background: rgba(182, 167, 124, 0.24);
            font-weight: 600;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .ghost-button:hover {
            text-decoration: none;
            transform: translateY(-1px);
            box-shadow: 0 10px 22px rgba(13, 2, 45, 0.18);
        }
        .template-layout {
            display: grid;
            gap: 1rem;
        }
        @media (min-width: 992px) {
            .template-layout {
                grid-template-columns: 2fr 1fr;
            }
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)

section_heading(
    "Brand Palette",
    "Banner navy and earthy camo tones ready for reuse anywhere custom HTML needs colour tokens.",
)

palette = [
    ("Background", "var(--autosniper-bg)", "#FFFFFF"),
    ("Surface", "var(--autosniper-surface)", "#FFFFFF"),
    ("Panel", "var(--autosniper-panel)", "#F2ECDB"),
    ("Highlight", "var(--autosniper-highlight)", "#D8CAA3"),
    ("Primary", "var(--autosniper-primary)", "#0D022D"),
    ("Primary Dark", "var(--autosniper-primary-dark)", "#07031A"),
    ("Accent", "var(--autosniper-accent)", "#284735"),
    ("Muted", "var(--autosniper-muted)", "#403030"),
    ("Success", "var(--autosniper-success)", "#284735"),
    ("Warning", "var(--autosniper-warning)", "#B6A77C"),
    ("Danger", "var(--autosniper-danger)", "#3C352F"),
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

section_heading("Layout Starter", "Drop your content into this split grid for balanced pages.")

st.markdown(
    clean_html(
        """
        <div class="template-layout autosniper-section">
            <div>
                <h2>Main Column</h2>
                <p class="autosniper-body">
                    Use this space for rich markdown, tables, or custom HTML blocks. Wrap complex sections inside
                    <code>st.container()</code> or the <code>autosniper-section</code> class to reuse the frosted card.
                </p>
            </div>
            <div>
                <h3>Sidebar Actions</h3>
                <p class="autosniper-body">
                    Quick stats, filters, or secondary actions live here. Keep calls-to-action stacked vertically.
                </p>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

section_heading("Reusable Blocks", "Copy these cards for consistent headings, metrics, and CTAs.")

st.markdown(
    clean_html(
        """
        <div class="template-grid">
            <div class="template-card">
                <h3>Section Headings</h3>
                <div class="content">
                    <p class="autosniper-body">
                        Use <code>section_heading("Title", "Optional subtitle")</code> at the top of each logical block.
                        Pair with <code>info_chip()</code> when you need inline status tags.
                    </p>
                </div>
            </div>
            <div class="template-card">
                <h3>Buttons</h3>
                <div class="content">
                    <p class="autosniper-body">
                        Default Streamlit buttons pick up our primary colour. For link-style CTAs, wrap an anchor with
                        the <code>ghost-button</code> class.
                    </p>
                    <div class="example-button-row">
                        <a class="ghost-button" href="#" onclick="return false;">Secondary Action</a>
                    </div>
                </div>
            </div>
            <div class="template-card">
                <h3>List Cards</h3>
                <div class="content">
                    <p class="autosniper-body">
                        Wrap vehicles or insights inside a <code>div.autosniper-listing-card</code>. The listing
                        dashboard demonstrates the full markup pattern.
                    </p>
                </div>
            </div>
            <div class="template-card">
                <h3>Data Tables</h3>
                <div class="content">
                    <p class="autosniper-body">
                        <code>st.dataframe(..., use_container_width=True)</code> automatically inherits rounded corners,
                        borders, and shadows from the shared CSS. Keep tables dense and filterable where possible.
                    </p>
                </div>
            </div>
        </div>
        """
    ),
    unsafe_allow_html=True,
)

section_heading("Copy Snippet", "Start new Streamlit pages with this boilerplate.")

st.code(
    clean_html(
        """
import streamlit as st
from shared.styling import display_banner, inject_global_styles, section_heading

st.set_page_config(page_title="New Page", layout="wide")
inject_global_styles()
display_banner()

st.title("Page Heading")
st.markdown("<p class='autosniper-tagline'>Short supporting statement.</p>", unsafe_allow_html=True)
section_heading("Section Title", "Optional subtitle for context.")

col1, col2 = st.columns((2, 1))
with col1:
    st.write("Primary content block goes here.")
with col2:
    if st.button("Primary Action"):
        st.success("Action complete.")
        """
    ),
    language="python",
)

st.markdown(
    clean_html(
        """
        <div class="autosniper-section">
            <div class="section-title">Need more patterns?</div>
            <p class="autosniper-body">
                The listing dashboards contain more advanced cards (metrics, AI verdicts, filters). Use this page as a
                quick reference while building new tools or onboarding collaborators.
            </p>
        </div>
        """
    ),
    unsafe_allow_html=True,
)
