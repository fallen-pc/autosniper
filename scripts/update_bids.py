import pandas as pd
import os
import asyncio
import re
import tempfile
import shutil
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from datetime import datetime
import random
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CSV_FILE = "CSV_data/vehicle_static_details.csv"
SKIPPED_LOG = "logs/skipped_links.txt"
PROGRESS_FILE = "logs/update_progress.txt"

# ─── Clean URL from HTML anchor tag ─────────────────────────────
def clean_url(url):
    if not isinstance(url, str):
        return ""
    match = re.search(r'href="([^"]+)"', url)
    return match.group(1) if match else url

# ─── Extract auction info ──────────────────────────────────────
def extract_bid_info(soup):
    try:
        # Price extraction using itemprop="price"
        price_elem = soup.find("span", attrs={"itemprop": "price"})
        price = price_elem.get_text(strip=True).replace('$', '').replace(',', '') if price_elem else "N/A"
        price = price if price and re.match(r'^\d+(\.\d+)?$', price) else "N/A"
        print(f"  Price element: {price_elem}")
        print(f"  Extracted price: {price}")

        # Time remaining for active listings
        time_elem = soup.find("span", id="lot-closing-countdown")
        time_remaining = time_elem.get_text(strip=True) if time_elem and re.search(r"\d+\s*(d|day|days|h|hour|hours|m|min|minutes|s|sec|seconds)", time_elem.get_text(strip=True).lower(), re.IGNORECASE) else None
        print(f"  Time element: {time_elem}")
        print(f"  Extracted time remaining: {time_remaining if time_remaining else 'None'}")

        # Date sold for sold listings
        date_sold_elem = soup.find("abbr", class_="endtime")
        date_sold = date_sold_elem.get_text(strip=True) if date_sold_elem else None
        print(f"  Date sold element: {date_sold_elem}")
        print(f"  Extracted date sold: {date_sold if date_sold else 'None'}")

        # Bid extraction using regex for number of bids
        bid_elem = soup.find("a", string=re.compile(r"\d+\s+bids", re.IGNORECASE))
        bids_text = bid_elem.get_text(strip=True) if bid_elem else "0 bids"
        bids_match = re.search(r'\d+', bids_text)
        bids = bids_match.group() if bids_match else "0"
        print(f"  Bid element: {bid_elem}")
        print(f"  Extracted bids: {bids}")

        # Check for Referred or Canceled status
        referred_elem = soup.find("div", class_="dls-heading-3")
        is_referred = referred_elem and "Referred" in referred_elem.get_text(strip=True) if referred_elem else False
        canceled_elem = soup.find("p", class_="large-stamp large-stamp-sale-closed")
        is_canceled = canceled_elem and "Sale closed" in canceled_elem.get_text(strip=True) if canceled_elem else False
        is_referred = is_referred or is_canceled  # Treat canceled as Referred
        print(f"  Referred/Canceled element: {referred_elem or canceled_elem}")
        print(f"  Is Referred or Canceled: {is_referred}")

        # Check for Active status based on time remaining
        is_active = bool(time_remaining and re.search(r"\d+\s*(d|day|days|h|hour|hours|m|min|minutes|s|sec|seconds)", time_remaining.lower(), re.IGNORECASE))
        print(f"  Is Active: {is_active}")

        return price, bids, time_remaining, date_sold, is_referred, is_active
    except Exception as e:
        print(f"⚠️ Error extracting auction info: {e}")
        return "N/A", "0", None, None, False, False

# ─── Fetch one listing ─────────────────────────────────────────
async def safe_goto(page, url, timeout=60000, retries=2):
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    ]
    for attempt in range(retries + 1):
        try:
            await page.set_extra_http_headers({"User-Agent": random.choice(user_agents)})
            await page.goto(url, wait_until="load", timeout=timeout)
            await page.wait_for_timeout(5000)
            return True
        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed for {url}: {e}")
            if attempt == retries:
                print(f"⚠️ All retries failed for {url}")
                return False
            await page.wait_for_timeout(3000)

# ─── Process one listing ───────────────────────────────────────
async def fetch_listing_data(url, page, browser):
    try:
        if await safe_goto(page, url):
            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            return extract_bid_info(soup)
        else:
            try:
                content = await page.content()
                with open(f"error_{url.split('/')[-1]}.html", "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"  Saved HTML to error_{url.split('/')[-1]}.html")
            except:
                print(f"  No content available to save for {url}")
            return "N/A", "0", None, None, False, False
    except Exception as e:
        print(f"⚠️ Critical fetch error for {url}: {e}. Restarting browser.")
        await page.close()
        await browser.close()
        browser = await async_playwright().chromium.launch(headless=True)
        page = await browser.new_page()
        return "N/A", "0", None, None, False, False, browser, page

# ─── Main update loop ──────────────────────────────────────────
async def update_bids(input_links=None):
    skipped_urls = []
    try:
        if not os.path.exists(CSV_FILE):
            print("❌ File not found:", CSV_FILE)
            return [], skipped_urls

        df = pd.read_csv(CSV_FILE)
        if df.empty:
            print("⚠️ vehicle_static_details.csv is empty.")
            return df, skipped_urls

        # Use input_links if provided, else use URLs from CSV
        if input_links:
            urls = [clean_url(url) for url in input_links if url and url.startswith("http")]
        else:
            urls = df["url"].apply(clean_url).dropna().drop_duplicates().tolist()

        # Ensure columns have correct dtypes
        if "price" in df.columns:
            df["price"] = df["price"].astype(str)
        if "time_remaining_or_date_sold" in df.columns:
            df["time_remaining_or_date_sold"] = df["time_remaining_or_date_sold"].astype(str)
        if "status" not in df.columns:
            df["status"] = "Unknown"
        if "bids" not in df.columns:
            df["bids"] = 0

        # Load progress if exists
        os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
        processed = set()
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, 'r') as f:
                processed = set(line.strip() for line in f if line.strip())
            print(f"Resuming: Skipping {len(processed)} processed URLs.")
            urls = [u for u in urls if u not in processed]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            for idx, url in enumerate(urls):
                if not url or not url.startswith("http"):
                    print(f"  Skipped: Invalid URL {url}")
                    skipped_urls.append(url)
                    continue

                print(f"🔄 Updating [{idx+1}/{len(urls)}]: {url}")
                result = await fetch_listing_data(url, page, browser)
                if len(result) == 8:  # Browser restart case
                    price, bids, time_remaining, date_sold, is_referred, is_active, browser, page = result
                else:
                    price, bids, time_remaining, date_sold, is_referred, is_active = result

                # Skip updates only if all fields are default and no status indicators
                if price == "N/A" and bids == "0" and time_remaining is None and date_sold is None and not is_active and not is_referred:
                    print(f"  Skipped: Fetch failed, retaining status {df.loc[df['url'] == url, 'status'].iloc[0] if not df.loc[df['url'] == url].empty else 'N/A'}")
                    skipped_urls.append(url)
                    continue

                # Update fields
                df.loc[df["url"] == url, "price"] = price
                try:
                    df.loc[df["url"] == url, "bids"] = int(bids)
                except:
                    df.loc[df["url"] == url, "bids"] = 0

                print(f"  Time remaining: {time_remaining if time_remaining else 'None'}")
                print(f"  Date sold: {date_sold if date_sold else 'None'}")
                print(f"  Price: {price}")
                print(f"  Bids: {bids}")
                print(f"  Is Referred: {is_referred}")
                print(f"  Is Active: {is_active}")

                # Improved status logic based on new selectors
                if is_active:
                    print("  Condition: Active countdown found - Set to Active")
                    df.loc[df["url"] == url, "time_remaining_or_date_sold"] = time_remaining if time_remaining else "N/A"
                    df.loc[df["url"] == url, "status"] = "Active"
                elif is_referred:
                    print("  Condition: Referred or Canceled indicator found - Set to Referred")
                    df.loc[df["url"] == url, "time_remaining_or_date_sold"] = "N/A"
                    df.loc[df["url"] == url, "status"] = "Referred"
                elif date_sold and int(bids) > 0:  # Prioritize date_sold and bids for Sold
                    print("  Condition: Date sold and bids found - Set to Sold")
                    df.loc[df["url"] == url, "time_remaining_or_date_sold"] = date_sold
                    df.loc[df["url"] == url, "status"] = "Sold"
                elif price != "N/A" and int(bids) > 0:
                    print("  Condition: Price and bids present, no date sold - Set to Sold with current date")
                    df.loc[df["url"] == url, "time_remaining_or_date_sold"] = datetime.now().strftime("%Y-%m-%d")
                    df.loc[df["url"] == url, "status"] = "Sold"
                else:
                    print("  Condition: No active, referred, or valid sold criteria - Set to Referred")
                    df.loc[df["url"] == url, "time_remaining_or_date_sold"] = "N/A"
                    df.loc[df["url"] == url, "status"] = "Referred"

                # Mark as processed
                with open(PROGRESS_FILE, 'a') as f:
                    f.write(url + '\n')

            await browser.close()

        # Save updated DataFrame
        os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
        df["url"] = df["url"].apply(clean_url)
        df.to_csv(temp_file, index=False)
        shutil.move(temp_file, CSV_FILE)
        touched_count = len(urls) if input_links else len(df)
        print(f"✅ vehicle_static_details.csv refreshed ({touched_count} listings touched, {len(df)} total records).")

        # Save skipped URLs to file
        if skipped_urls:
            os.makedirs(os.path.dirname(SKIPPED_LOG), exist_ok=True)
            with open(SKIPPED_LOG, 'a') as f:
                for url in skipped_urls:
                    f.write(url + "\n")
            print(f"📝 Saved {len(skipped_urls)} skipped URLs to {SKIPPED_LOG}")

        # Clear progress file on successful completion
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print(f"🗑️ Cleared progress file {PROGRESS_FILE}")

        return df, skipped_urls
    except Exception as e:
        logger.error(f"Unexpected error in update_bids: {e}")
        return df, skipped_urls

# ─── Entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(update_bids())
