# 🚗 AutoSniper2 – AI-Driven Car Auction Profit Tool

AutoSniper2 is a Streamlit-based web application that helps users analyze and track used car auctions (primarily from Grays.com.au) to identify vehicles that can be purchased at a profit and resold. It uses AI to predict profitable purchase prices and visually presents each listing with real-time bid and time data.

---

## 🧠 What It Does

- Scrapes and displays current **active vehicle auctions**
- Lets users **trigger AI analysis per vehicle** to estimate:
  - Resale value
  - Maximum profitable bid
  - Estimated profit margin
- Tracks and displays these results visually in the dashboard
- Groups listings into auction time buckets (`<24h`, `1–2d`, `2–3d`, `3+d`)
- Lets users filter vehicles (e.g., hide engine defects, unregistered, non-VIC)
- Maintains data between sessions via `.csv` files

---

## 🚀 Setup Instructions

1. **Install Python (3.10–3.12 recommended)**  
   Download from https://www.python.org/downloads/

2. **Download this project** (ZIP or Git)

3. **Open a terminal** in the root folder

4. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate

pip install -r requirements.txt

OPENAI_API_KEY=sk-xxxxxxx...

streamlit run app.py

autosniper2/
│
├── app.py                        ← Main Streamlit entrypoint
├── pages/
│   ├── ACTIVE LISTINGS.py        ← Displays live auction data + AI buttons
│   └── ai_analysis_page.py       ← Tabs of completed AI analysis results
│
├── scripts/
│   └── update_bids.py            ← Script to update time and bid info (called from UI)
│
├── CSV_data/
│   ├── vehicle_static_details.csv ← Base data of all listings
│   ├── ai_verdicts.csv           ← AI output results (generated dynamically)
│   └── ...                       ← Other saved datasets
│
├── .env                          ← OpenAI key and other secrets
├── requirements.txt              ← Python dependencies
└── README.md                     ← This file

📄 Page & Feature Breakdown
🔹 ACTIVE LISTINGS Page
This is the main dashboard where all active auction listings are shown.

Displays vehicles in rows grouped by auction time remaining.

Each vehicle tile shows:

Year, make, model, variant

Price, number of bids

Time left

Odometer

Includes a "💡 Run AI Analysis" button for each listing:

Sends the vehicle’s info to OpenAI

Receives: resale estimate, max bid, profit margin, verdict

Saves result to ai_verdicts.csv

Displays a color-coded profit margin bar after completion

You can also:

Filter to show only VIC cars

Hide vehicles with engine issues

Hide unregistered cars

Refresh live bid/time data (calls scripts/update_bids.py)

🧠 AI Analysis Page
Displays a tab for every vehicle that has completed AI analysis.

Each tab includes:

Vehicle summary + external link

Auction status (location, time remaining, price)

AI result block:

Estimated resale value

Max bid to stay profitable

Profit margin bar with color

Verdict label (e.g., Good, Marginal)

This page updates automatically as more vehicles are analyzed.

🤖 AI Prompt Logic
When a user clicks "Run AI Analysis", the app sends the following prompt to OpenAI:

You are an automotive resale expert. Given the following car details, estimate the resale value in Victoria, calculate the profit margin, and determine the maximum bid to stay profitable...

It then parses the JSON response with fields:

resale_estimate

max_bid

profit_margin_percent

verdict

🔮 Next Steps & Improvements
🧠 AI Improvements
Fine-tune the prompt:

Make it more structured to always return JSON without fluff

Add clearer resale assumptions (e.g., assuming no repairs unless noted)

AI Model Training (Future):

Export hundreds of past sale examples to fine-tune a custom GPT model

Train it using real resale data from sold_cars.csv and Autotrader

Add confidence level or risk flag to help assess listings with vague data

📊 Data Handling
Add more status flags: Withdrawn, Referred, No Sale

Detect and remove stale or expired listings automatically

Track vehicles over time as they move from Active → Sold

📈 UI Enhancements
Color-coded verdict badges (e.g., 🟢 Good, 🟡 Marginal, 🔴 Avoid)

Sorting by profit %, resale estimate, or AI confidence

Export analyzed vehicles to Excel/PDF reports

Add icons for missing documents, keys, or engine faults

⚙️ Dev Improvements
Use pydantic or dataclass for strict schema enforcement

Replace CSVs with SQLite or Supabase backend (scalable)

Add unit tests for prompt parsing & CSV updates

🧑‍💻 Contributors
Original Author: Ewan Ferrie

Special thanks to OpenAI, Grays, and the auto reselling community.

📬 Need Help?
Feel free to open an issue or contact the author directly for support setting up or extending AutoSniper2.