"""Read-only Dashboard population summaries."""
import pandas as pd


def ai_scope_valuation_counts(scope: pd.DataFrame, valuations: pd.DataFrame) -> tuple[int, int]:
    """Count unique eligible URLs with a saved valuation, excluding blank IDs."""
    def urls(frame):
        if frame.empty or "url" not in frame.columns:
            return set()
        values = frame["url"].dropna().astype(str).str.strip()
        return set(values[values != ""])

    eligible = urls(scope)
    return len(eligible & urls(valuations)), len(eligible)
