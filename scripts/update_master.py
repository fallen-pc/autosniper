import os
import shutil
import tempfile

import pandas as pd

from shared.data_loader import DATA_DIR

# File paths
DETAILS_FILE = str(DATA_DIR / "vehicle_static_details.csv")
SOLD_FILE = str(DATA_DIR / "sold_cars.csv")
REFERRED_FILE = str(DATA_DIR / "referred_cars.csv")
ACTIVE_FILE = str(DATA_DIR / "active_vehicle_details.csv")

def update_master_database():
    if not os.path.exists(DETAILS_FILE):
        print(f"❌ {DETAILS_FILE} not found.")
        return

    df = pd.read_csv(DETAILS_FILE)
    if df.empty:
        print(f"⚠️ {DETAILS_FILE} is empty.")
        return

    # Normalize status column
    df["status"] = df["status"].astype(str).str.strip().str.lower()

    # Split data
    sold_df = df[df["status"] == "sold"]
    referred_df = df[df["status"].isin(["referred", "canceled", "closed"])]
    active_df = df[df["status"] == "active"]

    # Ensure directory exists
    os.makedirs(os.path.dirname(DETAILS_FILE), exist_ok=True)

    # Save sold listings
    if not sold_df.empty:
        temp_sold = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
        if os.path.exists(SOLD_FILE):
            existing_sold = pd.read_csv(SOLD_FILE)
            sold_df = pd.concat([existing_sold, sold_df]).drop_duplicates(subset=["url"])
        sold_df.to_csv(temp_sold, index=False)
        shutil.move(temp_sold, SOLD_FILE)
        print(f"✅ Saved {len(sold_df)} sold listings to {SOLD_FILE}")
    else:
        print("ℹ️ No sold listings to save.")

    # Save referred/canceled/closed listings
    if not referred_df.empty:
        temp_referred = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
        if os.path.exists(REFERRED_FILE):
            existing_referred = pd.read_csv(REFERRED_FILE)
            referred_df = pd.concat([existing_referred, referred_df]).drop_duplicates(subset=["url"])
        referred_df.to_csv(temp_referred, index=False)
        shutil.move(temp_referred, REFERRED_FILE)
        print(f"✅ Saved {len(referred_df)} referred/canceled/closed listings to {REFERRED_FILE}")
    else:
        print("ℹ️ No referred/canceled/closed listings to save.")

    # Save active listings to active_vehicle_details.csv
    temp_active = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
    if not active_df.empty:
        active_df.to_csv(temp_active, index=False)
        shutil.move(temp_active, ACTIVE_FILE)
        print(f"✅ Saved {len(active_df)} active listings to {ACTIVE_FILE}")
    else:
        pd.DataFrame(columns=df.columns).to_csv(temp_active, index=False)
        shutil.move(temp_active, ACTIVE_FILE)
        print(f"✅ No active listings; saved empty {ACTIVE_FILE} with headers.")

    # Save only active listings to vehicle_static_details.csv
    temp_details = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
    if not active_df.empty:
        active_df.to_csv(temp_details, index=False)
        shutil.move(temp_details, DETAILS_FILE)
        print(f"✅ Saved {len(active_df)} active listings to {DETAILS_FILE}")
    else:
        pd.DataFrame(columns=df.columns).to_csv(temp_details, index=False)
        shutil.move(temp_details, DETAILS_FILE)
        print(f"✅ No active listings; saved empty {DETAILS_FILE} with headers.")

if __name__ == "__main__":
    update_master_database()
