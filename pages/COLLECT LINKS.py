import streamlit as st
import pandas as pd
from extract_links import extract_all_vehicle_links

st.set_page_config(page_title="Extract All Vehicle Links", layout="wide")
st.title("🔗 Extract All Vehicle Links")

CSV_PATH = "CSV_data/all_vehicle_links.csv"

if st.button("🚀 Run Link Scraper"):
    with st.spinner("Scraping vehicle links from Grays..."):
        progress_data = extract_all_vehicle_links(return_progress=True)
        pages_processed = progress_data["pages_processed"]
        total_links = progress_data["total_links"]
        unique_links = progress_data["unique_links"]
        links_saved = progress_data["links_saved"]
        status = progress_data["status"]

        # Progress bar (based on pages processed, assuming max pages estimated)
        st.progress(min(pages_processed / max(pages_processed, 1), 1.0))
        st.write(f"Processed {pages_processed} page(s)")
        st.write(f"Total links found: {total_links}")
        st.write(f"Unique links: {unique_links}")
        st.write(f"Saved {links_saved} links to {CSV_PATH}")
        st.write(f"Status: {status}")

if os.path.exists(CSV_PATH):
    st.markdown("### 📄 Latest Extracted Links")
    df = pd.read_csv(CSV_PATH)
    st.write(f"Total links: {len(df)}")
    st.dataframe(df.head(20))
else:
    st.info("Click the button above to extract all vehicle links.")