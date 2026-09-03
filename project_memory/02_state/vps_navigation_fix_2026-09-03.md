# VPS navigation fix - 2026-09-03

- Removed the Scraper Operations link to `pages/7_AUTOTRADER_SCRAPER.py` in VPS mode.
- The Autotrader control page remains intentionally development-only because it can launch scraper work and write runtime data.
- Added a regression test requiring every `st.page_link` on the VPS Scraper Operations page to target a page registered by the VPS navigation specification.
- Verification: `tests/test_navigation_and_health_ui.py` passes with 4 tests.
