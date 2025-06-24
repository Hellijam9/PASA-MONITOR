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
import signal
import sys

NTFY_TOPIC = "pasa-alerts"
MTPASA_URL = "https://nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
TIMEZONE = pytz.timezone("Australia/Sydney")
MAX_RUNTIME_SECONDS = 180  # kill script if it runs longer than 3 minutes
MIN_ZIP_SIZE_BYTES = 100_000  # skip ZIPs smaller than 100 KB (likely incomplete)


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def timeout_handler(signum, frame):
    log("⏱️ Timeout exceeded. Aborting.")
    send_ntfy("⚠️ PASA Monitor timed out after 3 minutes.")
    sys.exit(1)

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(MAX_RUNTIME_SECONDS)


def list_files():
    log("Fetching file list from NEMWeb...")
    r = requests.get(MTPASA_URL, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    files = [
        (a.text, MTPASA_URL + a['href'])
        for a in soup.find_all('a')
        if a.text.endswith(".zip") and "PUBLIC" in a.text
    ]
    return sorted(files)


def is_valid_zip(url):
    try:
        head = requests.head(url, timeout=10)
        content_type = head.headers.get('Content-Type', '')
        content_length = int(head.headers.get('Content-Length', '0'))
        return 'zip' in content_type and content_length >= MIN_ZIP_SIZE_BYTES
    except Exception:
        return False


def extract_csv_from_zip(url):
    log(f"Downloading ZIP: {url}")
    r = requests.get(url, timeout=60)
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        for filename in z.namelist():
            if filename.endswith(".csv"):
                log(f"Extracting CSV: {filename}")
                return pd.read_csv(z.open(filename))
    return pd.DataFrame()


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
    log("Sending alert via ntfy...")
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=summary.encode("utf-8"), timeout=10)
    except Exception as e:
        log(f"Failed to send ntfy alert: {e}")


if __name__ == "__main__":
    log("Fetching file list...")
    all_files = list_files()

    valid_files = [(name, url) for name, url in reversed(all_files) if is_valid_zip(url)]
    if len(valid_files) < 2:
        log("Not enough valid files to compare.")
        send_ntfy("⚠️ Not enough valid MTPASA files available for comparison.")
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

signal.alarm(0)  # Cancel timeout on success