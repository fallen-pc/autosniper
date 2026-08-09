import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from shared.navigation import render_sidebar_navigation

from shared.styling import (
    clean_html,
    display_banner,
    hero_action_card,
    inject_global_styles,
    section_heading,
)


DEFAULT_URL = "https://www.autotrader.com.au/for-sale/used/toyota/vic/melbourne"
DEFAULT_OUTPUT = "autotrader_isolated/output/first_page_results.csv"
DEFAULT_STORAGE_STATE = "autotrader_isolated/output/storage_state.json"
ROOT_DIR = Path(__file__).resolve().parent.parent


st.set_page_config(page_title="AUTOTRADER SCRAPER", layout="wide")
render_sidebar_navigation()
inject_global_styles()
display_banner()

run_clicked = hero_action_card(
    "AUTOTRADER SCRAPER",
    "Capture used listings with pagination, priority ordering, and dedupe against existing runs.",
    "Run Autotrader scrape",
    button_key="autotrader_run_scrape",
)

section_heading("Scrape Configuration", "Tune pagination, priority ordering, and output paths.")
left, right = st.columns(2)
with left:
    url = st.text_input("Search URL", value=DEFAULT_URL)
    output_path = DEFAULT_OUTPUT
    st.caption(f"Output CSV: `{output_path}`")
    all_pages = st.checkbox("Follow next_page_url (all pages)", value=True)
    max_pages = st.number_input(
        "Max pages (0 = no limit)",
        min_value=0,
        max_value=10000,
        value=0,
        step=1,
    )
    sleep_seconds = st.number_input(
        "Delay between pages (seconds)",
        min_value=0.0,
        max_value=20.0,
        value=0.0,
        step=0.1,
    )
    checkpoint_every = st.number_input(
        "Checkpoint every N listings (0 = disable)",
        min_value=0,
        max_value=5000,
        value=100,
        step=10,
    )

with right:
    priority_state = st.text_input("Priority state (e.g. VIC)", value="VIC")
    skip_existing = st.checkbox("Skip listings already in output", value=True)
    block_resources = st.checkbox("Block images/media/fonts", value=True)
    show_command = st.checkbox("Show command preview", value=False)

section_heading("Auth & Browser", "Use storage state for 403 bypass and run headful.")
auth_left, auth_right = st.columns(2)
with auth_left:
    storage_state = st.text_input("Storage state path", value=DEFAULT_STORAGE_STATE)
    cookie_file = st.text_input("Cookie file path (optional)", value="")
    headful = st.checkbox("Headful browser (recommended)", value=True)

with auth_right:
    browser = st.selectbox(
        "Playwright browser",
        options=["chromium", "chrome", "msedge", "firefox", "webkit"],
        index=1,
    )
    wait_mode = st.selectbox(
        "Playwright wait mode",
        options=["domcontentloaded", "load", "networkidle"],
        index=1,
    )
    playwright_timeout = st.number_input(
        "Playwright timeout (seconds)",
        min_value=5,
        max_value=180,
        value=60,
        step=5,
    )
    slowmo = st.number_input(
        "Playwright slowmo (ms)",
        min_value=0,
        max_value=2000,
        value=0,
        step=50,
    )

section_heading("Storage State Helper", "Refresh the login session if 403s appear.")
helper_left, helper_right = st.columns(2)
with helper_left:
    state_url = st.text_input("Login URL", value=url)
    wait_seconds = st.number_input(
        "Wait before saving state (seconds)",
        min_value=30,
        max_value=600,
        value=240,
        step=30,
    )
with helper_right:
    retries = st.number_input("Retry count", min_value=1, max_value=10, value=5, step=1)
    retry_delay = st.number_input(
        "Retry delay (seconds)",
        min_value=0.5,
        max_value=10.0,
        value=3.0,
        step=0.5,
    )
    create_state_clicked = st.button("Create/Refresh storage state", key="autotrader_create_state")


def _build_scrape_command() -> list[str]:
    command = [sys.executable, "autotrader_isolated/scrape_first_page.py"]
    if url:
        command.extend(["--url", url])
    if output_path:
        command.extend(["--output", output_path])
    if storage_state:
        command.extend(["--storage-state", storage_state])
    if cookie_file:
        command.extend(["--cookie-file", cookie_file])
    if all_pages:
        command.append("--all-pages")
    if max_pages > 0:
        command.extend(["--max-pages", str(int(max_pages))])
    if sleep_seconds > 0:
        command.extend(["--sleep-seconds", str(sleep_seconds)])
    if checkpoint_every >= 0:
        command.extend(["--checkpoint-every", str(int(checkpoint_every))])
    if priority_state:
        command.extend(["--priority-state", priority_state])
    if skip_existing:
        command.append("--skip-existing")
    if headful:
        command.append("--playwright-headful")
    if browser:
        command.extend(["--playwright-browser", browser])
    if wait_mode:
        command.extend(["--playwright-wait", wait_mode])
    if block_resources:
        command.append("--playwright-block-resources")
    if slowmo > 0:
        command.extend(["--playwright-slowmo", str(int(slowmo))])
    if playwright_timeout:
        command.extend(["--playwright-timeout", str(int(playwright_timeout))])
    return command


def _build_storage_state_command() -> list[str]:
    command = [sys.executable, "autotrader_isolated/create_storage_state.py"]
    if state_url:
        command.extend(["--url", state_url])
    if storage_state:
        command.extend(["--output", storage_state])
    if browser:
        command.extend(["--browser", browser])
    if wait_mode:
        command.extend(["--wait", wait_mode])
    if playwright_timeout:
        command.extend(["--timeout", str(int(playwright_timeout))])
    if slowmo > 0:
        command.extend(["--slowmo", str(int(slowmo))])
    if retries:
        command.extend(["--retries", str(int(retries))])
    if retry_delay:
        command.extend(["--retry-delay", str(retry_delay)])
    if wait_seconds:
        command.extend(["--wait-seconds", str(int(wait_seconds))])
    return command


def _command_preview(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def _render_command_result(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout.strip():
        st.code(result.stdout, language="text")
    if result.stderr.strip():
        st.code(result.stderr, language="text")


if show_command:
    st.code(_command_preview(_build_scrape_command()), language="powershell")

if create_state_clicked:
    with st.spinner("Opening browser to refresh storage state..."):
        result = _run_command(_build_storage_state_command())
        if result.returncode == 0:
            st.success("Storage state saved.")
        else:
            st.error("Storage state refresh failed. Check the terminal output.")
        _render_command_result(result)

if run_clicked:
    with st.spinner("Running Autotrader scraper..."):
        result = _run_command(_build_scrape_command())
        if result.returncode == 0:
            st.success("Scrape completed.")
        else:
            st.error("Scraper failed. Check the terminal output.")
        _render_command_result(result)

section_heading("Latest Output", "Preview the newest Autotrader results.")
output_file = ROOT_DIR / DEFAULT_OUTPUT
if output_file.exists():
    try:
        results = pd.read_csv(output_file)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read {output_file}: {exc}")
    else:
        last_run = datetime.fromtimestamp(output_file.stat().st_mtime, tz=timezone.utc).astimezone()
        row_count = len(results)
        unique_urls = results["url"].nunique() if "url" in results.columns else 0
        vic_share = (
            results["location"].astype(str).str.contains(r"\\bVIC\\b", case=False, na=False).mean()
            if "location" in results.columns and row_count
            else 0
        )
        summary_html = clean_html(
            f"""
            <div class="autosniper-section">
                <div class="section-title">Autotrader snapshot</div>
                <div class="section-subtitle">Last updated {last_run:%d %b %Y %H:%M}</div>
            </div>
            """
        )
        st.markdown(summary_html, unsafe_allow_html=True)
        metric_cols = st.columns(3)
        metric_cols[0].metric("Rows", f"{row_count:,}")
        metric_cols[1].metric("Unique URLs", f"{unique_urls:,}")
        metric_cols[2].metric("VIC share", f"{vic_share:.0%}")
        preview_all = st.checkbox("Show full table (may be slow)", value=False)
        preview_limit = st.selectbox("Preview rows", [50, 100, 200, 500, 1000], index=1)
        preview_df = results if preview_all else results.head(int(preview_limit))
        st.caption(f"Showing {len(preview_df):,} of {row_count:,} rows.")
        st.dataframe(preview_df, width="stretch", hide_index=True)
else:
    st.info("Run the scraper to generate the Autotrader output CSV.")
