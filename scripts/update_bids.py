import pandas as pd
import os
import asyncio
import re
import tempfile
import shutil
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from datetime import datetime

CSV_FILE = "CSV_data/vehicle_static_details.csv"

# ─── Clean URL from HTML anchor tag ─────────────────────────────
def clean_url(url):
    if not isinstance(url, str):
        return ""
    match = re.search(r'href="([^"]+)"', url)
    return match.group(1) if match else url

# ─── Extract auction info ───────────────────────────────────────
def extract_bid_info(soup):
    try:
        price_elem = soup.find("span", attrs={"itemprop": "price"})
        price = price_elem.get_text(strip=True) if price_elem else "N/A"

        time_elem = soup.find("span", id="lot-closing-countdown")
        time_remaining = time_elem.get_text(strip=True) if time_elem else "Auction Ended"

        bid_elem = soup.find("a", string=re.compile(r"\d+\s+bids", re.IGNORECASE))
        bids = bid_elem.get_text(strip=True).split()[0] if bid_elem else "0"

        return price, bids, time_remaining
    except Exception as e:
        print(f"⚠️ Error extracting auction info: {e}")
        return "N/A", "0", "Auction Ended"

# ─── Fetch one listing ──────────────────────────────────────────
async def fetch_listing_data(url, page):
    try:
        await page.goto(url, timeout=15000)
        await page.wait_for_timeout(3000)
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        return extract_bid_info(soup)
    except Exception as e:
        print(f"⚠️ Failed to update {url}: {e}")
        return "N/A", "0", "Auction Ended"

# ─── Main update loop ───────────────────────────────────────────
async def update_all_bids():
    if not os.path.exists(CSV_FILE):
        print("❌ File not found:", CSV_FILE)
        return

    df = pd.read_csv(CSV_FILE)
    if df.empty:
        print("⚠️ vehicle_static_details.csv is empty.")
        return

    # Ensure columns have correct dtypes
    if "price" in df.columns:
        df["price"] = df["price"].astype(str)
    if "time_remaining_or_date_sold" in df.columns:
        df["time_remaining_or_date_sold"] = df["time_remaining_or_date_sold"].astype(str)
    if "status" not in df.columns:
        df["status"] = "Unknown"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for idx, row in df.iterrows():
            url = clean_url(row.get("url", ""))
            if not url or not url.startswith("http"):
                continue

            print(f"🔄 Updating: {url}")
            price, bids, time_or_expired = await fetch_listing_data(url, page)

            # Update fields
            df.at[idx, "price"] = price
            try:
                df.at[idx, "bids"] = int(bids)
            except:
                df.at[idx, "bids"] = 0

            if re.search(r"\d+[dhm]", time_or_expired.lower()):
                df.at[idx, "time_remaining_or_date_sold"] = time_or_expired
                df.at[idx, "status"] = "Active"
            elif price != "N/A" and bids != "0":
                df.at[idx, "time_remaining_or_date_sold"] = datetime.now().strftime("%Y-%m-%d")
                df.at[idx, "status"] = "Sold"
            else:
                df.at[idx, "time_remaining_or_date_sold"] = "N/A"
                df.at[idx, "status"] = "Referred"

        await browser.close()

    # Save updated DataFrame using temp file to avoid conflicts
    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
    df["url"] = df["url"].apply(clean_url)  # Ensure URLs are clean
    df.to_csv(temp_file, index=False)
    shutil.move(temp_file, CSV_FILE)
    print("✅ vehicle_static_details.csv updated with status, price, bids, and auction outcome.")

# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(update_all_bids())
