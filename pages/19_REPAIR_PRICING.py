from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from shared.repair_pricing_schedule import (
    PRICING_COLUMNS,
    PRICING_METHODS,
    QUOTE_COLUMNS,
    SUPPLIER_TYPES,
    VEHICLE_CLASSES,
    apply_quote_response,
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
from shared.styling import clean_html, display_banner, escape_html, inject_global_styles, page_intro


st.set_page_config(page_title="Repair Pricing", layout="wide")
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


st.markdown(
    """
    <style>
    .repair-pricing-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.65rem;
        margin: 0.75rem 0 1rem;
    }
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
        color: rgba(255,255,255,0.58);
    }
    .repair-pricing-value {
        margin-top: 0.3rem;
        font-size: 1.35rem;
        font-weight: 820;
        color: rgba(255,255,255,0.94);
    }
    .repair-pricing-sub {
        margin-top: 0.25rem;
        font-size: 0.72rem;
        color: rgba(255,255,255,0.58);
    }
    .repair-pricing-note {
        border-left: 3px solid rgba(39, 182, 255, 0.55);
        background: rgba(39, 182, 255, 0.06);
        padding: 0.7rem 0.85rem;
        margin: 0.5rem 0 1rem;
        border-radius: 0 8px 8px 0;
    }
    @media (max-width: 900px) {
        .repair-pricing-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


candidates_df = canonical_pricing_candidates()
pricing_df = load_pricing_schedule()
quotes_df = load_quote_requests()
needs_df = needs_pricing(candidates_df, pricing_df)

priced_count = non_empty_count(pricing_df, "canonical_defect")
quote_open_count = 0
if not quotes_df.empty and "status" in quotes_df.columns:
    quote_open_count = int(quotes_df["status"].map(safe_text).isin({"draft", "ready", "sent", "waiting"}).sum())

st.markdown(
    clean_html(
        f"""
        <div class="repair-pricing-grid">
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

needs_tab, schedule_tab, quotes_tab, responses_tab, evidence_tab = st.tabs(
    ["Needs Pricing", "Pricing Schedule", "Quote Requests", "Quote Responses", "Supplier Evidence"]
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
            updated = pricing_df[pricing_df["canonical_defect"] != selected_item].copy()
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
            q_vehicle_class = st.selectbox("Vehicle class", VEHICLE_CLASSES, key="quote_vehicle_class")
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
            placeholder="What to ask for, vehicle details, part condition, VIN requirement, labour assumption.",
        )
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
                "draft_subject": "",
                "draft_body": "",
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
                    updated_pricing = pricing_df[pricing_df["canonical_defect"] != canonical].copy()
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
