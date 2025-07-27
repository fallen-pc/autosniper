import streamlit as st
import pandas as pd
import os
import re
import json
from openai import OpenAI
from dotenv import load_dotenv

# ─── Setup ─────────────────────────────────────────────────────
st.set_page_config(page_title="Active Listings Dashboard", layout="wide")
st.title("🚗 Active Listings Dashboard")

load_dotenv()
client = OpenAI()

CSV_FILE = "CSV_data/vehicle_static_details.csv"
VERDICT_FILE = "CSV_data/ai_verdicts.csv"

# ─── Refresh Listings ─────────────────────────────────────────
if st.button("🔄 Refresh Active Listings"):
    with st.spinner("Updating bid and time data..."):
        exit_code = os.system("python scripts/update_bids.py")
        if exit_code == 0:
            st.success("✅ Listings updated.")
            st.cache_data.clear()
        else:
            st.error("❌ Update failed. Check logs or terminal output.")

# ─── Load CSV ─────────────────────────────────────────────────
@st.cache_data(ttl=0)
def load_csv():
    return pd.read_csv(CSV_FILE)

if os.path.exists(CSV_FILE):
    df = load_csv()

    # Normalize string columns
    for col in df.select_dtypes(include='object').columns:
        df[col] = df[col].fillna("N/A")

    df["status"] = df["status"].astype(str).str.strip().str.lower()
    df = df[df["status"] == "active"]

    # ─── Filters ───────────────────────────────────────────────
    st.sidebar.markdown("### Filters")
    hide_engine_issues = st.sidebar.checkbox("Hide vehicles with engine defects", value=True)
    hide_unregistered = st.sidebar.checkbox("Hide unregistered vehicles", value=False)
    filter_vic_only = st.sidebar.checkbox("Show only VIC listings", value=False)

    def has_engine_issue(row):
        if pd.isna(row.get("general_condition", "")):
            return False
        text = row["general_condition"].lower()
        keywords = ["engine light", "rough idle", "engine oil leak", "smoke", "seized", "blown", "won't start", "does not start", "engine does not turn", "no compression"]
        return any(kw in text for kw in keywords)

    def is_unregistered(row):
        try:
            return int(row.get("no_of_plates", 0)) == 0
        except:
            return False

    if hide_engine_issues:
        df = df[~df.apply(has_engine_issue, axis=1)]
    if hide_unregistered:
        df = df[~df.apply(is_unregistered, axis=1)]
    if filter_vic_only:
        df = df[df["location"].astype(str).str.upper() == "VIC"]

    # ─── Time Bucketing ────────────────────────────────────────
    def time_bucket(row):
        time_str = str(row.get("time_remaining_or_date_sold", "")).lower()
        h_match = re.search(r'(\d+)\s*h', time_str)
        d_match = re.search(r'(\d+)\s*d', time_str)

        days = int(d_match.group(1)) if d_match else 0
        hours = int(h_match.group(1)) if h_match else 0
        total_hours = days * 24 + hours

        if total_hours < 24:
            return "< 24h"
        elif total_hours < 48:
            return "1–2d"
        elif total_hours < 72:
            return "2–3d"
        else:
            return "3+d"

    df["time_group"] = df.apply(time_bucket, axis=1)
    df["time_group_order"] = df["time_group"].map({"< 24h": 0, "1–2d": 1, "2–3d": 2, "3+d": 3})
    df = df.sort_values(by="time_group_order")

    grouped = df.groupby("time_group", sort=False)

    # ─── AI Analysis Logic ─────────────────────────────────────
    def run_ai_analysis(vehicle_row):
        prompt = f"""
    You are an automotive resale expert. Given the following car details, estimate the resale value in Victoria, calculate the profit margin, and determine the maximum bid to stay profitable.

    Details:
    {vehicle_row.to_dict()}

    Return a JSON like this:
    {{
    "resale_estimate": "$12,000",
    "max_bid": "$9,000",
    "profit_margin_percent": "25%",
    "verdict": "Good"
    }}
        """

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4
        )

        raw = response.choices[0].message.content.strip()

        # Extract JSON block even if text surrounds it
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                return parsed
            except Exception as e:
                return {"error": f"JSON parse failed: {e}", "raw": raw}
        else:
            return {"error": "No JSON found in response", "raw": raw}
    def display_profit_bar(profit_str, verdict):
        try:
            percent = float(profit_str.strip('%'))
            st.markdown(f"**Profit Margin: {profit_str} — Verdict: {verdict}**")
            st.progress(min(percent / 100, 1.0))
        except:
            st.warning("⚠️ Could not parse profit margin.")

    # ─── Display Listings ─────────────────────────────────────
    st.markdown(f"### {len(df)} Active Listings")

    verdicts_df = pd.read_csv(VERDICT_FILE) if os.path.exists(VERDICT_FILE) else pd.DataFrame()

    if df.empty:
        st.info("No active listings match the current filters.")
    else:
        for group, group_df in grouped:
            st.markdown(f"## ⏱️ {group} ({len(group_df)})")
            for _, row in group_df.iterrows():
                vehicle_url = row["url"]
                matching_verdict = verdicts_df[verdicts_df["url"] == vehicle_url]

                with st.container():
                    st.markdown("---")
                    cols = st.columns([3, 2, 2, 2, 2])
                    cols[0].markdown(f"**{row['year']} {row['make']} {row['model']} {row['variant']}**")
                    cols[1].markdown(f"💰 **Price:** {row['price']}")
                    cols[2].markdown(f"🔨 **Bids:** {row['bids']}")
                    cols[3].markdown(f"⏱ **Time Left:** {row['time_remaining_or_date_sold']}")
                    cols[4].markdown(f"📍 **Odometer:** {row.get('odometer_reading', 'N/A')} {row.get('odometer_unit', '')}")
                    if pd.notna(vehicle_url):
                        st.markdown(f'[🔗 View Listing]({vehicle_url})', unsafe_allow_html=True)

                    if not matching_verdict.empty:
                        profit = matching_verdict.iloc[0]["profit_margin_percent"]
                        verdict = matching_verdict.iloc[0]["verdict"]
                        display_profit_bar(profit, verdict)
                    else:
                        if st.button("💡 Run AI Analysis", key=vehicle_url):
                            result = run_ai_analysis(row)
                            if "error" not in result:
                                new_row = row.copy()
                                new_row["resale_estimate"] = result["resale_estimate"]
                                new_row["max_bid"] = result["max_bid"]
                                new_row["profit_margin_percent"] = result["profit_margin_percent"]
                                new_row["verdict"] = result["verdict"]

                                verdicts_df = pd.concat([verdicts_df, pd.DataFrame([new_row])], ignore_index=True)
                                verdicts_df.to_csv(VERDICT_FILE, index=False)

                                st.success("✅ AI analysis saved.")
                                display_profit_bar(result["profit_margin_percent"], result["verdict"])
                            else:
                                st.error("❌ Failed to parse AI response.")
                                st.code(result["raw"])
else:
    st.warning("vehicle_static_details.csv not found.")
