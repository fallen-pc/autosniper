import re

import pandas as pd
import requests
from bs4 import BeautifulSoup

from shared.data_loader import DATA_DIR

BASE_URL = "https://www.grays.com/search/automotive-trucks-and-marine/motor-vehiclesmotor-cycles/motor-vehicles"
OUTPUT_FILE = DATA_DIR / "all_vehicle_links.csv"  # Updated filename

def extract_all_vehicle_links():
    all_links = []
    page = 1

    while True:
        url = f"{BASE_URL}?tab=items&isdesktop=1&page={page}"  # ❌ Removed VIC filter
        print(f"🔄 Fetching: {url}")
        response = requests.get(url)
        if response.status_code != 200:
            print("❌ Failed to load page")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        links = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if re.search(r"/lot/\d+", href) and re.match(r"^\d{4}\b", text):
                if "motorbike" in text.lower() or "motor bike" in text.lower():
                    continue
                full_url = "https://www.grays.com" + href if href.startswith("/") else href
                links.append(full_url)

        unique_links = list(set(links))
        if not unique_links:
            break

        all_links.extend(unique_links)
        page += 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(sorted(set(all_links)), columns=["url"])
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"✅ Saved {len(df)} vehicle links to {OUTPUT_FILE}")

if __name__ == "__main__":
    extract_all_vehicle_links()
