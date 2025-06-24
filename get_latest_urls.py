import requests
import re
from datetime import datetime

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"

def fetch_latest_two():
    print("🔍 Scraping AEMO directory listing...")
    r = requests.get(BASE_URL)
    r.raise_for_status()
    
    # Find all ZIP files
    zip_files = re.findall(r'PUBLIC_MTPASADUIDAVAILABILITY_\d{12}_\d+\.zip', r.text)
    
    # Parse datetimes from filenames
    def extract_dt(filename):
        match = re.search(r'_(\d{12})_', filename)
        return datetime.strptime(match.group(1), "%Y%m%d%H%M") if match else datetime.min

    zip_files.sort(key=extract_dt, reverse=True)
    latest_two = zip_files[:2]

    print("🆕 Latest two MTPASA ZIP URLs by datetime:")
    for f in latest_two:
        print(BASE_URL + f)

if __name__ == "__main__":
    fetch_latest_two()
