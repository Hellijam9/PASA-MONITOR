#!/usr/bin/env python3
"""
Compares the two most recent MTPASA DUID Availability files
and pushes availability changes by DUID to ntfy.sh/pasa-alerts

Runs at 09:20, 12:20, 15:20, 18:20 AEST Mon–Sat
Plus 07:00 AEST Monday for weekend changes
"""
import os
import zipfile
import requests
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO
from bs4 import BeautifulSoup
import pytz

NTFY_TOPIC = "pasa-alerts"
MTPASA_URL = "https://nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
TIMEZONE = pytz.timezone("Australia/Sydney")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def list_files():
    r = requests.get(MTPASA_URL)
    soup = BeautifulSoup(r.text, "lxml")
    files = [
        (a.text, MTPASA_URL + a['href'])
        for a in soup.find_all('a')
        if a.text.endswith(".zip") and "PUBLIC" in a.text
    ]
    return sorted(files)

def is_valid_zip(url):
    try:
        head = requests.head(url, timeout=10)
        return 'zip' in head.headers.get('Content-Type', '')
    except Exception:
        return False

def extract_csv_from_zip(url):
    r = requests.get(url)
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]  # Always extract first file
        with z.open(file_name) as f:
            return pd.read_csv(f, skiprows=1, low_memory=False)

def compare_availability(df1, df2):
    cols = ["DUID", "Date", "Availability"]
    df1 = df1[cols].copy()
    df2 = df2[cols].copy()
    df1.rename(columns={"Availability": "Avail_1"}, inplace=True)
    df2.rename(columns={"Availability": "Avail_2"}, inplace=True)

    merged = pd.merge(df1, df2, on=["DUID", "Date"])
    merged["Change"] = merged["Avail_2"] - merged["Avail_1"]
    changed = merged[merged["Change"] != 0]
    return changed.sort_values(["DUID", "Date"])

def format_summary(changes):
    lines = ["MTPASA DUID Availability Changes:\n"]
    grouped = changes.groupby("DUID")
    for duid, group in grouped:
        lines.append(f"\n{duid}:")
        for _, row in group.iterrows():
            date = row['Date']
            c = int(row['Change'])
            lines.append(f"  {date}: {c:+} MW")
    return "\n".join(lines)

def send_ntfy(summary):
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=summary.encode("utf-8"))

if __name__ == "__main__":
    log("Fetching file list...")
    all_files = list_files()

    valid_files = [(name, url) for name, url in reversed(all_files) if is_valid_zip(url)]
    if len(valid_files) < 2:
        log("Not enough valid files to compare.")
        exit(1)

    (name1, url1), (name2, url2) = valid_files[-2:]  # older → newer
    log(f"Comparing {name1} to {name2}")

    df1 = extract_csv_from_zip(url1)
    df2 = extract_csv_from_zip(url2)
    changes = compare_availability(df1, df2)

    if changes.empty:
        log("No changes detected.")
    else:
        summary = format_summary(changes)
        send_ntfy(summary)
        log("Alert sent.")
