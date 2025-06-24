#!/usr/bin/env python3
"""
Downloads the latest MTPASA DUIDAvailability ZIP,
extracts the CSV, and prints the first few rows.
"""
import requests
from bs4 import BeautifulSoup
import zipfile
from io import BytesIO
import pandas as pd

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"

def get_latest_zip_url():
    r = requests.get(BASE_URL)
    soup = BeautifulSoup(r.text, "html.parser")
    zips = [a["href"] for a in soup.find_all("a") if a["href"].endswith(".zip")]
    latest_zip = sorted(zips)[-1]
    return BASE_URL + latest_zip

def download_and_extract_csv(zip_url):
    print(f"Downloading: {zip_url}")
    r = requests.get(zip_url)
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        for filename in z.namelist():
            if filename.endswith(".csv"):
                print(f"Extracting: {filename}")
                df = pd.read_csv(z.open(filename))
                print(df.head())
                return
    print("❌ No CSV found in ZIP.")

if __name__ == "__main__":
    zip_url = get_latest_zip_url()
    download_and_extract_csv(zip_url)