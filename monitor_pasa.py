#!/usr/bin/env python3
"""
Fetches the last 2 MTPASA DUIDAvailability ZIPs from manifest.xml,
compares availability by DUID, and pushes a summary to ntfy.sh/pasa-alerts
"""
import os
import zipfile
import requests
import pandas as pd
from datetime import datetime
from io import BytesIO
from bs4 import BeautifulSoup
import signal
import sys

NTFY_TOPIC = "pasa-alerts"
MTPASA_MANIFEST = "https://nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/manifest.xml"
MTPASA_BASE = "https://nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
MAX_RUNTIME_SECONDS = 180


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def timeout_handler(signum, frame):
    log("⏱️ Timeout exceeded. Aborting.")
    send_ntfy("⚠️ PASA Monitor timed out after 3 minutes.")
    sys.exit(1)

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(MAX_RUNTIME_SECONDS)


def send_ntfy(summary):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=summary.encode("utf-8"), timeout=10)
    except Exception as e:
        log(f"Failed to send ntfy alert: {e}")


def get_last_two_zip_urls():
    log("Fetching ZIP list from manifest.xml...")
    r = requests.get(MTPASA_MANIFEST, timeout=20)
    soup = BeautifulSoup(r.text, "lxml-xml")
    files = [node.text for node in soup.find_all("FileName") if node.text.endswith(".zip")]
    files = sorted(files)[-2:]
    return [MTPASA_BASE + f for f in files]


def extract_csv_from_url(url):
    log(f"Downloading ZIP: {url}")
    r = requests.get(url, timeout=60)
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        for filename in z.namelist():
            if filename.endswith(".csv"):
                log(f"Extracting: {filename}")
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
            lines.append(f"  {row['Date']}: {int(row['Change']):+} MW")
    return "\n".join(lines)


if __name__ == "__main__":
    log("Starting PASA Monitor from manifest")
    try:
        urls = get_last_two_zip_urls()
        if len(urls) < 2:
            raise Exception("Not enough ZIPs found in manifest")
    except Exception as e:
        log(f"❌ Failed to retrieve files: {e}")
        send_ntfy(f"⚠️ Failed to load MTPASA manifest: {e}")
        sys.exit(1)

    df1 = extract_csv_from_url(urls[0])
    df2 = extract_csv_from_url(urls[1])
    changes = compare_availability(df1, df2)

    if changes.empty:
        log("No changes detected.")
    else:
        summary = format_summary(changes)
        send_ntfy(summary)
        log("Alert sent.")

signal.alarm(0)