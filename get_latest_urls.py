import requests
import re
from datetime import datetime

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
MANIFEST_URL = BASE_URL + "manifest.xml"

def extract_datetime_from_filename(filename):
    # Example: PUBLIC_MTPASADUIDAVAILABILITY_202506241800_0000000469093579.zip
    match = re.search(r"_(\d{12})_", filename)
    if match:
        return datetime.strptime(match.group(1), "%Y%m%d%H%M")
    return None

def fetch_latest_two():
    r = requests.get(MANIFEST_URL)
    r.raise_for_status()
    zip_files = re.findall(r"PUBLIC_MTPASADUIDAVAILABILITY_\d{12}_[^<]+?\.zip", r.text)

    # Map to tuples of (datetime, filename), and sort by datetime
    dated_files = [(extract_datetime_from_filename(f), f) for f in zip_files]
    dated_files = sorted([pair for pair in dated_files if pair[0] is not None])

    latest_two = [BASE_URL + f for (_, f) in dated_files[-2:]]
    return latest_two

if __name__ == "__main__":
    print("🆕 Latest two MTPASA ZIP URLs by datetime:")
    for url in fetch_latest_two():
        print(url)
