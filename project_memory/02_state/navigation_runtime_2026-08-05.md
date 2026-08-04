# Local and VPS Navigation Split

- Local Streamlit runs now default to Dashboard and omit the VPS-only Scraper Operations page.
- The `/opt/autosniper` runtime, or an explicit `AUTOSNIPER_VPS_MODE=1`, defaults to Scraper Operations while keeping Dashboard available.
- Grouped sidebar navigation is rendered consistently from each routable page so direct page URLs retain the full menu.
- Verification: `tests/test_navigation_and_health_ui.py` passed (3 tests), Python compile validation passed, and the local `/_stcore/health` endpoint returned `ok` on port 8501.
