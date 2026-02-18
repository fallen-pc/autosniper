"""Location helpers used across UI and pipeline."""

from __future__ import annotations


STATE_ABBREVIATIONS = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")


def extract_state(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    upper = text.upper()
    for state in STATE_ABBREVIATIONS:
        if state in upper:
            return state
    if "," in text:
        return text.split(",")[-1].strip().upper()
    parts = text.split()
    if parts:
        return parts[-1].strip().upper()
    return upper
