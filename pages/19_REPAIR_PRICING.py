from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from shared.navigation import render_sidebar_navigation

from shared.csv_utils import CSV_READ_ERRORS
from shared.repair_pricing_schedule import (
    PRICING_COLUMNS,
    PRICING_METHODS,
    QUOTE_COLUMNS,
    SUPPLIER_TYPES,
    VEHICLE_CLASSES,
    REAL_VEHICLE_CLASSES,
    REPAIR_PRICING_MATRIX_PATH,
    apply_quote_response,
    build_quote_request_body,
    build_quote_request_subject,
    canonical_pricing_candidates,
    load_pricing_schedule,
    load_quote_requests,
    needs_pricing,
    next_request_id,
    pricing_row_from_quote,
    save_pricing_schedule,
    save_quote_requests,
)
from shared.repair_review import safe_text
from shared.repair_workbench import LEDGER_STATUSES, pricing_coverage_ledger
from shared.styling import clean_html, display_banner, escape_html, inject_global_styles, page_intro


st.set_page_config(page_title="Repair Pricing", layout="wide")
render_sidebar_navigation()
inject_global_styles()
display_banner()
page_intro(
    "REPAIR PRICING",
    "Build a quote-backed pricing schedule for canonical repair items.",
    show_logo=False,
)


def money(value: object) -> str:
    text = safe_text(value)
    if not text:
        return ""
    try:
        return f"${float(str(text).replace(',', '').replace('$', '')):,.0f}"
    except ValueError:
        return text


def metric_card(label: str, value: object, sub: str = "") -> str:
    return (
        '<div class="repair-pricing-card">'
        f'<div class="repair-pricing-label">{escape_html(label)}</div>'
        f'<div class="repair-pricing-value">{escape_html(value)}</div>'
        f'<div class="repair-pricing-sub">{escape_html(sub)}</div>'
        "</div>"
    )


def non_empty_count(df: pd.DataFrame, column: str) -> int:
    if df.empty or column not in df.columns:
        return 0
    return int((df[column].map(safe_text) != "").sum())


@st.cache_data(ttl=60)
def load_pricing_matrix(path: Path = REPAIR_PRICING_MATRIX_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path).fillna("")
    except CSV_READ_ERRORS:
        return pd.DataFrame()


def ledger_cell(row: pd.Series) -> str:
    status = safe_text(row.get("status")) or "Missing"
    value = money(row.get("default_estimate")) or "—"
    hits = int(row.get("occurrences", 0) or 0)
    return f"{status.upper()} · {value} · {hits:,} hits"


def ledger_metric(label: str, value: object, sub: str = "") -> None:
    st.markdown(
        clean_html(metric_card(label, value, sub)),
        unsafe_allow_html=True,
    )


st.markdown(
    clean_html(
        """
        <style>
        /* .repair-pricing-grid's grid/gap/margin (plus its responsive
           breakpoint) now come from the shared .autosniper-repair-grid
           class in shared/styling.py -- was an identical duplicate of the
           .repair-review-grid rule in 18_REPAIR_REVIEW.py. */
        .repair-pricing-card {
            border: 1px solid rgba(255,255,255,0.1);
            background: rgba(255,255,255,0.04);
            border-radius: 8px;
            padding: 0.7rem 0.8rem;
            min-height: 78px;
        }
        .repair-pricing-label {
            font-size: 0.6rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--autosniper-muted);
        }
        .repair-pricing-value {
            margin-top: 0.3rem;
            font-size: 1.35rem;
            font-weight: 820;
            color: var(--autosniper-primary);
        }
        .repair-pricing-sub {
            margin-top: 0.25rem;
            font-size: 0.72rem;
            color: var(--autosniper-muted);
        }
        .repair-pricing-note {
            border-left: 3px solid rgba(39, 182, 255, 0.55);
            background: rgba(39, 182, 255, 0.06);
            padding: 0.7rem 0.85rem;
            margin: 0.5rem 0 1rem;
            border-radius: 0 8px 8px 0;
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)


candidates_df = canonical_pricing_candidates()
pricing_df = load_pricing_schedule()
quotes_df = load_quote_requests()
needs_df = needs_pricing(candidates_df, pricing_df)
matrix_df = load_pricing_matrix()
ledger_df = pricing_coverage_ledger(matrix_df, pricing_df)

priced_count = non_empty_count(pricing_df, "canonical_defect")
quote_open_count = 0
if not quotes_df.empty and "status" in quotes_df.columns:
    quote_open_count = int(quotes_df["status"].map(safe_text).isin({"draft", "ready", "sent", "waiting"}).sum())

st.markdown(
    clean_html(
        f"""
        <div class="repair-pricing-grid autosniper-repair-grid">
            {metric_card("Canonical items", f"{len(candidates_df):,}", "from Repair Review decisions")}
            {metric_card("Priced items", f"{priced_count:,}", "saved pricing schedule")}
            {metric_card("Needs pricing", f"{len(needs_df):,}", "canonical items without pricing")}
            {metric_card("Open quote requests", f"{quote_open_count:,}", "draft/sent/waiting")}
        </div>
        """
    ),
    unsafe_allow_html=True,
)

st.markdown(
    clean_html(
        """
        <div class="repair-pricing-note">
        Wrecker prices are best for vehicle-specific bolt-on replacement parts where labour is minimal or can be estimated separately.
        Specialist repair quotes are still needed for glass, paint/panel, trim, upholstery, diagnostics, and mechanical work.
        </div>
        """
    ),
    unsafe_allow_html=True,
)

ledger_tab, needs_tab, schedule_tab, quotes_tab, responses_tab, evidence_tab = st.tabs(
    [
        "Coverage Ledger",
        "Needs Pricing",
        "Pricing Schedule",
        "Quote Requests",
        "Quote Responses",
        "Supplier Evidence",
    ]
)

with ledger_tab:
    st.markdown("### Repair Pricing Coverage Ledger")
    st.caption(
        "Every priceable repair type crossed with the five vehicle classes used by live repair assessment. "
        "Exact schedule rows carry an evidence-quality label; generic rows stay visibly generic and missing cells never borrow a guessed class multiplier."
    )
    if ledger_df.empty:
        st.warning(
            "The coverage matrix has not been generated yet. Run "
            "`venv\\Scripts\\python.exe -m scripts.build_repair_pricing_matrix --limit 0` to refresh it from all sold listings."
        )
    else:
        status_counts = ledger_df["status"].value_counts()
        missing_hits = int(ledger_df.loc[ledger_df["status"] == "Missing", "occurrences"].sum())
        exact_statuses = {"Verified", "Partial", "Provisional"}
        exact_count = int(ledger_df["status"].isin(exact_statuses).sum())
        metric_columns = st.columns(5)
        metric_values = [
            ("Total cells", f"{len(ledger_df):,}", "repair type × class"),
            ("Exact rows", f"{exact_count:,}", "verified/partial/provisional"),
            ("Generic fallback", f"{int(status_counts.get('Generic fallback', 0)):,}", "explicit generic schedule row"),
            ("Missing", f"{int(status_counts.get('Missing', 0)):,}", "no usable schedule row"),
            ("Unpriced hits", f"{missing_hits:,}", "observed sold-listing hits"),
        ]
        for column, (label, value, sub) in zip(metric_columns, metric_values):
            with column:
                ledger_metric(label, value, sub)

        filter_left, filter_right = st.columns([1.5, 1])
        with filter_left:
            ledger_search = st.text_input(
                "Search repair type",
                key="ledger_search",
                placeholder="paint damage, seat, windscreen...",
            )
        with filter_right:
            ledger_status = st.selectbox(
                "Coverage status",
                ["All"] + LEDGER_STATUSES,
                key="ledger_status",
            )

        visible = ledger_df.copy()
        if ledger_search.strip():
            visible = visible[
                visible["canonical_defect"].str.contains(ledger_search.strip(), case=False, regex=False)
            ].copy()
        if ledger_status != "All":
            matching_canonicals = set(visible.loc[visible["status"] == ledger_status, "canonical_defect"])
            visible = visible[visible["canonical_defect"].isin(matching_canonicals)].copy()

        if visible.empty:
            st.info("No pricing rows match those filters.")
        else:
            category_lookup = candidates_df.set_index("canonical_defect")["category"].to_dict()
            ledger_rows: list[dict[str, object]] = []
            for canonical, group in visible.groupby("canonical_defect", sort=False):
                display_row: dict[str, object] = {
                    "repair type": canonical.replace("_", " "),
                    "category": category_lookup.get(canonical, "unknown"),
                    "cost model": safe_text(group.iloc[0].get("cost_model")),
                    "total hits": int(group["occurrences"].sum()),
                }
                for vehicle_class in REAL_VEHICLE_CLASSES:
                    cell = group[group["vehicle_class"] == vehicle_class]
                    display_row[vehicle_class.replace("_", " ")] = (
                        ledger_cell(cell.iloc[0]) if not cell.empty else "MISSING · — · 0 hits"
                    )
                ledger_rows.append(display_row)
            ledger_table = pd.DataFrame(ledger_rows).sort_values("total hits", ascending=False)
            st.dataframe(ledger_table, use_container_width=True, hide_index=True, height=510)

            detail_left, detail_right = st.columns([1.4, 1])
            with detail_left:
                detail_canonical = st.selectbox(
                    "Inspect repair type",
                    visible["canonical_defect"].drop_duplicates().tolist(),
                    format_func=lambda value: value.replace("_", " "),
                    key="ledger_canonical",
                )
            detail_classes = visible[visible["canonical_defect"] == detail_canonical]["vehicle_class"].tolist()
            with detail_right:
                detail_class = st.selectbox(
                    "Vehicle class",
                    detail_classes,
                    format_func=lambda value: value.replace("_", " "),
                    key="ledger_vehicle_class",
                )
            detail = visible[
                (visible["canonical_defect"] == detail_canonical)
                & (visible["vehicle_class"] == detail_class)
            ].iloc[0]
            detail_columns = st.columns(5)
            details = [
                ("Status", detail["status"]),
                ("Default", money(detail["default_estimate"]) or "—"),
                ("Observed hits", f"{int(detail['occurrences']):,}"),
                ("Confidence", safe_text(detail["confidence"]) or "—"),
                ("Evidence date", safe_text(detail["evidence_date"]) or "—"),
            ]
            for column, (label, value) in zip(detail_columns, details):
                with column:
                    st.metric(label, value)
            if safe_text(detail["evidence_source"]):
                st.info(f"Evidence: {safe_text(detail['evidence_source'])}")
            if detail["status"] == "Missing":
                st.warning("This exact class has no supported price. Use Needs Pricing to add a quote request for this gap.")
            elif detail["status"] == "Generic fallback":
                st.warning(
                    f"This class is using a generic row whose underlying evidence quality is {detail['evidence_quality']}."
                )

with needs_tab:
    st.markdown("### Canonical Items Needing Prices")
    if needs_df.empty:
        st.success("Every canonical repair item currently has a pricing schedule row.")
    else:
        st.dataframe(needs_df, use_container_width=True, hide_index=True)

        st.markdown("### Add Pricing Row")
        item_options = needs_df["canonical_defect"].tolist()
        selected_item = st.selectbox("Canonical repair item", item_options)
        selected = needs_df[needs_df["canonical_defect"] == selected_item].iloc[0]
        c1, c2, c3 = st.columns(3)
        with c1:
            vehicle_class = st.selectbox(
                "Vehicle class",
                VEHICLE_CLASSES,
                index=VEHICLE_CLASSES.index(safe_text(selected.get("suggested_vehicle_class")))
                if safe_text(selected.get("suggested_vehicle_class")) in VEHICLE_CLASSES
                else 0,
            )
            pricing_method = st.selectbox(
                "Pricing method",
                PRICING_METHODS,
                index=PRICING_METHODS.index(safe_text(selected.get("suggested_pricing_method")))
                if safe_text(selected.get("suggested_pricing_method")) in PRICING_METHODS
                else 0,
            )
        with c2:
            low_estimate = st.number_input("Low estimate", min_value=0, value=0, step=25)
            default_estimate = st.number_input("Default estimate", min_value=0, value=0, step=25)
            high_estimate = st.number_input("High estimate", min_value=0, value=0, step=25)
        with c3:
            supplier = st.text_input("Supplier / evidence source")
            evidence_date = st.date_input("Evidence date", value=date.today())
            confidence = st.selectbox("Confidence", ["low", "medium", "high"], index=0)
        notes = st.text_area("Notes", placeholder="Quote details, part condition, labour assumption, or vehicle specificity.")
        if st.button("Save pricing row"):
            new_row = {
                "canonical_defect": selected_item,
                "category": safe_text(selected.get("category")),
                "vehicle_class": vehicle_class,
                "pricing_method": pricing_method,
                "default_estimate": int(default_estimate),
                "low_estimate": int(low_estimate),
                "high_estimate": int(high_estimate),
                "confidence": confidence,
                "evidence_source": supplier,
                "evidence_date": evidence_date.isoformat(),
                "supplier": supplier,
                "vehicle_specific": safe_text(selected.get("vehicle_specific")),
                "labour_required": "no" if pricing_method == "wrecker_part_price" else "yes",
                "notes": notes,
            }
            same_defect = pricing_df["canonical_defect"].map(safe_text) == selected_item
            same_class = pricing_df["vehicle_class"].map(safe_text) == vehicle_class
            updated = pricing_df[~(same_defect & same_class)].copy()
            updated = pd.concat([updated, pd.DataFrame([new_row], columns=PRICING_COLUMNS)], ignore_index=True)
            save_pricing_schedule(updated)
            st.cache_data.clear()
            st.success(f"Saved pricing row for `{selected_item}`.")
            st.rerun()

with schedule_tab:
    st.markdown("### Pricing Schedule")
    if pricing_df.empty:
        st.info("No pricing rows saved yet.")
    else:
        edited = st.data_editor(
            pricing_df,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "pricing_method": st.column_config.SelectboxColumn("pricing_method", options=PRICING_METHODS),
                "vehicle_class": st.column_config.SelectboxColumn("vehicle_class", options=VEHICLE_CLASSES),
                "confidence": st.column_config.SelectboxColumn("confidence", options=["low", "medium", "high"]),
                "labour_required": st.column_config.SelectboxColumn("labour_required", options=["yes", "no", "unknown"]),
                "vehicle_specific": st.column_config.SelectboxColumn("vehicle_specific", options=["yes", "no", "unknown"]),
            },
        )
        if st.button("Save edited pricing schedule"):
            save_pricing_schedule(edited)
            st.cache_data.clear()
            st.success("Pricing schedule saved.")
            st.rerun()
        st.download_button(
            "Download pricing schedule CSV",
            data=pricing_df.to_csv(index=False),
            file_name="repair_pricing_schedule.csv",
            mime="text/csv",
        )

with quotes_tab:
    st.markdown("### Quote Request Tracker")
    if quotes_df.empty:
        st.info("No quote requests yet.")
    else:
        st.dataframe(quotes_df, use_container_width=True, hide_index=True)

    st.markdown("### Create Quote Request")
    quote_source = needs_df if not needs_df.empty else candidates_df
    if quote_source.empty:
        st.info("No canonical repair items available yet.")
    else:
        q_item = st.selectbox("Repair item", quote_source["canonical_defect"].tolist(), key="quote_item")
        q_row = quote_source[quote_source["canonical_defect"] == q_item].iloc[0]
        q1, q2, q3 = st.columns(3)
        with q1:
            q_suggested_class = safe_text(q_row.get("suggested_vehicle_class"))
            q_vehicle_class = st.selectbox(
                "Vehicle class",
                VEHICLE_CLASSES,
                index=VEHICLE_CLASSES.index(q_suggested_class) if q_suggested_class in VEHICLE_CLASSES else 0,
                key="quote_vehicle_class",
            )
            representative_vehicle = st.text_input(
                "Representative vehicle",
                value="2016 Toyota Corolla hatch" if q_vehicle_class == "small_hatch" else "",
            )
        with q2:
            supplier_type_default = safe_text(q_row.get("suggested_supplier_type"))
            supplier_type = st.selectbox(
                "Supplier type",
                SUPPLIER_TYPES,
                index=SUPPLIER_TYPES.index(supplier_type_default) if supplier_type_default in SUPPLIER_TYPES else 0,
            )
            supplier = st.text_input("Supplier / company")
        with q3:
            contact_method = st.selectbox("Contact method", ["gmail", "web_form", "phone", "manual_research"])
            status = st.selectbox("Status", ["draft", "ready", "sent", "waiting", "replied", "priced"], index=0)
        q_notes = st.text_area(
            "Request notes",
            placeholder="Specific repair to price, for example: replace a cracked front windscreen supplied and fitted.",
        )
        draft_subject = build_quote_request_subject(q_item)
        draft_body = build_quote_request_body(q_item, representative_vehicle, q_notes)
        with st.expander("Draft email preview", expanded=False):
            st.text_input("Subject", value=draft_subject, disabled=True)
            st.text_area("Body", value=draft_body, height=220, disabled=True)
        if st.button("Create quote request"):
            request_id = next_request_id(quotes_df)
            new_quote = {
                "request_id": request_id,
                "canonical_defect": q_item,
                "category": safe_text(q_row.get("category")),
                "vehicle_class": q_vehicle_class,
                "representative_vehicle": representative_vehicle,
                "supplier": supplier,
                "supplier_type": supplier_type,
                "contact_method": contact_method,
                "status": status,
                "request_date": date.today().isoformat(),
                "response_date": "",
                "quoted_low": "",
                "quoted_high": "",
                "quoted_default": "",
                "evidence_url": "",
                "draft_subject": draft_subject,
                "draft_body": draft_body,
                "notes": q_notes,
            }
            updated_quotes = pd.concat(
                [quotes_df, pd.DataFrame([new_quote], columns=QUOTE_COLUMNS)],
                ignore_index=True,
            )
            save_quote_requests(updated_quotes)
            st.success(f"Created quote request `{request_id}`.")
            st.rerun()

with responses_tab:
    st.markdown("### Quote Response Inbox")
    st.write(
        "Paste supplier replies here after Gmail responses arrive. The parser extracts low/high/default prices, then you can promote the reviewed quote into the pricing schedule."
    )
    if quotes_df.empty:
        st.info("No quote requests available yet.")
    else:
        reply_candidates = quotes_df[
            quotes_df["status"].map(safe_text).isin({"sent", "waiting", "replied"})
        ].copy()
        if reply_candidates.empty:
            st.info("No sent or waiting quote requests are ready for response import.")
        else:
            display_cols = [
                "request_id",
                "canonical_defect",
                "supplier",
                "recipient_email",
                "status",
                "quoted_low",
                "quoted_high",
                "quoted_default",
                "response_parse_status",
            ]
            st.dataframe(reply_candidates[display_cols], use_container_width=True, hide_index=True)
            response_request_id = st.selectbox(
                "Quote request",
                reply_candidates["request_id"].tolist(),
                key="response_request_id",
            )
            selected_response = reply_candidates[
                reply_candidates["request_id"] == response_request_id
            ].iloc[0]
            st.caption(
                f"{safe_text(selected_response.get('canonical_defect'))} / {safe_text(selected_response.get('supplier')) or safe_text(selected_response.get('recipient_email'))}"
            )
            response_text = st.text_area(
                "Supplier reply text",
                value=safe_text(selected_response.get("response_text")),
                height=180,
                placeholder="Paste the Gmail reply or phone-note transcript here.",
            )
            response_source = st.selectbox("Response source", ["gmail", "phone", "web_form", "manual_research"])
            response_date = st.date_input("Response date", value=date.today())
            if st.button("Parse and save response"):
                updated_quotes = apply_quote_response(
                    quotes_df,
                    response_request_id,
                    response_text,
                    response_date=response_date.isoformat(),
                    response_source=response_source,
                )
                save_quote_requests(updated_quotes)
                st.success(f"Saved parsed response for `{response_request_id}`.")
                st.rerun()

            parsed_row = pricing_row_from_quote(quotes_df, response_request_id)
            if parsed_row:
                st.markdown("### Promote Parsed Quote")
                p1, p2, p3 = st.columns(3)
                with p1:
                    st.metric("Low", money(parsed_row["low_estimate"]))
                with p2:
                    st.metric("Default", money(parsed_row["default_estimate"]))
                with p3:
                    st.metric("High", money(parsed_row["high_estimate"]))
                if st.button("Promote quote to pricing schedule"):
                    canonical = safe_text(parsed_row.get("canonical_defect"))
                    quote_vehicle_class = safe_text(parsed_row.get("vehicle_class")) or "generic"
                    same_defect = pricing_df["canonical_defect"].map(safe_text) == canonical
                    same_class = pricing_df["vehicle_class"].map(safe_text) == quote_vehicle_class
                    updated_pricing = pricing_df[~(same_defect & same_class)].copy()
                    updated_pricing = pd.concat(
                        [updated_pricing, pd.DataFrame([parsed_row], columns=PRICING_COLUMNS)],
                        ignore_index=True,
                    )
                    updated_quotes = quotes_df.copy()
                    updated_quotes.loc[
                        updated_quotes["request_id"].map(safe_text) == safe_text(response_request_id),
                        "status",
                    ] = "priced"
                    save_pricing_schedule(updated_pricing)
                    save_quote_requests(updated_quotes)
                    st.cache_data.clear()
                    st.success(f"Promoted `{canonical}` into the pricing schedule.")
                    st.rerun()
            else:
                st.info("Save a reply with a detected price before promoting it into the schedule.")

with evidence_tab:
    st.markdown("### Supplier Evidence Plan")
    st.write(
        "Use this tab as the checklist before Gmail/browser quote gathering. Searches and form submissions should be recorded as quote requests before prices are promoted into the schedule."
    )
    st.markdown("**Good wrecker-price candidates**")
    st.write(
        "- bumper covers, headlights, tail lights, mirrors, door handles, fuel flaps, simple trim pieces, batteries, wheels/tyres, keys where applicable"
    )
    st.markdown("**Needs specialist quote evidence**")
    st.write(
        "- windscreen/glass fitting, paint/panel repair, hail, upholstery/roof lining, diagnostics, engine/transmission/driveline/brake/suspension faults"
    )
    st.markdown("**Melbourne wrecker research fields to capture**")
    st.write(
        "- supplier name, suburb, part description, vehicle compatibility, used/new/reconditioned, quoted part price, freight/pickup, warranty, evidence URL/date"
    )
    if quotes_df.empty:
        st.info("Create quote requests first, then use Gmail/browser to gather evidence against each request.")
    else:
        evidence_cols = [
            "request_id",
            "canonical_defect",
            "supplier_type",
            "supplier",
            "contact_method",
            "status",
            "evidence_url",
            "notes",
        ]
        st.dataframe(quotes_df[evidence_cols], use_container_width=True, hide_index=True)
