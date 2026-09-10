"""Resolve a cold /DASHBOARD request through the authenticated app router.

Streamlit scans pages/ before app.py first registers st.navigation. Dashboard
lives at the repository root, so this compatibility entry makes its URL known
during that initial scan. The curated navigation still owns the actual page.
"""

from pathlib import Path
import runpy


runpy.run_path(str(Path(__file__).resolve().parents[1] / "app.py"))
