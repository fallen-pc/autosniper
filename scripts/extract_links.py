import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import os

BASE_URL = "https://www.grays.com/search/automotive-trucks-and-marine/motor-vehiclesmotor-cycles/motor-vehicles"
OUTPUT_FILE = "CSV_data/all_vehicle_links.csv"

def extract_all_vehicle_links(return_progress=False):
    progress_data = {
        "pages_processed": 0,
        "total_links": 0,
        "unique_links": 0,
        "links_saved": 0,
        "status": "starting"
    }
    all_links = []
    page = 1
    max_pages = None  # Will be determined after first page

    while True:
        url = f"{BASE_URL}?tab=items&isdesktop=1&page={page}"
        progress_data["status"] = f"fetching page {page}"
        print(f"🔄 Fetching: {url}")
        response = requests.get(url)
        if response.status_code != 200:
            progress_data["status"] = f"failed to load page {page}"
            print("❌ Failed to load page")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        if max_pages is None:
            # Estimate max pages from pagination (if available)
            pagination = soup.find("div", class_="pagination")
            if pagination:
                last_page = pagination.find_all("a", href=True)[-1].get_text(strip=True)
                max_pages = int(last_page) if last_page.isdigit() else 1
            else:
                max_pages = 1

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
        progress_data["total_links"] += len(links)
        all_links.extend(unique_links)
        progress_data["pages_processed"] = page
        progress_data["status"] = f"processed page {page}"

        if not unique_links or (max_pages and page >= max_pages):
            break

        page += 1

    progress_data["unique_links"] = len(set(all_links))
    os.makedirs("CSV_data", exist_ok=True)
    df = pd.DataFrame(sorted(set(all_links)), columns=["url"])
    df.to_csv(OUTPUT_FILE, index=False)
    progress_data["links_saved"] = len(df)
    progress_data["status"] = f"saved {len(df)} links to {OUTPUT_FILE}"
    print(f"✅ Saved {len(df)} vehicle links to {OUTPUT_FILE}")

    if return_progress:
        progress_data["status"] = "completed"
        return progress_data
    return df

if __name__ == "__main__":
    extract_all_vehicle_links()