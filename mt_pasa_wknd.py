#!/usr/bin/env python3
import requests
import zipfile
import pandas as pd
import re
from io import BytesIO
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pytz
import sys

BASE_URL = "https://www.nemweb.com.au/REPORTS/CURRENT/MTPASA_DUIDAvailability/"
NTFY_URL = "https://ntfy.sh/wknd-power"

def fetch_latest_two_urls():
    r = requests.get(BASE_URL)
    r.raise_for_status()
    matches = set(re.findall(r'PUBLIC_MTPASADUIDAVAILABILITY_\d{12}_\d+\.zip', r.text))
    if len(matches) < 6:
        raise ValueError("❌ Not enough unique MTPASA ZIP files found.")
    def extract_dt(filename):
        match = re.search(r'_(\d{12})_', filename)
        return datetime.strptime(match.group(1), "%Y%m%d%H%M") if match else datetime.min
    sorted_files = sorted(matches, key=extract_dt, reverse=True)
    return BASE_URL + sorted_files[5], BASE_URL + sorted_files[0]

def extract_csv(url):
    print(f"Downloading: {url}")
    r = requests.get(url)
    r.raise_for_status()
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        file_name = z.namelist()[0]
        print(f"✅ Extracting: {file_name}")
        with z.open(file_name) as f:
            return pd.read_csv(f, skiprows=1, low_memory=False)

def group_consecutive_changes(group):
    output = []
    group = group.sort_values("DAY")
    start_date = prev_date = prev_change = None
    for _, row in group.iterrows():
        cur_date = pd.to_datetime(row["DAY"])
        cur_change = int(row["CHANGE"])
        if start_date is None:
            start_date = prev_date = cur_date
            prev_change = cur_change
            continue
        if cur_date == prev_date + timedelta(days=1) and cur_change == prev_change:
            prev_date = cur_date
        else:
            output.append((start_date, prev_date, prev_change))
            start_date = prev_date = cur_date
            prev_change = cur_change
    if start_date is not None:
        output.append((start_date, prev_date, prev_change))
    return output

def compare_availability(df_old, df_new):
    cols = ["DUID", "DAY", "PASAAVAILABILITY"]
    df_old = df_old[cols].copy()
    df_new = df_new[cols].copy()
    df_old.rename(columns={"PASAAVAILABILITY": "AVAIL_OLD"}, inplace=True)
    df_new.rename(columns={"PASAAVAILABILITY": "AVAIL_NEW"}, inplace=True)
    merged = pd.merge(df_old, df_new, on=["DUID", "DAY"])
    merged["CHANGE"] = merged["AVAIL_NEW"] - merged["AVAIL_OLD"]
    changes = merged[merged["CHANGE"] != 0]

    # Load UNIT_NAME and REGION
    try:
        duid_info = pd.read_csv("duid_info.csv")
        unit_name_map = duid_info.set_index("DUID")["UNIT_NAME"].to_dict()
        region_map = duid_info.set_index("DUID")["REGION"].to_dict()
    except Exception as e:
        print(f"⚠️ Could not load duid_info.csv: {e}")
        unit_name_map = {}
        region_map = {}

    # Load Owner, Units, Capacity
    try:
        duid_meta = pd.read_csv("duid_owner_units_capacity.csv")
        duid_meta["DUID"] = duid_meta["DUID"].astype(str).str.strip().str.upper()
        duid_meta = duid_meta[duid_meta["DUID"] != ""].drop_duplicates(subset="DUID")
        meta_map = duid_meta.set_index("DUID")[["Owner", "Number of Units", "Nameplate Capacity (MW)"]].to_dict("index")
    except Exception as e:
        print(f"⚠️ Could not load duid_owner_units_capacity.csv: {e}")
        meta_map = {}

    message_lines = []

    if changes.empty:
        message_lines.append("No DUID availability changes detected.")
    else:
        message_lines.append("🔄 Changes in Availability by DUID (≥100 MW):")
        for duid, group in changes.groupby("DUID"):
            grouped_ranges = group_consecutive_changes(group)
            if all(abs(change) < 100 for _, _, change in grouped_ranges):
                continue
            name = unit_name_map.get(duid, duid)
            region = region_map.get(duid, "UNKNOWN")
            meta = meta_map.get(duid, {})
            owner = meta.get("Owner", "UNKNOWN")
            capacity = meta.get("Nameplate Capacity (MW)", "UNKNOWN")
            units = meta.get("Number of Units", "UNKNOWN")
            message_lines.append(f"\n🔺 {duid} | {name} | {owner} | {region}")
            message_lines.append(f"   ➤ Full capacity: {capacity} MW | Units: {units}")
            for start, end, change in grouped_ranges:
                if abs(change) < 100:
                    continue

                # ── replaced duration/label with relativedelta ──
                rd = relativedelta(end, start)
                parts = []
                if rd.years:
                    parts.append(f"{rd.years} year{'s' if rd.years>1 else ''}")
                if rd.months:
                    parts.append(f"{rd.months} month{'s' if rd.months>1 else ''}")
                if rd.days:
                    parts.append(f"{rd.days} day{'s' if rd.days>1 else ''}")
                label = " ".join(parts) or "0 days"
                # ── end replacement ──

                qtr = f"Q{((start.month - 1) // 3) + 1} {start.year}"
                message_lines.append(f"   ➤ {start.date()} to {end.date()} ({label}, {qtr}): {change:+} MW")

    full_message = "\n".join(message_lines)
    print("\n" + full_message)
    requests.post(NTFY_URL, data=full_message.encode("utf-8"))

def run_scheduler(test_mode=False):
    if test_mode:
        print("Running in TEST mode – simulating now.")
    else:
        tz = pytz.timezone("Australia/Sydney")
        now = datetime.now(tz)
        print(f"Current AEST Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        url_old, url_new = fetch_latest_two_urls()
        df_old = extract_csv(url_old)
        df_new = extract_csv(url_new)
        compare_availability(df_old, df_new)
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    test_mode = "--test" in sys.argv
    run_scheduler(test_mode=test_mode)
