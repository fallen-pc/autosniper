import streamlit as st


def display_profit_bar(profit_str: str, verdict: str) -> None:
    """Display a progress bar representing the profit margin.

    Parameters
    ----------
    profit_str : str
        Profit margin percentage as a string, e.g. "25%".
    verdict : str
        Verdict text to display alongside the profit margin.
    """
    try:
        percent = float(str(profit_str).strip('%'))
        st.markdown(f"**Profit Margin: {profit_str} — Verdict: {verdict}**")
        st.progress(min(percent / 100, 1.0))
    except Exception:
        st.warning("⚠️ Could not parse profit margin.")
