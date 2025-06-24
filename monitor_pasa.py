#!/usr/bin/env python3
"""
Reads two most recent local ZIPs (already downloaded via wget)
and pushes availability changes by DUID to ntfy.sh/pasa-alerts
"""
import os
import zipfile
import pandas as pd
from datetime import datetime
from io import BytesIO
import signal
import sys

NTFY_TOPIC = "pasa-alerts"
ZIP_DIR = "pasa_data"
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
        import requests
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=summary.encode("utf-8"), timeout=10)
    except Exception as e:
        log(f"Failed to send ntfy alert: {e}")


def extract_csv_from_zipfile(path):
    log(f"Reading ZIP: {path}")
    with zipfile.ZipFile(path, 'r') as z:
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
    log("Starting local ZIP comparison")
    files = sorted([
        os.path.join(ZIP_DIR, f)
        for f in os.listdir(ZIP_DIR)
        if f.endswith(".zip")
    ])

    if len(files) < 2:
        log("❌ Not enough ZIP files in pasa_data/")
        send_ntfy("⚠️ Not enough local MTPASA ZIPs to compare.")
        sys.exit(1)

    file1, file2 = files[-2:]
    df1 = extract_csv_from_zipfile(file1)
    df2 = extract_csv_from_zipfile(file2)
    changes = compare_availability(df1, df2)

    if changes.empty:
        log("No changes detected.")
    else:
        summary = format_summary(changes)
        send_ntfy(summary)
        log("Alert sent.")

signal.alarm(0)