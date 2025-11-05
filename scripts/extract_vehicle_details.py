import asyncio
import os
import re
import shutil
import tempfile

import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from shared.data_loader import DATA_DIR

# ─── File Paths ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
INPUT_FILE = str(DATA_DIR / "all_vehicle_links.csv")
OUTPUT_FILE = str(DATA_DIR / "vehicle_static_details.csv")
SKIPPED_LOG = os.path.join(ROOT_DIR, "logs", "skipped_links.txt")

# ─── Schema Field Order ───────────────────────────────────
SCHEMA_FIELDS = [
    "year", "make", "model", "variant", "body_type", "no_of_seats", "build_date", "compliance_date",
    "vin", "rego_no", "rego_state", "rego_expiry", "no_of_plates", "no_of_cylinders", "engine_capacity",
    "fuel_type", "transmission", "odometer_reading", "odometer_unit", "exterior_colour", "interior_colour",
    "key", "spare_key", "owners_manual", "service_history", "engine_turns_over", "location",
    "url", "general_condition", "features_list", "bids", "price", "time_remaining_or_date_sold", "status"
]

# ─── Field Label Mapping ───────────────────────────────
FIELD_MAP = {
    "body_type": "Body Type",
    "no_of_seats": "No. of Seats",
    "build_date": "Build Date",
    "compliance_date": "Compliance Date",
    "vin": "VIN",
    "rego_no": "Registration No",
    "rego_state": "Registration State",
    "rego_expiry": "Registration Expiry Date",
    "no_of_plates": "No. of Plates",
    "no_of_cylinders": "No. of Cylinders",
    "engine_capacity": "Engine Capacity",
    "fuel_type": "Fuel Type",
    "transmission": "Transmission",
    "odometer_reading": "Indicated Odometer Reading",
    "exterior_colour": "Exterior Colour",
    "interior_colour": "Interior Colour",
    "key": "Key",
    "spare_key": "Spare Key",
    "owners_manual": "Owners Manual",
    "service_history": "Service History",
    "engine_turns_over": "Engine Turns Over",
    "location": "Location",
    "general_condition": "General Condition Notes",
    "features_list": "Features List",
    "bids": "N/A",
    "price": "N/A",
    "time_remaining_or_date_sold": "N/A"
}

# ─── Helpers ────────────────────────────────────────────
def clean_joined_fields(text):
    return re.sub(r'([a-z])([A-Z])', r'\1, \2', text)

def extract_field(soup, label):
    li_tags = soup.find_all("li")
    for li in li_tags:
        text = li.get_text(strip=True)
        if re.match(rf"^{re.escape(label)}\s*:", text, re.IGNORECASE):
            parts = text.split(":", 1)
            if len(parts) == 2:
                return clean_joined_fields(parts[1].strip())
    return "N/A"

def extract_general_condition(soup):
    try:
        condition_header = soup.find('strong', string=re.compile("condition assessment", re.IGNORECASE))
        if condition_header:
            ul = condition_header.find_parent('p').find_next_sibling('ul')
            items = [li.get_text(strip=True) for li in ul.find_all('li')] if ul else []
            return '\n'.join(items) if items else 'N/A'
    except:
        pass
    return 'N/A'

def extract_features_list(soup):
    try:
        features_header = soup.find('strong', string=re.compile("^features", re.IGNORECASE))
        if features_header:
            ul = features_header.find_parent('p').find_next_sibling('ul')
            items = [li.get_text(strip=True) for li in ul.find_all('li')] if ul else []
            return ', '.join(items) if items else 'N/A'
    except:
        pass
    return 'N/A'

def extract_location(soup):
    try:
        location_cell = soup.find('td', string=re.compile('Location', re.IGNORECASE))
        if location_cell:
            location_text = location_cell.find_next_sibling('td').get_text(strip=True)
            region = location_text.split(',')[-2].strip().upper()
            if region in ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT']:
                return region
    except:
        pass
    return 'N/A'

# ─── Main Vehicle Extractor ───────────────────────────────
def extract_vehicle_details(soup, url):
    title_elem = soup.find("h1", class_="dls-heading-3 lotPageTitle")
    title = title_elem.get_text(strip=True) if title_elem else "N/A"
    title_parts = title.split()
    year = title_parts[0] if title_parts and re.match(r"^\d{4}$", title_parts[0]) else "N/A"
    make = title_parts[1] if len(title_parts) > 1 else "N/A"
    model = title_parts[2] if len(title_parts) > 2 else "N/A"
    variant = " ".join(title_parts[3:]) if len(title_parts) > 3 else "N/A"

    details = {
        "year": year,
        "make": make,
        "model": model,
        "variant": variant,
        "odometer_unit": "km",
        "url": url,
        "status": "Active"
    }

    for field_key, label in FIELD_MAP.items():
        details[field_key] = extract_field(soup, label)

    details["general_condition"] = extract_general_condition(soup)
    details["features_list"] = extract_features_list(soup)
    details["location"] = extract_location(soup)

    return details

# ─── Scrape Logic ─────────────────────────────────
async def safe_goto(page, url, timeout=60000, retries=2):
    for attempt in range(retries):
        try:
            await page.goto(url, timeout=timeout)
            return True
        except Exception as e:
            print(f"⚠️ Attempt {attempt+1} failed for {url}: {e}")
            await page.wait_for_timeout(2000)
    return False

async def process_links(links):
    results = []
    skipped = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for url in links:
            print(f"\n▶ Scraping: {url}")
            if await safe_goto(page, url):
                content = await page.content()
                soup = BeautifulSoup(content, "html.parser")
                row = extract_vehicle_details(soup, url)
                results.append(row)
            else:
                print(f"❌ Skipping {url} after retries.")
                skipped.append(url)
        await browser.close()

    if skipped:
        os.makedirs(os.path.dirname(SKIPPED_LOG), exist_ok=True)
        with open(SKIPPED_LOG, "a") as f:
            for url in skipped:
                f.write(url + "\n")

    return results

# ─── Entry Point ──────────────────────────────────
async def main():
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file not found at: {INPUT_FILE}")
        return

    links_df = pd.read_csv(INPUT_FILE)
    all_links = links_df["url"].dropna().drop_duplicates().tolist()

    if os.path.exists(OUTPUT_FILE):
        existing_df = pd.read_csv(OUTPUT_FILE)
        processed_urls = set(existing_df["url"].dropna().unique())
    else:
        processed_urls = set()

    new_links = [url for url in all_links if url not in processed_urls]

    if not new_links:
        print("✅ No new vehicle links to process.")
        return

    print(f"🔍 {len(new_links)} new vehicle links to process out of {len(all_links)} total.")
    data = await process_links(new_links)
    df = pd.DataFrame(data)

    # Debug: Print DataFrame contents
    print(f"DEBUG: New DataFrame with {len(df)} rows:\n{df[['url', 'year', 'make', 'model', 'status']].to_string()}")

    # Ensure directory exists
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Use temp file for atomic write
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
    if os.path.exists(OUTPUT_FILE):
        combined_df = pd.concat([existing_df, df], ignore_index=True)
        combined_df.drop_duplicates(subset=["url"], inplace=True)
    else:
        combined_df = df

    combined_df = combined_df.reindex(columns=SCHEMA_FIELDS)
    print(f"DEBUG: Saving combined DataFrame with {len(combined_df)} rows to {temp_file}")
    combined_df.to_csv(temp_file, index=False)
    shutil.move(temp_file, OUTPUT_FILE)

    print(f"\n✅ Saved {len(df)} new vehicles. Total now: {len(combined_df)} in {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
