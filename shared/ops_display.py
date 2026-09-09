"""Read-only explanations for operational records; does not change pipeline policy."""
import pandas as pd


def reason_category(reason: object) -> str:
    code = str(reason).strip().strip("[]").lower()
    if code == "ok":
        return "Successful records"
    if code in {"out_of_scope", "out_of_scope_year", "disallowed_variant", "motorcycle"}:
        return "Expected scope exclusions"
    if code.startswith(("missing_", "bad_", "ambig_")):
        return "Data needing review"
    if code in {"fetch_failed", "fetch_failed_threshold", "http_error", "timeout", "scrape_failed"}:
        return "Collection failures"
    return "Unclassified — investigate"


ISSUE_GUIDANCE = {
    "NO_URL": ("Missing identity", "Check the original source record and restore its full listing URL before any valuation or notes are trusted."),
    "BAD_PARSE": ("Data needing review", "Open Detail and compare year, make and model with the auction listing. Correct the source parsing before repricing."),
    "MISSING_VARIANT": ("Data needing review", "Check the auction description and photos for the exact variant; verify the tag before using a resale curve."),
    "MISSING_VIN": ("Data needing review", "Check the auction listing or inspection evidence for a complete VIN. Do not invent a missing identifier."),
    "MISSING_ODOM": ("Data needing review", "Check the odometer reading and units against the auction evidence before curve pricing."),
    "NO_TAG": ("Coverage / classification review", "Check the identity in Detail. Establish whether this vehicle belongs in the supported buying scope before requesting a tag or curve."),
    "TAG_AMBIGUOUS": ("Coverage / classification review", "Compare variant, fuel and transmission with source evidence, then resolve the ambiguous tag before pricing."),
    "NO_CURVE": ("Coverage gap — not a scraper failure", "Check the tag and supported buying scope in Detail. If the vehicle is in scope, inspect Curves and add a needs-curve request from Detail. Out-of-scope vehicles do not require a new curve."),
    "LOW_CONFIDENCE": ("Valuation review", "Open AI Analysis and inspect the named evidence gaps and condition costs before using the bid ceiling."),
    "COND_NOTES_EMPTY": ("Missing condition evidence", "Inspect the auction description and photos. Empty notes do not mean the vehicle has no defects."),
    "NOT_ACTIVE": ("Lifecycle information", "Check whether the auction ended or the record is outside the active feed. No repair is needed for an intentionally inactive listing."),
}


def issue_guidance(code: str) -> tuple[str, str]:
    return ISSUE_GUIDANCE.get(code, ("Unclassified issue", "Inspect Detail and the original auction evidence before deciding what to change."))


def filtered_issue_summary(exploded: pd.DataFrame, visible_urls) -> pd.DataFrame:
    """Count each full listing URL once per issue, within the same filtered population."""
    selected = exploded[exploded["url"].isin(visible_urls)].drop_duplicates(["url", "issue_code"])
    return selected.groupby("issue_code").size().reset_index(name="count").sort_values("count", ascending=False)
