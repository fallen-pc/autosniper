from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from shared.repair_review import LIVE_QUEUE_PATH
from shared.styling import clean_html, display_banner, escape_html, inject_global_styles, page_intro


st.set_page_config(page_title="Repair Review", layout="wide")
inject_global_styles()
display_banner()
page_intro(
    "REPAIR REVIEW",
    "Review unclassified Grays condition fragments before promoting them into repair dictionary rules.",
    show_logo=False,
)


REPORT_DIR = Path("CSV_data/reports")
LINES_PATH = REPORT_DIR / "grays_condition_repair_lines.csv"
FRAGMENTS_PATH = REPORT_DIR / "grays_condition_repair_fragments.csv"
SUMMARY_PATH = REPORT_DIR / "grays_condition_repair_summary.json"
DECISIONS_PATH = REPORT_DIR / "repair_review_decisions.csv"

REVIEW_COLUMNS = [
    "repair_key",
    "repair_item",
    "review_bucket",
    "decision",
    "target_category",
    "canonical_defect",
    "severity_hint",
    "cost_model",
    "notes",
]

BODY_LOCATION_RE = re.compile(
    r"\b(roof|bonnet|bumper|bar|door|doors|boot|bootlid|tailgate|guard|panel|quarter|fender|mirror|"
    r"headlight|tail light|lamp|pillar|rail|spoiler|fender)\b",
    re.IGNORECASE,
)
REPAIR_WORD_RE = re.compile(
    r"\b(broken|cracked|hazed|requires attention|not working|inoperable|worn|torn|rust|corrosion|"
    r"dent|scratch|scuff|damage|damaged|leak|light on|misaligned|faded|sagging|peeling|missing|fault)\b",
    re.IGNORECASE,
)
BOILERPLATE_RE = re.compile(
    r"\b(wovr|written off|salvage|roadworthy|state-based road authority|mechanical inspection|"
    r"public liability certificate|workers compensation|high risk license|swms|legislative|"
    r"additional documentation|repair receipts|stored|inspected|therefore|where is|as is)\b",
    re.IGNORECASE,
)
FEATURE_RE = re.compile(
    r"\b(reverse camera|reversing camera|navigation|satellite navigation|roof racks|bullbar|bull bar|"
    r"alloy wheels|leather trim|parking assist|drivers airbag|dvd players|uhf|sunroof|roof rail)\b",
    re.IGNORECASE,
)
USAGE_RISK_RE = re.compile(r"\b(mine site|ex[- ]?rental|taxi|police|beach|farm)\b", re.IGNORECASE)


@st.cache_data(ttl=60)
def load_lines() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if not LINES_PATH.exists():
        base = pd.DataFrame()
    else:
        base = pd.read_csv(LINES_PATH).fillna("")
    if not base.empty:
        frames.append(base)
    if LIVE_QUEUE_PATH.exists():
        live = pd.read_csv(LIVE_QUEUE_PATH).fillna("")
        if not live.empty:
            frames.append(live)
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]

    combined = pd.concat(frames, ignore_index=True, sort=False).fillna("")
    combined["_source_rank"] = combined["source_file"].astype(str).eq("AI_ANALYSIS_LIVE").astype(int)
    combined.sort_values(["_source_rank"], ascending=[True], inplace=True)
    combined = combined.drop_duplicates(subset=["repair_key"], keep="last")
    return combined.drop(columns=["_source_rank"], errors="ignore")


@st.cache_data(ttl=60)
def load_fragments() -> pd.DataFrame:
    if not FRAGMENTS_PATH.exists():
        return pd.DataFrame()
    return pd.read_csv(FRAGMENTS_PATH).fillna("")


@st.cache_data(ttl=60)
def load_summary() -> dict[str, object]:
    if not SUMMARY_PATH.exists():
        return {}
    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_decisions() -> pd.DataFrame:
    if not DECISIONS_PATH.exists():
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    try:
        df = pd.read_csv(DECISIONS_PATH).fillna("")
    except Exception:
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    for column in REVIEW_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df[REVIEW_COLUMNS]


def safe_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def review_bucket(row: pd.Series) -> str:
    item = safe_text(row.get("repair_item"))
    status = safe_text(row.get("status"))
    category = safe_text(row.get("category"))
    canonical = safe_text(row.get("canonical_defects"))
    if status == "not_assessed_after_hard_avoid":
        return "Hard-avoid skipped"
    if status == "matched":
        return "Already matched"
    if status == "ignored" or category == "boilerplate":
        return "Ignore / boilerplate"
    if BOILERPLATE_RE.search(item):
        return "Ignore / boilerplate"
    if USAGE_RISK_RE.search(item):
        return "Usage risk"
    if FEATURE_RE.search(item) and not REPAIR_WORD_RE.search(item):
        return "Feature-list leak"
    if BODY_LOCATION_RE.search(item) and not REPAIR_WORD_RE.search(item):
        return "Context fragment"
    if REPAIR_WORD_RE.search(item):
        return "Real repair gap"
    if canonical == "body_location_list":
        return "Context fragment"
    return "Unknown"


def apply_decisions(df: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    if decisions.empty or "repair_key" not in decisions.columns:
        for column in ["decision", "target_category", "canonical_defect"]:
            df[column] = ""
        return df
    latest = decisions.drop_duplicates(subset=["repair_key"], keep="last")
    merged = df.merge(
        latest[["repair_key", "decision", "target_category", "canonical_defect"]],
        on="repair_key",
        how="left",
    )
    for column in ["decision", "target_category", "canonical_defect"]:
        merged[column] = merged[column].fillna("")
    return merged


def upsert_decision(record: dict[str, str]) -> None:
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    decisions = load_decisions()
    decisions = decisions[decisions["repair_key"] != record["repair_key"]].copy()
    decisions = pd.concat([decisions, pd.DataFrame([record])], ignore_index=True)
    decisions.to_csv(DECISIONS_PATH, index=False)


def display_metric(label: str, value: object, sub: str = "") -> str:
    return (
        '<div class="repair-review-metric">'
        f'<div class="repair-review-label">{label}</div>'
        f'<div class="repair-review-value">{value}</div>'
        f'<div class="repair-review-sub">{sub}</div>'
        "</div>"
    )


def display_selection(label: str, value: object) -> str:
    display_value = safe_text(value) or "Blank"
    return (
        '<div class="repair-review-selection">'
        f'<div class="repair-review-selection-label">{escape_html(label)}</div>'
        f'<div class="repair-review-selection-value">{escape_html(display_value)}</div>'
        "</div>"
    )


def widget_key(prefix: str, repair_key: object) -> str:
    cleaned = re.sub(r"[^a-z0-9_]+", "_", safe_text(repair_key).lower()).strip("_")
    return f"{prefix}_{cleaned[:80] or 'row'}"


def canonical_from_repair_key(repair_key: object) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", safe_text(repair_key).lower()).strip("_")
    return cleaned[:80]


def suggested_review_defaults(selected: pd.Series, existing: pd.Series) -> dict[str, str]:
    status = safe_text(selected.get("status"))
    category = safe_text(selected.get("category"))
    canonical = safe_text(existing.get("canonical_defect")) or safe_text(selected.get("canonical_defects"))
    severity = safe_text(existing.get("severity_hint"))
    cost_model = safe_text(existing.get("cost_model"))

    if status == "hard_avoid":
        if not severity:
            severity = "high"
        if not cost_model:
            cost_model = "hard_avoid"
        if category == "mechanical" and not canonical:
            canonical = canonical_from_repair_key(selected.get("repair_key"))

    return {
        "target_category": safe_text(existing.get("target_category")) or category,
        "canonical_defect": canonical,
        "severity_hint": severity,
        "cost_model": cost_model,
        "notes": safe_text(existing.get("notes")),
    }


st.markdown(
    """
    <style>
    .repair-review-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.65rem;
        margin: 0.75rem 0 1rem;
    }
    .repair-review-metric {
        border: 1px solid rgba(39, 182, 255, 0.24);
        background: rgba(8, 12, 18, 0.64);
        border-radius: 8px;
        padding: 0.7rem 0.8rem;
        min-height: 82px;
    }
    .repair-review-label {
        font-size: 0.62rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: rgba(255,255,255,0.62);
    }
    .repair-review-value {
        margin-top: 0.3rem;
        font-size: 1.5rem;
        font-weight: 850;
        color: rgba(255,255,255,0.94);
    }
    .repair-review-sub {
        margin-top: 0.25rem;
        font-size: 0.72rem;
        color: rgba(255,255,255,0.58);
    }
    .repair-review-item {
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.035);
        border-radius: 8px;
        padding: 0.7rem 0.8rem;
        margin-top: 0.5rem;
    }
    .repair-review-item .k {
        font-size: 0.62rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: rgba(255,255,255,0.58);
    }
    .repair-review-item .v {
        margin-top: 0.25rem;
        color: rgba(255,255,255,0.9);
        overflow-wrap: anywhere;
    }
    .repair-review-selection-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.5rem;
        margin: 0.5rem 0 0.9rem;
    }
    .repair-review-selection {
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(255,255,255,0.04);
        border-radius: 8px;
        padding: 0.55rem 0.65rem;
        min-height: 62px;
    }
    .repair-review-selection-label {
        font-size: 0.58rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: rgba(255,255,255,0.58);
    }
    .repair-review-selection-value {
        margin-top: 0.25rem;
        font-size: 0.85rem;
        font-weight: 720;
        color: rgba(255,255,255,0.94);
        overflow-wrap: anywhere;
    }
    @media (max-width: 900px) {
        .repair-review-grid,
        .repair-review-selection-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

lines_df = load_lines()
if lines_df.empty:
    st.error(
        "Repair audit output is missing. Run `venv\\Scripts\\python.exe scripts\\extract_grays_condition_repairs.py` first."
    )
    st.stop()

for column in ["repair_key", "repair_item", "status", "category", "occurrences", "listing_count"]:
    if column not in lines_df.columns:
        lines_df[column] = ""

lines_df["occurrences"] = pd.to_numeric(lines_df["occurrences"], errors="coerce").fillna(0).astype(int)
lines_df["listing_count"] = pd.to_numeric(lines_df["listing_count"], errors="coerce").fillna(0).astype(int)
lines_df["review_bucket"] = lines_df.apply(review_bucket, axis=1)

decisions_df = load_decisions()
lines_df = apply_decisions(lines_df, decisions_df)
summary = load_summary()

metric_html = "".join(
    [
        display_metric("Fragments", f'{summary.get("fragment_occurrences", len(lines_df)):,}', "current audit"),
        display_metric("Deduped lines", f'{summary.get("deduped_repair_lines", len(lines_df)):,}', "review universe"),
        display_metric("Unclassified", f'{summary.get("unclassified_lines", 0):,}', "occurrences remaining"),
        display_metric("Decisions", f"{len(decisions_df):,}", "saved review rows"),
    ]
)
st.markdown(f'<div class="repair-review-grid">{metric_html}</div>', unsafe_allow_html=True)

queue_df = lines_df[lines_df["review_bucket"] != "Already matched"].copy()

st.sidebar.markdown("### Review Filters")
bucket_options = ["All"] + sorted(queue_df["review_bucket"].dropna().unique().tolist())
bucket_choice = st.sidebar.selectbox("Review bucket", bucket_options, index=0)
status_options = ["All"] + sorted(queue_df["status"].dropna().unique().tolist())
status_choice = st.sidebar.selectbox("Parser status", status_options, index=0)
decision_options = ["All", "Undecided", "Decided"]
decision_choice = st.sidebar.selectbox("Decision state", decision_options, index=1)
min_occurrences = st.sidebar.number_input("Minimum occurrences", min_value=1, value=3, step=1)
search_text = st.sidebar.text_input("Search repair text")
st.sidebar.markdown(
    clean_html(
        f"""
        <div class="repair-review-selection-grid" style="grid-template-columns: 1fr;">
            {display_selection("Review bucket", bucket_choice)}
            {display_selection("Parser status", status_choice)}
            {display_selection("Decision state", decision_choice)}
            {display_selection("Minimum occurrences", min_occurrences)}
            {display_selection("Search repair text", search_text)}
        </div>
        """
    ),
    unsafe_allow_html=True,
)

filtered_df = queue_df[queue_df["occurrences"] >= int(min_occurrences)].copy()
if bucket_choice != "All":
    filtered_df = filtered_df[filtered_df["review_bucket"] == bucket_choice].copy()
if status_choice != "All":
    filtered_df = filtered_df[filtered_df["status"] == status_choice].copy()
if decision_choice == "Undecided":
    filtered_df = filtered_df[filtered_df["decision"] == ""].copy()
elif decision_choice == "Decided":
    filtered_df = filtered_df[filtered_df["decision"] != ""].copy()
if search_text.strip():
    needle = search_text.strip().lower()
    filtered_df = filtered_df[
        filtered_df["repair_item"].astype(str).str.lower().str.contains(needle, regex=False)
        | filtered_df["repair_key"].astype(str).str.lower().str.contains(needle, regex=False)
    ].copy()

filtered_df.sort_values(["occurrences", "repair_item"], ascending=[False, True], inplace=True)
filtered_occurrences = int(filtered_df["occurrences"].sum()) if not filtered_df.empty else 0

bucket_counts = (
    queue_df.groupby("review_bucket", as_index=False)
    .agg(unique_lines=("repair_key", "count"), occurrences=("occurrences", "sum"))
    .sort_values("occurrences", ascending=False)
)

bucket_tab, queue_tab, decision_tab = st.tabs(["Buckets", "Review Queue", "Saved Decisions"])

with bucket_tab:
    st.markdown("### Review Buckets")
    st.dataframe(bucket_counts, use_container_width=True, hide_index=True)

with queue_tab:
    queue_heading = f"{decision_choice} Queue" if decision_choice != "All" else "Queue"
    st.markdown(f"### {queue_heading} ({len(filtered_df):,} unique lines)")
    st.caption(
        "Queue count is deduped repair lines. The occurrence numbers are listing/fragments seen across the Grays audit, "
        "so adding row occurrences will be much higher than the unique-line queue count. Saved lines drop out of the "
        "default Undecided queue; use Decision state = Decided or All to inspect saved reviews."
    )
    st.markdown(
        clean_html(
            f"""
            <div class="repair-review-selection-grid">
                {display_selection("Shown unique lines", f"{len(filtered_df):,}")}
                {display_selection("Shown occurrences", f"{filtered_occurrences:,}")}
                {display_selection("Meaning of row number", "Occurrences across listings/fragments")}
                {display_selection("Meaning of queue number", "Unique deduped repair lines")}
            </div>
            """
        ),
        unsafe_allow_html=True,
    )
    display_cols = [
        "review_bucket",
        "repair_item",
        "occurrences",
        "status",
        "category",
        "canonical_defects",
        "decision",
        "target_category",
        "canonical_defect",
    ]
    st.dataframe(filtered_df[display_cols].head(250), use_container_width=True, hide_index=True)

    if filtered_df.empty:
        st.info("No review rows match the current filters.")
    else:
        labels = [
            f'{row.repair_item} [{row.review_bucket}, {int(row.occurrences)}]'
            for row in filtered_df.itertuples(index=False)
        ]
        selected_label = st.selectbox("Select row to review", labels)
        selected_idx = labels.index(selected_label)
        selected = filtered_df.iloc[selected_idx]
        st.markdown(
            clean_html(
                f"""
                <div class="repair-review-selection-grid">
                    {display_selection("Selected row", selected_label)}
                    {display_selection("Bucket", selected.get("review_bucket"))}
                    {display_selection("Status", selected.get("status"))}
                    {display_selection("Occurrences", selected.get("occurrences"))}
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

        detail_cols = st.columns([1, 1])
        with detail_cols[0]:
            st.markdown(
                clean_html(
                    f"""
                    <div class="repair-review-item">
                      <div class="k">Repair fragment</div>
                      <div class="v">{safe_text(selected.get("repair_item"))}</div>
                    </div>
                    <div class="repair-review-item">
                      <div class="k">Suggested bucket</div>
                      <div class="v">{safe_text(selected.get("review_bucket"))}</div>
                    </div>
                    <div class="repair-review-item">
                      <div class="k">Current parser output</div>
                      <div class="v">status={safe_text(selected.get("status"))} | category={safe_text(selected.get("category"))} | match={safe_text(selected.get("canonical_defects"))}</div>
                    </div>
                    """
                ),
                unsafe_allow_html=True,
            )
        with detail_cols[1]:
            st.markdown(
                clean_html(
                    f"""
                    <div class="repair-review-item">
                      <div class="k">Example vehicles</div>
                      <div class="v">{safe_text(selected.get("example_vehicles"))}</div>
                    </div>
                    <div class="repair-review-item">
                      <div class="k">Example condition notes</div>
                      <div class="v">{safe_text(selected.get("example_condition_notes"))}</div>
                    </div>
                    """
                ),
                unsafe_allow_html=True,
            )

        fragments_df = load_fragments()
        matching_fragments = pd.DataFrame()
        if not fragments_df.empty and "repair_key" in fragments_df.columns:
            matching_fragments = fragments_df[fragments_df["repair_key"] == selected["repair_key"]].head(25)
        with st.expander("Occurrence examples", expanded=False):
            if matching_fragments.empty:
                st.write("No occurrence-level examples found.")
            else:
                example_cols = [
                    col
                    for col in [
                        "vehicle",
                        "repair_item",
                        "status",
                        "category",
                        "general_condition",
                        "url",
                    ]
                    if col in matching_fragments.columns
                ]
                st.dataframe(matching_fragments[example_cols], use_container_width=True, hide_index=True)

        st.markdown("### Save Review Decision")
        default_bucket = safe_text(selected.get("review_bucket"))
        selected_repair_key = safe_text(selected.get("repair_key"))
        category_options = [
            "",
            "cosmetic",
            "glass",
            "replacement",
            "interior",
            "mechanical",
            "structural",
            "boilerplate",
            "usage_risk",
            "context_fragment",
            "feature_leak",
        ]
        decision_options_form = [
            "Add dictionary rule",
            "Ignore as boilerplate",
            "Mark feature-list leak",
            "Mark context fragment",
            "Mark usage risk",
            "Leave unclassified",
        ]
        suggested_decision = {
            "Ignore / boilerplate": "Ignore as boilerplate",
            "Feature-list leak": "Mark feature-list leak",
            "Context fragment": "Mark context fragment",
            "Usage risk": "Mark usage risk",
            "Real repair gap": "Add dictionary rule",
        }.get(default_bucket, "Leave unclassified")
        existing_decision = decisions_df[decisions_df["repair_key"] == selected_repair_key]
        if not existing_decision.empty:
            existing = existing_decision.iloc[-1]
            suggested_decision = safe_text(existing.get("decision")) or suggested_decision
        else:
            existing = pd.Series(dtype=object)
        defaults = suggested_review_defaults(selected, existing)
        category_default = defaults["target_category"]
        severity_default = defaults["severity_hint"]
        cost_default = defaults["cost_model"]

        decision_index = decision_options_form.index(suggested_decision) if suggested_decision in decision_options_form else 0
        category_index = category_options.index(category_default) if category_default in category_options else 0
        severity_options = ["", "low", "medium", "high"]
        severity_index = severity_options.index(severity_default) if severity_default in severity_options else 0
        cost_options = ["", "no_cost", "cosmetic_panel", "fixed_replacement", "glass", "hard_avoid"]
        cost_index = cost_options.index(cost_default) if cost_default in cost_options else 0

        c1, c2, c3 = st.columns(3)
        with c1:
            decision = st.selectbox(
                "Decision",
                decision_options_form,
                index=decision_index,
                key=widget_key("decision", selected_repair_key),
            )
            target_category = st.selectbox(
                "Target category",
                category_options,
                index=category_index,
                key=widget_key("target_category", selected_repair_key),
            )
        with c2:
            canonical_defect = st.text_input(
                "Canonical defect",
                value=defaults["canonical_defect"],
                key=widget_key("canonical_defect", selected_repair_key),
            )
            severity_hint = st.selectbox(
                "Severity hint",
                severity_options,
                index=severity_index,
                key=widget_key("severity", selected_repair_key),
            )
        with c3:
            cost_model = st.selectbox(
                "Cost model",
                cost_options,
                index=cost_index,
                key=widget_key("cost_model", selected_repair_key),
            )
            notes = st.text_area(
                "Notes",
                value=defaults["notes"],
                height=92,
                key=widget_key("notes", selected_repair_key),
            )

        st.markdown(
            clean_html(
                f"""
                <div class="repair-review-selection-grid">
                    {display_selection("Decision", decision)}
                    {display_selection("Target category", target_category)}
                    {display_selection("Canonical defect", canonical_defect)}
                    {display_selection("Severity hint", severity_hint)}
                    {display_selection("Cost model", cost_model)}
                    {display_selection("Notes", notes)}
                </div>
                """
            ),
            unsafe_allow_html=True,
        )

        if st.button("Save decision", key=widget_key("save_decision", selected_repair_key)):
            record = {
                "repair_key": selected_repair_key,
                "repair_item": safe_text(selected.get("repair_item")),
                "review_bucket": default_bucket,
                "decision": decision,
                "target_category": target_category,
                "canonical_defect": canonical_defect,
                "severity_hint": severity_hint,
                "cost_model": cost_model,
                "notes": notes,
            }
            upsert_decision(record)
            st.cache_data.clear()
            st.toast(f"Saved review decision for {record['repair_item']}.")
            st.rerun()

with decision_tab:
    st.markdown("### Saved Decisions")
    decisions_df = load_decisions()
    if decisions_df.empty:
        st.info("No review decisions saved yet.")
    else:
        st.dataframe(decisions_df, use_container_width=True, hide_index=True)
        st.download_button(
            "Download decisions CSV",
            data=decisions_df.to_csv(index=False),
            file_name="repair_review_decisions.csv",
            mime="text/csv",
        )

st.caption("Review decisions are local generated data and are written under CSV_data/reports.")
