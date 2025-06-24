import requests
import zipfile
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta
import os
import json
import argparse
import pytz

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
NTFY_URL = "https://ntfy.sh/pasa-alerts"
STORAGE_FILE = "stored_mtpasa_runs.json"
tz = pytz.timezone("Australia/Sydney")


def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = set(re.findall(r'PUBLIC_MTPASADUIDAVAILABILITY_\d{12}_\d+\.zip', r.text))
    if len(matches) < 2:
        raise ValueError("❌ Not enough ZIP files found.")

    def extract_dt(f):
        match = re.search(r'_(\d{12})_', f)
        return datetime.strptime(match.group(1), "%Y%m%d%H%M") if match else datetime.min

    sorted_files = sorted(matches, key=extract_dt, reverse=True)
    return sorted_files[1], sorted_files[0]  # old, new


def extract_csv(url):
    r = requests.get(BASE_URL + url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, skiprows=1, low_memory=False)


def group_changes(group):
    output = []
    group = group.sort_values("DAY")
    start, prev_day, prev_val = None, None, None
    for _, row in group.iterrows():
        day = pd.to_datetime(row["DAY"])
        chg = int(row["CHANGE"])
        if start is None:
            start, prev_day, prev_val = day, day, chg
            continue
        if day == prev_day + timedelta(days=1) and chg == prev_val:
            prev_day = day
        else:
            output.append((start, prev_day, prev_val))
            start, prev_day, prev_val = day, day, chg
    if start:
        output.append((start, prev_day, prev_val))
    return output


def compare_availability(df_old, df_new):
    df_old = df_old[["DUID", "DAY", "PASAAVAILABILITY"]].rename(columns={"PASAAVAILABILITY": "AVAIL_OLD"})
    df_new = df_new[["DUID", "DAY", "PASAAVAILABILITY"]].rename(columns={"PASAAVAILABILITY": "AVAIL_NEW"})
    merged = pd.merge(df_old, df_new, on=["DUID", "DAY"])
    merged["CHANGE"] = merged["AVAIL_NEW"] - merged["AVAIL_OLD"]
    changes = merged[merged["CHANGE"] != 0]

    if changes.empty:
        return "No DUID availability changes detected."

    lines = ["🔁 Changes in Availability by DUID:"]
    for duid, grp in changes.groupby("DUID"):
        ranges = group_changes(grp)
        lines.append(f"\n{duid}:")
        for start, end, chg in ranges:
            if start == end:
                lines.append(f"  {start.date()}: {chg:+} MW")
            else:
                lines.append(f"  {start.date()} to {end.date()}: {chg:+} MW")
    return "\n".join(lines)


def save_message(key, message):
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, 'r') as f:
            data = json.load(f)
    else:
        data = {}
    data[key] = message
    with open(STORAGE_FILE, 'w') as f:
        json.dump(data, f)


def load_message(key):
    if os.path.exists(STORAGE_FILE):
        with open(STORAGE_FILE, 'r') as f:
            data = json.load(f)
        return data.get(key)
    return None


def main(mode):
    now = datetime.now(tz)
    print(f"⏱️ Heartbeat: Running at {now.strftime('%Y-%m-%d %H:%M')} AEST | Mode: {mode}")

    old_file, new_file = fetch_latest_two_urls()
    df_old = extract_csv(old_file)
    df_new = extract_csv(new_file)
    message = compare_availability(df_old, df_new)

    dow = now.weekday()  # Monday = 0
    hour = now.hour

    if mode == "test":
        print("\n🧪 Running in TEST mode – simulating now.")
        print(message)
        requests.post(NTFY_URL, data=message.encode("utf-8"))
        return

    if hour == 7:
        if dow == 0:
            combined = []
            for key in ["fri_1820", "sat_0920", "sat_1220", "sat_1520", "sat_1820"]:
                part = load_message(key)
                if part:
                    combined.append(part)
            if combined:
                full = "\n\n".join(combined)
                print(full)
                requests.post(NTFY_URL, data=full.encode("utf-8"))
        elif 1 <= dow <= 4:
            part = load_message("prev_1820")
            if part:
                print(part)
                requests.post(NTFY_URL, data=part.encode("utf-8"))
    else:
        key = None
        if dow == 5:
            if hour == 9: key = "sat_0920"
            elif hour == 12: key = "sat_1220"
            elif hour == 15: key = "sat_1520"
            elif hour == 18: key = "sat_1820"
        elif dow == 4 and hour == 18:
            key = "fri_1820"
        elif dow in range(0, 5):
            if hour in [9, 12, 15]:
                print(message)
                requests.post(NTFY_URL, data=message.encode("utf-8"))
            elif hour == 18:
                save_message("prev_1820", message)

        if key:
            save_message(key, message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    main("test" if args.test else "prod")